import test from "node:test";
import assert from "node:assert/strict";
import { downloadReport, downloadTrajectoryAssessmentCsv, getManeuver, restoreArchivedScreeningJob, selectedEventReportPath, selectedManeuverReportPath } from "../src/api/ssaClient.js";
import { captureGlobeEventSelection, downloadGlobeEventReport, resolveGlobeEventSelection } from "../src/utils/globeEventReport.js";

test("Globe physical-event report stays bound to its originating screening job", () => {
  const calls = [];
  downloadGlobeEventReport(
    captureGlobeEventSelection({ id: "CA-globe-selected", result_kind: "physics_assessment" }, "0123456789abcdef0123456789abcdef"),
    (path, filename) => calls.push({ path, filename }),
  );
  assert.deepEqual(calls, [{
    path: "/api/conjunction-jobs/0123456789abcdef0123456789abcdef/events/CA-globe-selected/report.pdf",
    filename: "CA-globe-selected-report.pdf",
  }]);
});

test("Globe proxy report preserves its supported legacy report path", () => {
  const calls = [];
  downloadGlobeEventReport(
    captureGlobeEventSelection({ id: "SP-globe-proxy", result_kind: "screening_proxy" }, null),
    (path, filename) => calls.push({ path, filename }),
  );
  assert.deepEqual(calls, [{ path: "/api/reports/SP-globe-proxy.pdf", filename: "SP-globe-proxy-report.pdf" }]);
});

test("Globe physical report without job identity reports an error without legacy fallback", () => {
  const calls = [];
  const errors = [];
  const result = downloadGlobeEventReport(
    captureGlobeEventSelection({ id: "CA-no-job", result_kind: "physics_assessment" }, null),
    (path) => calls.push(path),
    (error) => errors.push(error.message),
  );
  assert.equal(result, null);
  assert.deepEqual(calls, []);
  assert.match(errors[0], /screening job identity is unavailable/);
  assert.doesNotMatch(errors[0], /api\/reports/);
});

test("Globe handoff keeps the captured physical event and originating job when a newer job reuses its ID", () => {
  const jobA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
  const eventFromJobA = { id: "CA-same-id", result_kind: "physics_assessment", attachedData: "from job A" };
  const eventFromJobB = { id: "CA-same-id", result_kind: "physics_assessment", attachedData: "from job B" };
  const newerAcceptedJobEvents = [eventFromJobB];
  const handoff = captureGlobeEventSelection(eventFromJobA, jobA);
  const resolved = resolveGlobeEventSelection(handoff);
  const calls = [];

  // The page's selection resolver consumes only the captured handoff, not the newer event list.
  assert.equal(newerAcceptedJobEvents[0].id, resolved.event.id);
  assert.strictEqual(resolved.event, eventFromJobA);
  assert.equal(resolved.event.attachedData, "from job A");
  assert.equal(resolved.screeningJobId, jobA);
  downloadGlobeEventReport(handoff, (path, filename) => calls.push({ path, filename }));
  assert.deepEqual(calls, [{
    path: `/api/conjunction-jobs/${jobA}/events/CA-same-id/report.pdf`,
    filename: "CA-same-id-report.pdf",
  }]);
});

