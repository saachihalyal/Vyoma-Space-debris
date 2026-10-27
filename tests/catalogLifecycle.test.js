import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { API_BASE, getCatalog, getForecast, getConjunctions, getManeuver } from "../src/api/ssaClient.js";
import { datasetLabel, retainCatalogSnapshot, sourceLabel } from "../src/utils/catalogStatus.js";
import { createRequestSequence, ignoreAbort } from "../src/utils/requestSequence.js";
import { beginScreeningAttempt, collisionScreeningState, createExplicitRefreshHandler, finishScreeningAttempt, reconcilePhysicalEventSelection, resolvePhysicalEventSelection, retainSelectedPhysicalEvent, screeningResultMatchesRun, screeningStatusForEmptyResults, screeningSummaryDisplay, shouldStartScreeningRun, updateScreeningAttempt } from "../src/utils/screeningRefreshPolicy.js";
import { maneuverPageState, resolveManeuverEvent } from "../src/utils/maneuverSelection.js";
import { readWatchlist } from "../src/utils/watchlistStorage.js";

const capturedScreeningEvent = JSON.parse(readFileSync(new URL("./fixtures/capturedRealScreeningEvent.json", import.meta.url), "utf8"));

test("detached request chains consume expected aborts but report other failures", async () => {
  let reported = 0;
  await ignoreAbort(Promise.reject(Object.assign(new Error("cancelled"), { name: "AbortError" })), () => { reported += 1; });
  await ignoreAbort(Promise.reject(new Error("network failure")), () => { reported += 1; });
  assert.equal(reported, 1);
});

test("malformed or inaccessible watchlist storage cannot prevent app initialization", () => {
  assert.deepEqual(readWatchlist({ getItem: () => "{" }), []);
  assert.deepEqual(readWatchlist({ getItem: () => "{\"watchlist\":[]}" }), []);
  assert.deepEqual(readWatchlist({ getItem: () => "[\"NORAD-1\", 42, null]" }), ["NORAD-1", 42]);
  assert.deepEqual(readWatchlist({ getItem: () => { throw new Error("storage blocked"); } }), []);
});

