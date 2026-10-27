import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { API_BASE, resumeConjunctionJob } from "../src/api/ssaClient.js";
import capturedRealScreeningEvent from "./fixtures/capturedRealScreeningEvent.json" with { type: "json" };
import { clearActiveScreeningJobId, readActiveScreeningJobId, saveActiveScreeningJobId } from "../src/utils/screeningJobStorage.js";
import { shouldStartScreeningRun, finishScreeningAttempt } from "../src/utils/screeningRefreshPolicy.js";

const event = { id: "CA-resumed", result_kind: "physics_assessment", primary: { id: "1" }, secondary: { id: "2" } };

test("reload resumes polling the same running job until its result completes", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  let polls = 0;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || "GET" });
    polls += 1;
    return polls === 1
      ? new Response(JSON.stringify({ job_id: "resume-running", status: "running", progress: { stage: "trajectory_screening" } }), { status: 200 })
      : new Response(JSON.stringify({ job_id: "resume-running", status: "complete", result: { data: [event], result_status: "valid_non_empty" } }), { status: 200 });
  };
  try {
    const statuses = [];
    const result = await resumeConjunctionJob("resume-running", { pollIntervalMs: 1, onStatus: (status) => statuses.push(status.status) });
    assert.equal(result.job_id, "resume-running");
    assert.equal(result.completion_status, "complete");
    assert.deepEqual(result.data, [event]);
    assert.deepEqual(statuses, ["running", "complete"]);
    assert.equal(calls.length, 2);
    assert.ok(calls.every((call) => call.method === "GET" && call.url === `${API_BASE}/api/conjunction-jobs/resume-running`));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("latest accepted job lookup propagates caller abort through its timeout controller", async () => {
  const { getLatestConjunctionJob } = await import("../src/api/ssaClient.js");
  const originalFetch = globalThis.fetch;
  const controller = new AbortController();
  let requestSignal;
  globalThis.fetch = async (url, options = {}) => {
    assert.equal(String(url), `${API_BASE}/api/conjunction-jobs/latest`);
    requestSignal = options.signal;
    return new Promise((resolve, reject) => options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }));
  };
  try {
    const pending = getLatestConjunctionJob({ signal: controller.signal });
    await new Promise((resolve) => setImmediate(resolve));
    assert.ok(requestSignal instanceof AbortSignal);
    assert.notEqual(requestSignal, controller.signal);
    controller.abort();
    await assert.rejects(pending, { name: "AbortError" });
    assert.equal(requestSignal.aborted, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("resumed API response preserves the captured numerical research Pc for rendering", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    assert.equal(String(url), `${API_BASE}/api/conjunction-jobs/research-pc-capture`);
    return new Response(JSON.stringify({
      job_id: "research-pc-capture", status: "complete",
      result: { data: [capturedRealScreeningEvent], result_status: "valid_non_empty" },
    }), { status: 200 });
  };
  try {
    const result = await resumeConjunctionJob("research-pc-capture", { pollIntervalMs: 1 });
    assert.equal(result.data[0].id, "CA-CDBC9233F65C7BE0EE0A");
    assert.equal(result.data[0].automatic_research_pc_assessment.estimated_pc_scientific, "1.55992e-167");
    assert.equal(result.data[0].automatic_research_pc_assessment.percentage_scientific, "1.55992e-165");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("reload restores terminal COMPLETE and PARTIAL results without changing their status", async (t) => {
  const originalFetch = globalThis.fetch;
  for (const completion of ["complete", "partial"]) {
    await t.test(completion, async () => {
      globalThis.fetch = async (url, options = {}) => {
        assert.equal(options.method || "GET", "GET");
        assert.equal(String(url), `${API_BASE}/api/conjunction-jobs/job-${completion}`);
        return new Response(JSON.stringify({
          job_id: `job-${completion}`, status: completion,
          result: { data: [event], result_status: completion === "partial" ? "partial" : "valid_non_empty", completion_status: completion },
        }), { status: 200 });
      };
      const result = await resumeConjunctionJob(`job-${completion}`, { pollIntervalMs: 1 });
      assert.equal(result.completion_status, completion);
      assert.equal(result.result_status, completion === "partial" ? "partial" : "valid_non_empty");
      assert.deepEqual(result.data, [event]);
    });
  }
  globalThis.fetch = originalFetch;
});

test("terminal job hydration requests every assessment page and rejects omissions", async () => {
  const originalFetch = globalThis.fetch;
  const rows = Array.from({ length: 245 }, (_, index) => ({
    id: `EV-${String(index).padStart(3, "0")}`,
    physics_result: { status: index % 10 === 0 ? "invalid" : "valid", reason_codes: index % 10 === 0 ? ["PAIR_DIAGNOSTIC"] : [] },
  }));
  const calls = [];
  globalThis.fetch = async (url) => {
    const value = String(url);
    calls.push(value);
    if (value.endsWith("/assessments?page=2&page_size=120")) return new Response(JSON.stringify({ job_id: "paged-job", page: 2, data: rows.slice(120, 240), next_page: 3 }), { status: 200 });
    if (value.endsWith("/assessments?page=3&page_size=120")) return new Response(JSON.stringify({ job_id: "paged-job", page: 3, data: rows.slice(240), next_page: null }), { status: 200 });
    return new Response(JSON.stringify({ job_id: "paged-job", status: "complete", result: {
      data: rows.slice(0, 120), assessment_pagination: { page: 1, page_size: 120, total_records: 245, has_more: true, next_page: 2 },
    } }), { status: 200 });
  };
  try {
    const result = await resumeConjunctionJob("paged-job", { pollIntervalMs: 1 });
    assert.equal(result.data.length, 245);
    assert.deepEqual(result.data.map((row) => row.id), rows.map((row) => row.id));
    assert.deepEqual(result.data[10].physics_result.reason_codes, ["PAIR_DIAGNOSTIC"]);
    assert.equal(result.assessment_pagination.loaded_all, true);
    assert.equal(calls.length, 3);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("a lost in-memory job reports rerun guidance and recovery never POSTs a replacement", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || "GET" });
    return new Response(JSON.stringify({ detail: "Screening job not found in this backend process." }), { status: 404 });
  };
  try {
    const result = await resumeConjunctionJob("lost-job", { pollIntervalMs: 1 });
    assert.equal(result.job_id, "lost-job");
    assert.equal(result.completion_status, "failed");
    assert.match(result.reason, /job is no longer available; rerun screening/i);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].method, "GET");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("page initialization remains passive and stale resumed results cannot replace a newer attempt", () => {
  const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(appSource, /resumeConjunctionJob\(savedJobId/);
  assert.match(appSource, /load\(\{ explicitScreeningRefresh: false \}\)/);
  assert.equal(shouldStartScreeningRun({ explicitRefresh: false }), false);

  const currentEvent = { id: "CA-current", result_kind: "physics_assessment" };
  const state = {
    conjunctions: [currentEvent], conjunctionStatus: { job_id: "new-job" },
    screeningAttempt: { run_id: "new-run", job_id: "new-job", result_status: "running" },
  };
  const stale = finishScreeningAttempt(state, "resume-old-run", {
    job_id: "old-job", completion_status: "complete", result_status: "valid_empty", data: [],
  }, []);
  assert.deepEqual(stale.conjunctions, [currentEvent]);
  assert.equal(stale.conjunctionStatus.job_id, "new-job");
  assert.equal(stale.screeningAttempt.run_id, "new-run");
});

test("saved job state clears only when the expected job still owns the slot", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  assert.equal(saveActiveScreeningJobId("job-old", storage), true);
  assert.equal(readActiveScreeningJobId(storage), "job-old");
  assert.equal(clearActiveScreeningJobId("job-new", storage), false);
  assert.equal(readActiveScreeningJobId(storage), "job-old");
  assert.equal(saveActiveScreeningJobId("job-new", storage), true);
  assert.equal(clearActiveScreeningJobId("job-old", storage), false);
  assert.equal(readActiveScreeningJobId(storage), "job-new");
  assert.equal(clearActiveScreeningJobId("job-new", storage), true);
  assert.equal(readActiveScreeningJobId(storage), null);
});