test("invalid original Globe handoff cannot fall back to a newer job or event", () => {
  const eventFromJobB = { id: "CA-same-id", result_kind: "physics_assessment", attachedData: "from job B" };
  const calls = [];
  const errors = [];
  const missingJobHandoff = captureGlobeEventSelection(
    { id: "CA-same-id", result_kind: "physics_assessment", attachedData: "from job A" },
    null,
  );
  const result = downloadGlobeEventReport(missingJobHandoff, (path) => calls.push(path), (error) => errors.push(error.message));
  assert.equal(result, null);
  assert.deepEqual(calls, []);
  assert.match(errors[0], /screening job identity is unavailable/);
  assert.throws(() => resolveGlobeEventSelection(missingJobHandoff), /screening job identity is unavailable/);

  const malformedHandoff = { event: eventFromJobB, screeningJobId: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", resultKind: "screening_proxy" };
  assert.throws(() => resolveGlobeEventSelection(malformedHandoff), /unavailable or invalid/);
});

test("selected physical event report path is bound to its screening job", () => {
  assert.equal(
    selectedEventReportPath("0123456789abcdef0123456789abcdef", "CA-selected"),
    "/api/conjunction-jobs/0123456789abcdef0123456789abcdef/events/CA-selected/report.pdf",
  );
  assert.throws(() => selectedEventReportPath(null, "CA-selected"), /screening job ID and selected event ID/);
});

test("selected event and maneuver reports expose matching PDF, CSV, and JSON formats", () => {
  const jobId = "0123456789abcdef0123456789abcdef";
  assert.equal(selectedEventReportPath(jobId, "CA-selected", "csv"), `/api/conjunction-jobs/${jobId}/events/CA-selected/report.csv`);
  assert.equal(selectedEventReportPath(jobId, "CA-selected", "json"), `/api/conjunction-jobs/${jobId}/events/CA-selected/report.json`);
  assert.equal(selectedManeuverReportPath(jobId, "CA-selected", "pdf"), `/api/conjunction-jobs/${jobId}/events/CA-selected/assessment.pdf`);
  assert.equal(selectedManeuverReportPath(jobId, "CA-selected", "csv"), `/api/conjunction-jobs/${jobId}/events/CA-selected/assessment.csv`);
  assert.equal(selectedManeuverReportPath(jobId, "CA-selected", "json"), `/api/conjunction-jobs/${jobId}/events/CA-selected/assessment.json`);
});

test("downloadReport keeps the object URL alive until the browser has started the download", async () => {
  const originals = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document };
  const events = [];
  let delayedCleanup;
  const anchor = { click: () => events.push("clicked"), remove: () => events.push("removed"), set href(value) { this._href = value; }, set download(value) { this._download = value; } };
  globalThis.fetch = async (url) => {
    events.push(String(url));
    return new Response("%PDF-1.4 sample", { headers: { "content-type": "application/pdf" } });
  };
  globalThis.window = { URL: { createObjectURL: () => "blob:report", revokeObjectURL: () => events.push("revoked") }, setTimeout: (callback, delay) => { delayedCleanup = { callback, delay }; } };
  globalThis.document = { body: { appendChild: () => events.push("appended") }, createElement: () => anchor };
  try {
    await downloadReport("/api/reports/mission.pdf", "mission.pdf");
    assert.deepEqual(events.slice(-3), ["appended", "clicked", "removed"]);
    assert.equal(delayedCleanup.delay, 1_000);
    assert.equal(events.includes("revoked"), false);
    delayedCleanup.callback();
    assert.equal(events.at(-1), "revoked");
  } finally {
    globalThis.fetch = originals.fetch;
    globalThis.window = originals.window;
    globalThis.document = originals.document;
  }
});