test("catalog requests are shared and independent of forecast horizon", async () => {
  const originalFetch = globalThis.fetch;
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(String(url));
    await new Promise((resolve) => setTimeout(resolve, 10));
    return new Response(JSON.stringify({ objects: [], risk_cells: [], stats: {} }), { status: 200 });
  };
  try {
    const obsolete = new AbortController();
    const first = getCatalog({ forecastHours: 63, limit: 650, signal: obsolete.signal });
    const second = getCatalog({ forecastHours: 84, limit: 650 });
    obsolete.abort();
    await assert.rejects(first, { name: "AbortError" });
    await second;
    assert.equal(urls.length, 1);
    assert.match(urls[0], /forecast_hours=0/);
    assert.doesNotMatch(urls[0], /forecast_hours=(63|84)/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("catalog transport failure is represented as unavailable, not synthetic fallback", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  try {
    const snapshot = await getCatalog({ limit: 651 });
    assert.equal(snapshot.source_state.status, "unavailable");
    assert.equal(snapshot.source_summary.status, "unavailable");
    assert.deepEqual(snapshot.objects, []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("identical in-flight conjunction jobs are shared and preserve screening configuration", async () => {
  const originalFetch = globalThis.fetch;
  const urls = [];
  let created = 0;
  globalThis.fetch = async (url, options = {}) => {
    urls.push(String(url));
    if (options.method === "POST") {
      created += 1;
      return new Response(JSON.stringify({ job_id: "job-1", status: "queued" }), { status: 202 });
    }
    return new Response(JSON.stringify({
      job_id: "job-1", status: "complete", completion_status: "complete",
      result: { data: [], result_status: "valid_empty", completion_status: "complete" },
    }), { status: 200 });
  };
  try {
    const results = await Promise.all([
      getConjunctions({ limit: 120, horizonHours: 24, catalogIdentity: "catalog-a", startUtc: "2026-10-10T00:00:00Z" }),
      getConjunctions({ limit: 120, horizonHours: 24, catalogIdentity: "catalog-a", startUtc: "2026-10-10T00:00:00Z" }),
    ]);
    assert.equal(created, 1);
    assert.equal(urls.length, 2);
    assert.match(urls[0], /api\/conjunction-jobs\?/);
    assert.match(urls[0], /limit=120/);
    assert.match(urls[0], /horizon_hours=24/);
    assert.match(urls[0], /sample_step_seconds=60/);
    assert.match(urls[0], /screening_threshold_km=25/);
    assert.match(urls[0], /start_utc=2026-10-10T00%3A00%3A00Z/);
    assert.equal(results[0].completion_status, "complete");
    assert.equal(results[0].result_status, "valid_empty");
    await getConjunctions({ limit: 120, horizonHours: 24, catalogIdentity: "catalog-b", startUtc: "2026-10-10T00:00:00Z" });
    assert.equal(created, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("passive refresh can detach a UI subscription without cancelling Stage 2A polling", async () => {
  const originalFetch = globalThis.fetch;
  let created = 0;
  let polls = 0;
  globalThis.fetch = async (_url, options = {}) => {
    if (options.method === "POST") {
      created += 1;
      return new Response(JSON.stringify({ job_id: "refresh-job", status: "queued" }), { status: 202 });
    }
    polls += 1;
    return new Response(JSON.stringify(polls === 1
      ? { job_id: "refresh-job", status: "running" }
      : { job_id: "refresh-job", status: "complete", result: { data: [], result_status: "valid_empty" } }), { status: 200 });
  };
  try {
    const controller = new AbortController();
    const config = { startUtc: "2026-10-11T00:00:00Z", catalogIdentity: "refresh-detach", pollIntervalMs: 1 };
    const detached = getConjunctions({ ...config, signal: controller.signal });
    const attached = getConjunctions(config);
    controller.abort();
    await assert.rejects(detached, { name: "AbortError" });
    const result = await attached;
    assert.equal(result.completion_status, "complete");
    assert.equal(result.result_status, "valid_empty");
    assert.equal(created, 1);
    assert.equal(polls, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("polling times out explicitly without claiming the backend job was cancelled", async () => {
  const originalFetch = globalThis.fetch;
  let polls = 0;
  globalThis.fetch = async (_url, options = {}) => options.method === "POST"
    ? new Response(JSON.stringify({ job_id: "slow-job", status: "queued" }), { status: 202 })
    : (polls += 1, new Response(JSON.stringify({ job_id: "slow-job", status: "running" }), { status: 200 }));
  try {
    const result = await getConjunctions({ startUtc: "2026-10-11T00:00:01Z", catalogIdentity: "timeout", pollTimeoutMs: 10, pollIntervalMs: 25 });
    assert.equal(result.result_status, "timeout");
    assert.equal(result.completion_status, "failed");
    assert.equal(result.job_id, "slow-job");
    assert.match(result.reason, /did not cancel it/);
    assert.equal(polls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("a backend-reported cancelled job is distinguished from a detached UI subscription", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_url, options = {}) => options.method === "POST"
    ? new Response(JSON.stringify({ job_id: "cancelled-job", status: "queued" }), { status: 202 })
    : new Response(JSON.stringify({ job_id: "cancelled-job", status: "cancelled", reason: "cancelled by operator" }), { status: 200 });
  try {
    const result = await getConjunctions({ startUtc: "2026-10-11T00:00:02Z", catalogIdentity: "cancelled", pollIntervalMs: 1 });
    assert.equal(result.api_status, "cancelled");
    assert.equal(result.result_status, "cancelled");
    assert.equal(result.completion_status, "cancelled");
    assert.equal(result.reason, "cancelled by operator");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maneuver evaluation posts the selected physical event and shares duplicate requests", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const event = {
    id: "event-real-1",
    result_kind: "physics_assessment",
    physics_result: {
      tca: { status: "available", value: "2026-10-10T00:00:00Z" },
      primary_state_at_tca: { object_id: "10001", frame: "TEME", epoch: "2026-10-10T00:00:00Z" },
      secondary_state_at_tca: { object_id: "10002", frame: "TEME", epoch: "2026-10-10T00:00:00Z" },
    },
  };
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return new Response(JSON.stringify({ screening_job_id: "screen-job-1", data: { status: "available", event_id: event.id, candidates: [] } }), { status: 200 });
  };
  try {
    const [first, second] = await Promise.all([
      getManeuver(event, { screeningJobId: "screen-job-1", leadSeconds: 420, maxDeltaVMs: 0.08, initialMassKg: 850, specificImpulseS: 310 }),
      getManeuver(event, { screeningJobId: "screen-job-1", leadSeconds: 420, maxDeltaVMs: 0.08, initialMassKg: 850, specificImpulseS: 310 }),
    ]);
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /api\/conjunctions\/event-real-1\/maneuver/);
    assert.match(calls[0].url, /screening_job_id=screen-job-1/);
    assert.match(calls[0].url, /lead_seconds=420/);
    assert.match(calls[0].url, /max_delta_v_m_s=0.08/);
    assert.match(calls[0].url, /initial_mass_kg=850/);
    assert.match(calls[0].url, /specific_impulse_s=310/);
    assert.equal(calls[0].options.method, "POST");
    assert.deepEqual(JSON.parse(calls[0].options.body), event);
    assert.equal(first.event_id, event.id);
    assert.equal(second.event_id, event.id);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maneuver evaluation rejects an event already bound to another screening job", async () => {
  const event = { id: "event-cross-job", result_kind: "physics_assessment", screening_job_id: "job-A" };
  await assert.rejects(
    getManeuver(event, { screeningJobId: "job-B" }),
    /selected event belongs to a different screening job/,
  );
});

test("maneuver evaluation rejects response event or screening job identity mismatches", async () => {
  const originalFetch = globalThis.fetch;
  const event = { id: "event-bound", result_kind: "physics_assessment" };
  try {
    for (const [responseJobId, responseEventId, expected] of [
      ["other-job", event.id, /screening job ID does not match/],
      ["screen-job-1", "other-event", /event ID does not match/],
    ]) {
      globalThis.fetch = async () => new Response(JSON.stringify({
        screening_job_id: responseJobId,
        data: { status: "available_with_warning", event_id: responseEventId },
      }), { status: 200 });
      await assert.rejects(getManeuver(event, { screeningJobId: "screen-job-1" }), expected);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maneuver evaluation reports a missing screening job ID as an incompatible response", async () => {
  const originalFetch = globalThis.fetch;
  const event = { id: "event-bound", result_kind: "physics_assessment" };
  globalThis.fetch = async () => new Response(JSON.stringify({
    success: true,
    data: { status: "available", event_id: event.id, physics_candidate_status: "evaluated", ml_result: { status: "not_implemented" } },
  }), { status: 200 });
  try {
    await assert.rejects(
      getManeuver(event, { screeningJobId: "screen-job-1" }),
      /response is missing its screening job ID; this backend cannot confirm/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("screening poll rejects a status payload that identifies a different job", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_url, options = {}) => options.method === "POST"
    ? new Response(JSON.stringify({ job_id: "accepted-job", status: "queued" }), { status: 202 })
    : new Response(JSON.stringify({ job_id: "other-job", status: "complete", result: { data: [] } }), { status: 200 });
  try {
    const result = await getConjunctions({
      startUtc: "2026-10-20T00:00:00Z", catalogIdentity: "poll-job-identity-mismatch",
      pollTimeoutMs: 1000, pollIntervalMs: 1,
    });
    assert.equal(result.job_id, "accepted-job");
    assert.equal(result.result_status, "unavailable");
    assert.equal(result.reason_code, "JOB_ID_MISMATCH");
    assert.match(result.reason, /does not match the accepted job/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maneuver reports the backend identity reason code and message", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: { reason_code: "JOB_INCOMPLETE", message: "A partial screening job cannot be used." },
  }), { status: 409 });
  try {
    await assert.rejects(
      getManeuver({ id: "event-partial", result_kind: "physics_assessment" }, { screeningJobId: "partial-job" }),
      /JOB_INCOMPLETE: A partial screening job cannot be used/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("screening job polling exposes running status and then terminal results", async () => {
  const originalFetch = globalThis.fetch;
  const statuses = [];
  let polls = 0;
  globalThis.fetch = async (url, options = {}) => {
    if (options.method === "POST") return new Response(JSON.stringify({ job_id: "job-running", status: "queued" }), { status: 202 });
    polls += 1;
    if (polls === 1) return new Response(JSON.stringify({ job_id: "job-running", status: "running", progress: { stage: "trajectory_screening", percent: null } }), { status: 200 });
    return new Response(JSON.stringify({
      job_id: "job-running", status: "partial", completion_status: "partial",
      result: { data: [], result_status: "partial", completion_status: "partial" },
    }), { status: 200 });
  };
  try {
    const result = await getConjunctions({ startUtc: "2026-10-10T00:00:00Z", onStatus: (status) => statuses.push(status.status) });
    assert.deepEqual(statuses, ["queued", "running", "partial"]);
    assert.equal(result.completion_status, "partial");
    assert.equal(result.result_status, "partial");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("a timed-out status read retries the same job until its partial result arrives", async () => {
  const originalFetch = globalThis.fetch;
  const statuses = [];
  let polls = 0;
  globalThis.fetch = async (_url, options = {}) => {
    if (options.method === "POST") {
      return new Response(JSON.stringify({ job_id: "slow-status-job", status: "queued" }), { status: 202 });
    }
    polls += 1;
    if (polls === 1) {
      return new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new DOMException("request aborted", "AbortError")), { once: true });
      });
    }
    return new Response(JSON.stringify({
      job_id: "slow-status-job",
      status: "partial",
      completion_status: "partial",
      result: { data: [{ id: "accepted-event" }], result_status: "partial", completion_status: "partial" },
    }), { status: 200 });
  };
  try {
    const result = await getConjunctions({
      startUtc: "2026-10-19T00:00:00Z",
      catalogIdentity: "status-timeout-retry",
      pollTimeoutMs: 1000,
      pollIntervalMs: 1,
      requestTimeoutMs: 10,
      onStatus: (status) => statuses.push(status),
    });
    assert.equal(polls, 2);
    assert.equal(result.job_id, "slow-status-job");
    assert.equal(result.completion_status, "partial");
    assert.equal(result.result_status, "partial");
    assert.deepEqual(result.data, [{ id: "accepted-event" }]);
    assert.ok(statuses.some((status) => status.progress?.stage === "status_retry"));
    assert.ok(statuses.every((status) => status.result_status !== "timeout"));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("screening transport failures remain errors rather than valid empty results", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new TypeError("network unavailable for test"); };
  try {
    const result = await getConjunctions({ startUtc: "2026-10-10T00:00:00Z", catalogIdentity: "failure-test" });
    assert.equal(result.api_status, "error");
    assert.equal(result.completion_status, "failed");
    assert.equal(result.result_status, "unavailable");
    assert.equal(result.reason, "network unavailable for test");
    assert.deepEqual(result.data, []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("a job lost from the backend registry is reported unavailable and a later explicit run can complete", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  let created = 0;
  globalThis.fetch = async (url, options = {}) => {
    const requestUrl = String(url);
    requests.push({ url: requestUrl, method: options.method || "GET" });
    if (options.method === "POST") {
      created += 1;
      const jobId = created === 1 ? "job-lost-after-restart" : "job-retry";
      return new Response(JSON.stringify({ job_id: jobId, status: "queued" }), { status: 202 });
    }
    if (requestUrl.endsWith("/job-lost-after-restart")) {
      return new Response(JSON.stringify({ detail: "Screening job not found in this backend process." }), { status: 404 });
    }
    return new Response(JSON.stringify({
      job_id: "job-retry", status: "complete", completion_status: "complete",
      result: { data: [], result_status: "valid_empty", completion_status: "complete" },
    }), { status: 200 });
  };
  try {
    let failedAttempt = beginScreeningAttempt({
      conjunctions: [], conjunctionStatus: { api_status: "idle", result_status: "not_started" }, screeningAttempt: null,
    }, { run_id: "run-lost", result_status: "queued", job_id: null });
    const failedResult = await getConjunctions({
      startUtc: "2026-10-14T00:00:00Z", catalogIdentity: "registry-loss", pollIntervalMs: 1,
      onStatus: (status) => { failedAttempt = updateScreeningAttempt(failedAttempt, "run-lost", { job_id: status.job_id, result_status: status.result_status }); },
    });
    failedAttempt = finishScreeningAttempt(failedAttempt, "run-lost", failedResult, []);
    assert.deepEqual(requests.slice(0, 2).map((request) => request.method), ["POST", "GET"]);
    assert.match(requests[1].url, /api\/conjunction-jobs\/job-lost-after-restart$/);
    assert.equal(failedResult.api_status, "error");
    assert.equal(failedResult.result_status, "unavailable");
    assert.equal(failedResult.job_id, "job-lost-after-restart");
    assert.deepEqual(failedResult.data, []);
    const unavailableForDisplay = screeningStatusForEmptyResults(failedAttempt.conjunctionStatus, failedAttempt.screeningAttempt);
    assert.equal(unavailableForDisplay.result_status, "unavailable");
    assert.match(unavailableForDisplay.reason, /job is no longer available; rerun screening/i);
    assert.deepEqual(screeningSummaryDisplay(failedAttempt.conjunctionStatus, failedAttempt.screeningAttempt), {
      label: "Latest screening attempt",
      text: "unavailable · failed · job job-lost-after-restart",
    });

    assert.equal(shouldStartScreeningRun({ explicitRefresh: true, runActive: false }), true);
    let retryAttempt = beginScreeningAttempt(failedAttempt, { run_id: "run-retry", result_status: "queued", job_id: null });
    const retryResult = await getConjunctions({
      startUtc: "2026-10-14T00:01:00Z", catalogIdentity: "registry-retry", pollIntervalMs: 1,
      onStatus: (status) => { retryAttempt = updateScreeningAttempt(retryAttempt, "run-retry", { job_id: status.job_id, result_status: status.result_status }); },
    });
    const acceptedRetry = finishScreeningAttempt(retryAttempt, "run-retry", retryResult, []);
    assert.equal(retryResult.job_id, "job-retry");
    assert.equal(acceptedRetry.conjunctionStatus.result_status, "valid_empty");
    assert.equal(acceptedRetry.conjunctionStatus.job_id, "job-retry");
    assert.equal(requests.filter((request) => request.method === "POST").length, 2);
    assert.ok(requests.some((request) => request.url.endsWith("/api/conjunction-jobs/job-retry")));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("job creation without a returned job ID becomes unavailable and does not poll", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url: String(url), method: options.method || "GET" });
    return new Response(JSON.stringify({ status: "queued" }), { status: 202 });
  };
  try {
    const result = await getConjunctions({ startUtc: "2026-10-14T00:02:00Z", catalogIdentity: "missing-job-id" });
    assert.equal(result.api_status, "error");
    assert.equal(result.result_status, "unavailable");
    assert.equal(result.job_id, null);
    assert.match(result.reason, /did not contain a job ID/);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].method, "POST");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("forecast transport failure does not invent forecast frames", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  try {
    const forecast = await getForecast({ horizonHours: 168, steps: 9 });
    assert.equal(forecast.source_state.status, "unavailable");
    assert.deepEqual(forecast.frames, []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("older responses cannot be applied after a newer request starts", () => {
  const sequence = createRequestSequence();
  const oldRequest = sequence.next();
  const newestRequest = sequence.next();
  assert.equal(sequence.isCurrent(oldRequest), false);
  assert.equal(sequence.isCurrent(newestRequest), true);
});

test("periodic catalog refresh does not start a replacement physical screening job", () => {
  assert.equal(shouldStartScreeningRun({ explicitRefresh: false, runActive: false }), false);
  for (let refresh = 0; refresh < 4; refresh += 1) {
    assert.equal(shouldStartScreeningRun({ explicitRefresh: false, runActive: true }), false);
  }
  assert.equal(shouldStartScreeningRun({ explicitRefresh: true, runActive: true }), false);
  assert.equal(shouldStartScreeningRun({ explicitRefresh: true, runActive: false }), true);
});

test("explicit TopBar refresh enters the job flow once while startup and periodic refresh stay passive", async () => {
  const originalFetch = globalThis.fetch;
  const originalConsoleInfo = console.info;
  const calls = [];
  const postDiagnostics = [];
  const clickIds = [];
  let runActive = false;
  let created = 0;
  let polls = 0;
  let releaseCatalog;
  let signalCatalogStarted;
  let signalPostStarted;
  const catalogGate = new Promise((resolve) => { releaseCatalog = resolve; });
  const catalogStarted = new Promise((resolve) => { signalCatalogStarted = resolve; });
  const postStarted = new Promise((resolve) => { signalPostStarted = resolve; });
  globalThis.fetch = async (url, options = {}) => {
    const requestUrl = String(url);
    calls.push({ url: requestUrl, method: options.method || "GET" });
    if (requestUrl.includes("/api/catalog?")) {
      signalCatalogStarted();
      await catalogGate;
      return new Response(JSON.stringify({ objects: [{ catalog_id: "25544" }], source_state: { status: "available" } }), { status: 200 });
    }
    if (options.method === "POST") {
      signalPostStarted();
      created += 1;
      return new Response(JSON.stringify({ job_id: "manual-refresh-job", status: "queued" }), { status: 202 });
    }
    polls += 1;
    return new Response(JSON.stringify({
      job_id: "manual-refresh-job", status: "complete", completion_status: "complete",
      result: { data: [], result_status: "valid_empty", completion_status: "complete" },
    }), { status: 200 });
  };
  console.info = (message, details) => {
    if (message === "[ORION screening diagnostic] POST starting") postDiagnostics.push(details);
  };
  try {
    const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
    assert.match(appSource, /refresh=\{startScreening\}/);
    assert.match(appSource, /onStartScreening=\{startScreening\}/);
    assert.match(appSource, /const explicitRefresh = explicitScreeningRefreshRef\.current;/);
    assert.match(appSource, /onClick=\{refresh\}/);
    assert.match(appSource, /const explicitRefresh = \(invocationId, options = \{\}\) => \{[\s\S]*load\(\{ explicitScreeningRefresh: true, invocationId, \.\.\.options \}\);/);
    assert.match(appSource, /load\(\{ explicitScreeningRefresh: false \}\);/);
    assert.match(appSource, /setInterval\(\(\) => load\(\{ explicitScreeningRefresh: false \}\)/);
    assert.match(appSource, /result_status: "not_started"/);
    assert.match(readFileSync(new URL("../src/components/UI/CollisionWorkbench.jsx", import.meta.url), "utf8"), /Run screening to populate physical encounter groups/);

    let requestId = 0;
    let activeController = null;
    const load = async ({ explicitScreeningRefresh = false, invocationId = null } = {}) => {
      const thisRequestId = ++requestId;
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        const catalog = await getCatalog({ limit: 652, signal: controller.signal });
        if (thisRequestId !== requestId || !catalog || !shouldStartScreeningRun({ explicitRefresh: explicitScreeningRefresh, runActive })) return null;
        runActive = true;
        return getConjunctions({ startUtc: "2026-10-14T00:00:00Z", catalogIdentity: "manual-topbar-refresh", diagnosticInvocationId: invocationId, pollIntervalMs: 1 })
          .finally(() => { runActive = false; });
      } catch (error) {
        if (error?.name === "AbortError") return null;
        throw error;
      }
    };
    // TopBar's callback calls the same explicit load path directly; it no longer
    // depends on a state change causing a second effect to capture the intent.
    const topBarRefresh = createExplicitRefreshHandler((invocationId) => {
      clickIds.push(invocationId);
      return load({ explicitScreeningRefresh: true, invocationId });
    });
    const startupPromise = load({ explicitScreeningRefresh: false });
    await catalogStarted;
    const resultPromise = topBarRefresh();
    assert.equal(await startupPromise, null); // the explicit refresh cancels the passive subscription
    releaseCatalog();
    await postStarted;
    // A second click while the job is active must not create a second job.
    const duplicatePromise = topBarRefresh();
    const result = await resultPromise;
    assert.equal(await duplicatePromise, null);
    assert.equal(await load({ explicitScreeningRefresh: false }), null); // periodic refresh is passive with a ready catalogue
    assert.equal(result?.job_id, "manual-refresh-job");
    assert.equal(result?.completion_status, "complete");
    const subsequentResult = await topBarRefresh();
    assert.equal(subsequentResult?.job_id, "manual-refresh-job");
    assert.equal(subsequentResult?.completion_status, "complete");
    assert.equal(created, 2);
    assert.equal(polls, 2);
    assert.equal(calls.filter((call) => call.method === "POST").length, 2);
    assert.equal(clickIds.length, 3);
    assert.ok(clickIds.every((id) => /^refresh-\d+-\d+$/.test(id)));
    assert.equal(new Set(clickIds).size, 3);
    assert.equal(postDiagnostics.length, 2);
    assert.equal(postDiagnostics[0].invocationId, clickIds[0]);
    assert.ok(calls.filter((call) => call.method === "POST").every((call) => call.url.startsWith(`${API_BASE}/api/conjunction-jobs?`)));
    assert.equal(API_BASE, "http://127.0.0.1:8001");
  } finally {
    globalThis.fetch = originalFetch;
    console.info = originalConsoleInfo;
  }
});

test("a pending replacement and its failure preserve accepted events, job, and selected event", () => {
  const event = { id: "EV-1", result_kind: "physics_assessment" };
  const completed = {
    conjunctions: [event],
    conjunctionStatus: { api_status: "available", result_status: "valid_non_empty", completion_status: "complete", job_id: "job-1", screening: { candidate_pair_count: 7 } },
    selectedEvent: event,
  };
  assert.equal(shouldStartScreeningRun({ explicitRefresh: false, runActive: true }), false);
  const pending = beginScreeningAttempt(completed, { run_id: "run-2", result_status: "queued", job_id: null });
  assert.deepEqual(pending.conjunctions, completed.conjunctions);
  assert.equal(pending.conjunctionStatus.job_id, "job-1");
  assert.equal(pending.selectedEvent.id, "EV-1");
  const failed = finishScreeningAttempt(pending, "run-2", { api_status: "error", result_status: "unavailable", completion_status: "failed", reason: "screen failed" }, []);
  assert.deepEqual(failed.conjunctions, completed.conjunctions);
  assert.equal(failed.conjunctionStatus.job_id, "job-1");
  assert.equal(failed.screeningAttempt.completion_status, "failed");
  assert.equal(failed.selectedEvent.id, "EV-1");
  assert.equal(finishScreeningAttempt(failed, "old-run", { completion_status: "complete", result_status: "valid_empty", data: [] }, []).screeningAttempt.run_id, "run-2");
});

test("latest failed attempt is shown when no accepted result exists, without replacing a prior accepted job", () => {
  const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const controlsSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(controlsSource, /attemptStatus\.reason/);
  assert.match(controlsSource, /Last accepted run/);
  const initial = {
    conjunctions: [],
    conjunctionStatus: { api_status: "idle", result_status: "not_started" },
    screeningAttempt: null,
  };
  const pending = beginScreeningAttempt(initial, { run_id: "run-lost", result_status: "queued", job_id: "job-lost" });
  const failed = finishScreeningAttempt(pending, "run-lost", {
    api_status: "error", job_id: "job-lost", completion_status: "failed",
    result_status: "unavailable", reason: "SSA API returned 404 reading the screening job", data: [],
  }, []);
  assert.equal(failed.conjunctionStatus.result_status, "not_started");
  assert.equal(failed.screeningAttempt.job_id, "job-lost");
  const emptyStateStatus = screeningStatusForEmptyResults(failed.conjunctionStatus, failed.screeningAttempt);
  assert.equal(emptyStateStatus.result_status, "unavailable");
  assert.equal(emptyStateStatus.completion_status, "failed");
  assert.equal(emptyStateStatus.job_id, "job-lost");
  assert.match(emptyStateStatus.reason, /404/);

  const oldEvent = { id: "EV-old", result_kind: "physics_assessment" };
  const acceptedOldRun = {
    conjunctions: [oldEvent],
    conjunctionStatus: { api_status: "available", result_status: "valid_non_empty", completion_status: "complete", job_id: "job-old" },
  };
  assert.equal(screeningStatusForEmptyResults(acceptedOldRun.conjunctionStatus, failed.screeningAttempt), acceptedOldRun.conjunctionStatus);
  assert.deepEqual(screeningSummaryDisplay(acceptedOldRun.conjunctionStatus, failed.screeningAttempt), {
    label: "Last accepted result",
    text: "valid_non_empty · complete · job job-old",
  });
  assert.deepEqual(acceptedOldRun.conjunctions, [oldEvent]);
  assert.match(appSource, /screeningSummaryDisplay\(eventStatus, attemptStatus\)/);
});

test("a successful replacement binds physical events to its job and clears unrelated selections", () => {
  const prior = { id: "EV-old", result_kind: "physics_assessment" };
  const next = { id: "EV-next", result_kind: "physics_assessment" };
  const proxy = { id: "SP-1", result_kind: "screening_proxy" };
  const initial = {
    conjunctions: [prior], conjunctionStatus: { job_id: "job-old" }, selectedEvent: prior,
    screeningAttempt: { run_id: "run-next", result_status: "running", job_id: "job-next" },
  };
  const payload = { api_status: "available", completion_status: "complete", result_status: "valid_non_empty", job_id: "job-next", data: [next, proxy] };
  const accepted = finishScreeningAttempt(initial, "run-next", payload, [next]);
  assert.deepEqual(accepted.conjunctions, [next]);
  assert.equal(accepted.conjunctionStatus.job_id, "job-next");
  assert.equal(retainSelectedPhysicalEvent(prior, accepted.conjunctions), null);
  assert.equal(retainSelectedPhysicalEvent({ id: "EV-old", result_kind: "screening_proxy" }, accepted.conjunctions), null);
  assert.equal(retainSelectedPhysicalEvent(next, accepted.conjunctions), next);
});

test("a terminal payload from a different job cannot replace the accepted result", () => {
  const oldEvent = { id: "EV-old", result_kind: "physics_assessment" };
  const state = {
    conjunctions: [oldEvent],
    conjunctionStatus: { job_id: "job-old", result_status: "valid_non_empty", completion_status: "complete" },
    screeningAttempt: { run_id: "run-current", job_id: "job-current", result_status: "running" },
  };
  const result = finishScreeningAttempt(state, "run-current", {
    api_status: "available", job_id: "job-old", completion_status: "complete", result_status: "valid_empty", data: [],
  }, []);
  assert.deepEqual(result.conjunctions, [oldEvent]);
  assert.equal(result.conjunctionStatus.job_id, "job-old");
  assert.equal(result.screeningAttempt.job_id, "job-current");
  assert.match(result.screeningAttempt.reason, /did not match/);
});

test("a matching completed screening run reconciles selection to its accepted physical event", () => {
  const event = { id: "EV-new", result_kind: "physics_assessment", physics_result: { status: "valid" } };
  const payload = { job_id: "job-new", completion_status: "complete", result_status: "valid_non_empty", data: [event] };
  assert.equal(screeningResultMatchesRun({ runId: "run-new", jobId: "job-new" }, payload), true);
  const selected = reconcilePhysicalEventSelection({ event: { ...event }, context: { ...event }, notice: null }, [event]);
  assert.equal(selected.event, event);
  assert.equal(selected.context, event);
  assert.equal(selected.notice, null);
});

test("an accepted run automatically selects the earliest valid physical event when there is no selection", () => {
  const later = { id: "EV-later", result_kind: "physics_assessment", physics_result: { status: "valid", tca: { value: "2030-01-02T00:00:00Z" } } };
  const earliest = { id: "EV-earliest", result_kind: "physics_assessment", physics_result: { status: "valid", tca: { value: "2030-01-01T00:00:00Z" } } };
  const invalid = { id: "EV-invalid", result_kind: "physics_assessment", physics_result: { status: "invalid", tca: { value: "2029-12-31T00:00:00Z" } } };
  const selection = reconcilePhysicalEventSelection(null, [later, invalid, earliest]);
  assert.strictEqual(selection.event, earliest);
  assert.strictEqual(selection.context, earliest);
  assert.equal(selection.notice, null);
});

test("an empty accepted run clears an unselected event without inventing a selection", () => {
  assert.deepEqual(reconcilePhysicalEventSelection(null, []), { event: null, context: null, notice: null });
});

test("Collision Analysis lifecycle labels follow backend-reported attempt and accepted-result states", () => {
  assert.equal(collisionScreeningState({}, null), "ready");
  assert.equal(collisionScreeningState({}, { result_status: "queued" }), "starting");
  assert.equal(collisionScreeningState({}, { result_status: "running", progress: { percent: null } }), "running");
  assert.equal(collisionScreeningState({ job_id: "job-1", completion_status: "complete", result_status: "valid_empty" }), "completed");
  assert.equal(collisionScreeningState({}, { completion_status: "failed", result_status: "unavailable" }), "failed");
});

test("a prior selection absent from accepted results is cleared with an explicit notice", () => {
  const prior = { id: "EV-old", result_kind: "physics_assessment" };
  const next = { id: "EV-next", result_kind: "physics_assessment" };
  const selection = reconcilePhysicalEventSelection({ event: prior, context: prior, notice: null }, [next]);
  assert.equal(selection.event, null);
  assert.match(selection.notice, /not present in the accepted screening result/);
});

test("a physical selection with changed identity is not rebound to a similar event", () => {
  const prior = {
    id: "EV-old-identity", result_kind: "physics_assessment",
    primary: { id: "A" }, secondary: { id: "B" },
    physics_result: { status: "valid", tca: { value: "2030-01-01T00:00:00Z" } },
  };
  const current = { ...prior, id: "EV-new-identity" };
  const selection = reconcilePhysicalEventSelection(
    { event: prior, context: prior, notice: null },
    [current],
  );
  assert.equal(selection.event, null);
  assert.equal(selection.context, prior);
  assert.match(selection.notice, /not present in the accepted screening result/);
});

test("reconciliation keeps the exact encounter when the same object pair has multiple TCAs", () => {
  const selected = {
    id: "CA-encounter-one",
    result_kind: "physics_assessment",
    primary: { id: "A" },
    secondary: { id: "B" },
    physics_result: { status: "valid", tca_status: "valid", tca: { value: "2030-01-01T00:00:00.000000+00:00" } },
    automatic_research_pc_assessment: { log10_pc: -8 },
  };
  const samePairDifferentTca = {
    ...selected,
    id: "CA-encounter-two",
    physics_result: { status: "valid", tca: { value: "2030-01-01T06:00:00.000000+00:00" } },
  };
  const acceptedCopyOfSelection = { ...selected, screening_job_marker: "job-B" };
  const selection = reconcilePhysicalEventSelection(
    { event: selected, context: selected, notice: null },
    [samePairDifferentTca, acceptedCopyOfSelection],
  );

  assert.strictEqual(selection.event, acceptedCopyOfSelection);
  assert.equal(selection.event.id, selected.id);
  assert.equal(selection.event.physics_result.tca.value, selected.physics_result.tca.value);
  assert.equal(selection.notice, null);
});

test("a missing exact encounter is cleared instead of substituted by a same-pair different-TCA event", () => {
  const selected = {
    id: "CA-selected-encounter",
    result_kind: "physics_assessment",
    primary: { id: "A" },
    secondary: { id: "B" },
    physics_result: { status: "valid", tca: { value: "2030-01-01T00:00:00Z" } },
  };
  const otherEncounter = {
    ...selected,
    id: "CA-other-encounter",
    physics_result: { status: "valid", tca: { value: "2030-01-02T00:00:00Z" } },
  };
  const selection = reconcilePhysicalEventSelection(
    { event: selected, context: selected, notice: null },
    [otherEncounter],
  );

  assert.equal(selection.event, null);
  assert.strictEqual(selection.context, selected);
  assert.match(selection.notice, /not present in the accepted screening result/);
});

test("missing, malformed, and duplicate physical event IDs fail closed", () => {
  const identitylessRow = { result_kind: "physics_assessment", physics_result: { status: "valid" } };
  for (const id of [undefined, "", "   ", 42, " CA-leading-space"]) {
    const candidate = { ...identitylessRow, id };
    const selection = resolvePhysicalEventSelection(candidate, [identitylessRow]);
    assert.equal(selection.event, null);
    assert.match(selection.notice, /missing or malformed event identity/);
  }

  const duplicateA = { id: "CA-duplicate", result_kind: "physics_assessment", physics_result: { status: "valid" } };
  const duplicateB = { ...duplicateA, attachedData: "conflicting duplicate" };
  const selection = resolvePhysicalEventSelection(duplicateA, [duplicateA, duplicateB]);
  assert.equal(selection.event, null);
  assert.match(selection.notice, /duplicated in the accepted screening result/);
  assert.equal(retainSelectedPhysicalEvent(duplicateA, [duplicateA, duplicateB]), null);
});

test("accepted job preserves exact event selection and blocks maneuver requests below the Pc floor", async () => {
  const jobAEvent = { ...capturedScreeningEvent, record_marker: "job-A" };
  const jobBExactEvent = { ...jobAEvent, record_marker: "job-B" };
  const prior = {
    conjunctions: [jobAEvent],
    conjunctionStatus: { job_id: "job-A", result_status: "valid_non_empty" },
    screeningAttempt: { run_id: "run-B", job_id: "job-B" },
  };
  const accepted = finishScreeningAttempt(prior, "run-B", {
    api_status: "available",
    job_id: "job-B",
    completion_status: "complete",
    result_status: "valid_non_empty",
    data: [jobBExactEvent],
  }, [jobBExactEvent]);
  const selection = reconcilePhysicalEventSelection(
    { event: jobAEvent, context: jobAEvent, notice: null },
    accepted.conjunctions,
  );
  assert.equal(accepted.conjunctionStatus.job_id, "job-B");
  assert.strictEqual(selection.event, jobBExactEvent);
  assert.equal(resolveManeuverEvent(selection.event, accepted.conjunctions), null);
  await assert.rejects(getManeuver(null, { screeningJobId: accepted.conjunctionStatus.job_id }), /selected Stage 2A event ID is required/);
});

test("mismatched or superseded screening results cannot replace accepted events or selection", () => {
  const existing = { id: "EV-current", result_kind: "physics_assessment" };
  const state = { conjunctions: [existing], conjunctionStatus: { job_id: "job-current" }, screeningAttempt: { run_id: "run-current", job_id: "job-current" } };
  const stale = { job_id: "job-old", completion_status: "complete", result_status: "valid_empty", data: [] };
  assert.equal(screeningResultMatchesRun({ runId: "run-current", jobId: "job-current" }, stale), false);
  const result = finishScreeningAttempt(state, "run-old", stale, []);
  assert.deepEqual(result.conjunctions, [existing]);
  assert.equal(result.conjunctionStatus.job_id, "job-current");
  assert.equal(reconcilePhysicalEventSelection({ event: existing, context: existing, notice: null }, result.conjunctions).event, existing);
});

test("a proxy with a matching pair resolves only to the physical event", () => {
  const physical = { id: "EV-physical", result_kind: "physics_assessment", primary: { id: 1 }, secondary: { id: 2 } };
  const proxy = { id: "SP-proxy", result_kind: "screening_proxy", primary: { id: "2" }, secondary: { id: "1" } };
  const selection = resolvePhysicalEventSelection(proxy, [physical]);
  assert.equal(selection.event, physical);
  assert.equal(selection.context, physical);
  assert.equal(selection.notice, null);
});

test("an unmatched proxy remains an explicit empty selection, never an unrelated physical event", () => {
  const unrelated = { id: "EV-other", result_kind: "physics_assessment", primary: { id: "3" }, secondary: { id: "4" } };
  const proxy = { id: "SP-proxy", result_kind: "screening_proxy", primary: { id: "1" }, secondary: { id: "2" } };
  const selection = resolvePhysicalEventSelection(proxy, [unrelated]);
  assert.equal(selection.event, null);
  assert.match(selection.notice, /no matching physical Stage 2A event/);
  assert.equal(resolveManeuverEvent(selection.event, [unrelated]), null);
  assert.equal(maneuverPageState(selection.event, [unrelated]).selected_event, null);
});

test("source labels distinguish live, stale live, fallback, unavailable, and loading", () => {
  assert.equal(sourceLabel("live"), "Live");
  assert.equal(sourceLabel("stale_live", 3660), "Catalog cached · updated 1h 1m ago");
  assert.equal(sourceLabel("fallback"), "BUNDLED FALLBACK DATA");
  assert.equal(sourceLabel("unavailable"), "SOURCE UNAVAILABLE");
  assert.equal(datasetLabel(true, "unavailable"), "Loading dataset");
  assert.equal(datasetLabel(false, "unavailable"), "Source unavailable");
});

test("unavailable catalog refresh preserves prior plotted objects and marks them stale", () => {
  const previous = { generated_at: "2026-10-10T00:00:00Z", objects: [{ id: "live-1" }], source_state: { status: "live", source: "CelesTrak" } };
  const failed = { objects: [], source_state: { status: "unavailable", last_error_code: "network_error" } };
  const accepted = retainCatalogSnapshot(previous, failed);
  assert.deepEqual(accepted.objects, previous.objects);
  assert.equal(accepted.generated_at, previous.generated_at);
  assert.equal(accepted.source_state.status, "stale");
  assert.equal(accepted.source_state.last_error_code, "network_error");
  assert.equal(sourceLabel(accepted.source_state.status), "Catalog cached");
  assert.equal(datasetLabel(false, accepted.source_state.status), "Dataset loaded");
  assert.deepEqual(retainCatalogSnapshot(null, failed), failed);
  const fallback = { objects: [{ id: "fallback-1" }], source_state: { status: "fallback", source: "Bundled fallback TLE sample" } };
  assert.equal(retainCatalogSnapshot(previous, fallback), fallback);
});