test("downloadReport surfaces backend details instead of treating error JSON as a file", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Selected event was not found in this screening run." }), {
    status: 404,
    headers: { "content-type": "application/json" },
  });
  try {
    await assert.rejects(downloadReport("/api/reports/missing.pdf", "missing.pdf"), /Selected event was not found/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("downloadReport preserves structured event identity reason codes", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: { reason_code: "EVENT_NOT_FOUND", message: "The selected event is not part of this screening job." },
  }), { status: 404, headers: { "content-type": "application/json" } });
  try {
    await assert.rejects(
      downloadReport("/api/conjunction-jobs/job-A/events/event-B/report.pdf", "event-B.pdf"),
      /EVENT_NOT_FOUND: The selected event is not part of this screening job/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("trajectory assessment download requests the selected job and creates a correctly named CSV download", async () => {
  const originals = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document };
  const events = [];
  const anchor = { click: () => events.push("clicked"), remove: () => {}, set href(value) { this._href = value; }, set download(value) { this._download = value; } };
  globalThis.fetch = async (url) => {
    events.push(String(url));
    return new Response("event_id,event_identity_type\nCA-1,trajectory_event_deterministic", { headers: { "content-type": "text/csv; charset=utf-8" } });
  };
  globalThis.window = { URL: { createObjectURL: () => "blob:csv", revokeObjectURL: () => {} }, setTimeout: () => {} };
  globalThis.document = { body: { appendChild: () => {} }, createElement: () => anchor };
  try {
    const filename = await downloadTrajectoryAssessmentCsv("0123456789abcdef0123456789abcdef");
    assert.match(events[0], /conjunction-jobs\/0123456789abcdef0123456789abcdef\/reports\/conjunctions\.csv$/);
    assert.equal(events.at(-1), "clicked");
    assert.equal(filename, "trajectory-assessments-0123456789abcdef0123456789abcdef.csv");
    assert.equal(anchor._download, filename);
  } finally {
    globalThis.fetch = originals.fetch;
    globalThis.window = originals.window;
    globalThis.document = originals.document;
  }
});

test("trajectory assessment download explains a missing selected job without making a request", async () => {
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = async () => { called = true; throw new Error("unexpected request"); };
  try {
    await assert.rejects(downloadTrajectoryAssessmentCsv(null), /No completed screening job is selected/);
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("trajectory assessment download surfaces backend errors instead of creating a file", async () => {
  const originals = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document };
  let objectUrlCreated = false;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "The requested screening job is not available in memory or the export archive." }), {
    status: 404,
    headers: { "content-type": "application/json" },
  });
  globalThis.window = { URL: { createObjectURL: () => { objectUrlCreated = true; return "blob:csv"; }, revokeObjectURL: () => {} }, setTimeout: () => {} };
  globalThis.document = { body: { appendChild: () => {} }, createElement: () => ({ click() {}, remove() {} }) };
  try {
    await assert.rejects(downloadTrajectoryAssessmentCsv("0123456789abcdef0123456789abcdef"), /not available in memory or the export archive/);
    assert.equal(objectUrlCreated, false);
  } finally {
    globalThis.fetch = originals.fetch;
    globalThis.window = originals.window;
    globalThis.document = originals.document;
  }
});

test("archive restore uses its explicit route and does not create a screening job", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const job = {
    job_id: "0123456789abcdef0123456789abcdef", status: "partial", archived: true,
    result: { result_kind: "physics_assessment", data: [{ id: "CA-1" }] },
  };
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), method: options?.method });
    return new Response(JSON.stringify(job), { headers: { "content-type": "application/json" } });
  };
  try {
    const restored = await restoreArchivedScreeningJob(job.job_id);
    assert.equal(restored.job_id, job.job_id);
    assert.match(calls[0].url, /conjunction-jobs\/0123456789abcdef0123456789abcdef\/restore$/);
    assert.equal(calls[0].method, "POST");
    assert.doesNotMatch(calls[0].url, /conjunction-jobs\?/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("archive restore rejects malformed IDs locally and surfaces missing archives", async () => {
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return new Response(JSON.stringify({ detail: "No archived screening job exists for this ID." }), {
      status: 404, headers: { "content-type": "application/json" },
    });
  };
  try {
    await assert.rejects(restoreArchivedScreeningJob("../../outside"), /32-character hexadecimal/);
    assert.equal(called, false);
    await assert.rejects(restoreArchivedScreeningJob("0123456789abcdef0123456789abcdef"), /No archived screening job exists/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("getManeuver explains missing job context before making a request", async () => {
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = async () => { called = true; throw new Error("unexpected request"); };
  try {
    await assert.rejects(getManeuver({ id: "EV-1", result_kind: "physics_assessment" }), /completed screening job ID is unavailable/);
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
