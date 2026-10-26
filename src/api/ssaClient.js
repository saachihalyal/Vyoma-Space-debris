export const API_BASE = import.meta.env?.VITE_API_BASE || "http://127.0.0.1:8001";
export const REPORT_BASE = API_BASE;

function responseErrorMessage(payload, fallback) {
  const detail = payload?.detail;
  if (detail && typeof detail === "object") {
    return [detail.reason_code, detail.message].filter(Boolean).join(": ") || fallback;
  }
  return detail || payload?.message || fallback;
}

const catalogRequests = new Map();
const conjunctionRequests = new Map();
const maneuverRequests = new Map();
const SCREENING_POLL_TIMEOUT_MS = 55 * 60 * 1000;
const SCREENING_POLL_INTERVAL_MS = 1000;
const SCREENING_STATUS_REQUEST_TIMEOUT_MS = 30 * 1000;
const API_REQUEST_TIMEOUT_MS = 12 * 1000;

async function fetchWithTimeoutRetry(url, options = {}, { timeoutMs = API_REQUEST_TIMEOUT_MS, retries = 1 } = {}) {
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    if (options.signal?.aborted) throw new DOMException("Request aborted", "AbortError");
    const controller = new AbortController();
    const abortFromCaller = () => controller.abort();
    options.signal?.addEventListener("abort", abortFromCaller, { once: true });
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      if (response.status >= 500) {
        await response.body?.cancel();
        if (attempt < retries) continue;
        throw new Error(`Backend busy: server returned HTTP ${response.status}.`);
      }
      return response;
    } catch (error) {
      if (options.signal?.aborted) throw new DOMException("Request aborted", "AbortError");
      if (attempt >= retries) throw new Error("Backend busy: request timed out or could not connect.");
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", abortFromCaller);
    }
  }
  throw new Error("Backend busy: request failed.");
}

export function getCatalog({ limit = 900, signal } = {}) {
  if (signal?.aborted) return Promise.reject(new DOMException("Request aborted", "AbortError"));
  const key = String(limit);
  let pending = catalogRequests.get(key);
  if (!pending) {
    const controller = new AbortController();
    pending = { controller, subscribers: 0, settled: false, abortTimer: null };
    pending.promise = fetchCatalog(limit, controller.signal);
    catalogRequests.set(key, pending);
    pending.promise.finally(() => {
      pending.settled = true;
      if (catalogRequests.get(key) === pending) catalogRequests.delete(key);
    }).catch(() => {});
  }
  if (pending.abortTimer) {
    clearTimeout(pending.abortTimer);
    pending.abortTimer = null;
  }
  return awaitWithAbort(pending, signal);
}

async function fetchCatalog(limit, signal) {
  try {
    const params = new URLSearchParams({ limit: String(limit), forecast_hours: "0" });
    const response = await fetchWithTimeoutRetry(`${API_BASE}/api/catalog?${params}`, { signal });
    if (!response.ok) {
      throw new Error(`SSA API returned ${response.status}`);
    }
    const payload = await response.json();
    return normalizeSnapshot(payload);
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    return unavailableSnapshot(error?.message || "Catalog API unavailable");
  }
}

function awaitWithAbort(request, signal) {
  const release = () => {
    request.subscribers = Math.max(0, request.subscribers - 1);
    if (!request.subscribers && !request.settled) {
      request.abortTimer = setTimeout(() => {
        if (!request.subscribers && !request.settled) request.controller.abort();
      }, 0);
    }
  };
  if (!signal) {
    request.subscribers += 1;
    return request.promise.finally(release);
  }
  if (signal.aborted) return Promise.reject(new DOMException("Request aborted", "AbortError"));
  request.subscribers += 1;
  return new Promise((resolve, reject) => {
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      signal.removeEventListener("abort", abort);
      release();
    };
    const abort = () => {
      finish();
      reject(new DOMException("Request aborted", "AbortError"));
    };
    signal.addEventListener("abort", abort, { once: true });
    request.promise.then(
      (value) => { finish(); resolve(value); },
      (error) => { finish(); reject(error); },
    );
  });
}

export async function getForecast({ horizonHours = 168, steps = 9, signal } = {}) {
  try {
    const params = new URLSearchParams({
      horizon_hours: String(horizonHours),
      steps: String(steps),
    });
    const response = await fetchWithTimeoutRetry(`${API_BASE}/api/forecast?${params}`, { signal });
    if (!response.ok) {
      throw new Error(`SSA API returned ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    if (error.name === "AbortError") {
      throw error;
    }
    return {
      generated_at: new Date().toISOString(),
      horizon_hours: horizonHours,
      frames: [],
      source_summary: { status: "unavailable", counts_by_source_type: {}, object_count: 0 },
      source_state: { status: "unavailable", source: "Source unavailable" },
      error: error?.message || "Forecast API unavailable",
    };
  }
}

export async function getSystemHealth({ signal } = {}) {
  return getStructured("/api/system-health", { signal }, { data: fallbackHealth() });
}

export async function getAnalytics({ signal } = {}) {
  return getStructured("/api/analytics", { signal }, { data: null });
}

export function getConjunctions({ limit = 100, horizonHours = 24, sampleStepSeconds = 60, screeningThresholdKm = 25, startUtc, catalogIdentity = "unspecified", signal, onStatus, pollTimeoutMs = SCREENING_POLL_TIMEOUT_MS, pollIntervalMs = SCREENING_POLL_INTERVAL_MS, requestTimeoutMs = SCREENING_STATUS_REQUEST_TIMEOUT_MS, diagnosticInvocationId = null } = {}) {
  const key = JSON.stringify({ limit, horizonHours, sampleStepSeconds, screeningThresholdKm, startUtc, catalogIdentity, pollTimeoutMs, pollIntervalMs, requestTimeoutMs });
  let request = conjunctionRequests.get(key);
  if (!request) {
    const params = new URLSearchParams({ limit: String(limit), horizon_hours: String(horizonHours), sample_step_seconds: String(sampleStepSeconds), screening_threshold_km: String(screeningThresholdKm) });
    if (startUtc) params.set("start_utc", startUtc);
    request = fetchConjunctions(params, onStatus, { pollTimeoutMs, pollIntervalMs, requestTimeoutMs, diagnosticInvocationId });
    conjunctionRequests.set(key, request);
    request.finally(() => { if (conjunctionRequests.get(key) === request) conjunctionRequests.delete(key); }).catch(() => {});
  } else {
    console.info("[ORION screening diagnostic] reusing in-flight screening client request", { invocationId: diagnosticInvocationId });
  }
  if (!signal) return request;
  if (signal.aborted) return Promise.reject(new DOMException("Request aborted", "AbortError"));
  return new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = () => signal.removeEventListener("abort", abort);
    const abort = () => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new DOMException("UI subscription detached", "AbortError"));
    };
    signal.addEventListener("abort", abort, { once: true });
    request.then((value) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(value);
    }, (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    });
  });
}

export function resumeConjunctionJob(jobId, { onStatus, pollTimeoutMs = SCREENING_POLL_TIMEOUT_MS, pollIntervalMs = SCREENING_POLL_INTERVAL_MS, requestTimeoutMs = SCREENING_STATUS_REQUEST_TIMEOUT_MS } = {}) {
  if (!jobId) return Promise.resolve({ api_status: "error", result_status: "unavailable", completion_status: "failed", reason: "The saved screening job ID is unavailable.", data: [] });
  return pollExistingConjunctionJob(jobId, onStatus, { pollTimeoutMs, pollIntervalMs, requestTimeoutMs });
}

async function fetchConjunctions(params, onStatus, { pollTimeoutMs, pollIntervalMs, requestTimeoutMs, diagnosticInvocationId }) {
  const deadline = Date.now() + Math.max(1, pollTimeoutMs);
  let jobId = null;
  try {
    console.info("[ORION screening diagnostic] POST starting", { invocationId: diagnosticInvocationId, endpoint: `${API_BASE}/api/conjunction-jobs` });
    const acceptedResponse = await fetchScreeningRequest(`${API_BASE}/api/conjunction-jobs?${params}`, { method: "POST" }, deadline);
    console.info("[ORION screening diagnostic] POST response", { invocationId: diagnosticInvocationId, status: acceptedResponse.status, ok: acceptedResponse.ok });
    if (!acceptedResponse.ok) throw new Error(`SSA API returned ${acceptedResponse.status} starting the screening job`);
    const accepted = await acceptedResponse.json();
    if (!accepted?.job_id) throw new Error("The screening job response did not contain a job ID.");
    jobId = accepted.job_id;
    console.info("[ORION screening diagnostic] job accepted", { invocationId: diagnosticInvocationId, jobId, status: accepted.status || "queued" });
    onStatus?.({ ...accepted, api_status: "available", result_status: accepted.status || "queued" });
    return await pollExistingConjunctionJob(accepted.job_id, onStatus, { pollTimeoutMs, pollIntervalMs, requestTimeoutMs, deadline, diagnosticInvocationId });
  } catch (error) {
    console.warn("[ORION screening diagnostic] POST/poll path failed", { invocationId: diagnosticInvocationId, jobId, errorName: error?.name || "Error", message: error?.message || "Screening request failed." });
    if (error?.name === "AbortError") throw error;
    if (error instanceof ScreeningPollTimeout) {
      const timeout = { api_status: "error", result_status: "timeout", completion_status: "failed", job_id: jobId, reason: "Screening status polling timed out. The backend job may still be running; this timeout did not cancel it." };
      onStatus?.({ ...timeout, status: "timed_out" });
      return { ...timeout, data: [], physics_assessment_status: "unavailable" };
    }
    return {
      api_status: "error",
      result_status: "unavailable",
      completion_status: "failed",
      job_id: jobId,
      result_kind: "physics_assessment",
      physics_assessment_status: "unavailable",
      data: [],
      reason: error?.message || "The screening API request failed.",
    };
  }
}

async function pollExistingConjunctionJob(jobId, onStatus, { pollTimeoutMs, pollIntervalMs, requestTimeoutMs = SCREENING_STATUS_REQUEST_TIMEOUT_MS, deadline = Date.now() + Math.max(1, pollTimeoutMs), diagnosticInvocationId = "resume" } = {}) {
  try {
    while (true) {
      const remaining = deadline - Date.now();
      if (remaining <= 0) throw new ScreeningPollTimeout();
      await new Promise((resolve) => setTimeout(resolve, Math.min(pollIntervalMs, remaining)));
      if (Date.now() >= deadline) throw new ScreeningPollTimeout();
      let response;
      try {
        response = await fetchScreeningRequest(`${API_BASE}/api/conjunction-jobs/${encodeURIComponent(jobId)}`, {}, deadline, requestTimeoutMs);
      } catch (error) {
        if (!(error instanceof ScreeningStatusRequestTimeout)) throw error;
        // Retrying a read is safe and keeps the same backend job and result identity.
        // The overall polling deadline remains the upper bound for this recovery.
        onStatus?.({
          job_id: jobId,
          api_status: "available",
          status: "running",
          result_status: "running",
          progress: {
            stage: "status_retry",
            percent: null,
            message: "The screening status read timed out; the same job is still being checked.",
          },
        });
        continue;
      }
      console.info("[ORION screening diagnostic] poll response", { invocationId: diagnosticInvocationId, jobId, status: response.status, ok: response.ok });
      if (response.status === 404) {
        const unavailable = {
          api_status: "error", result_status: "unavailable", completion_status: "failed", job_id: jobId,
          result_kind: "physics_assessment", physics_assessment_status: "unavailable", data: [],
          reason: "This screening job is no longer available; rerun screening.",
        };
        onStatus?.({ ...unavailable, status: "unavailable" });
        return unavailable;
      }
      if (!response.ok) throw new Error(`SSA API returned ${response.status} reading the screening job`);
      const state = await response.json();
      if (state?.job_id !== jobId) {
        const mismatch = {
          api_status: "error", result_status: "unavailable", completion_status: "failed",
          job_id: jobId, reason_code: "JOB_ID_MISMATCH", data: [],
          reason: "Screening status response job ID does not match the accepted job.",
        };
        onStatus?.({ ...mismatch, status: "unavailable" });
        return mismatch;
      }
      onStatus?.({ ...state, api_status: "available", result_status: state.status });
      if (!["complete", "partial", "failed", "cancelled"].includes(state.status)) continue;
      if (state.status === "cancelled") return {
        api_status: "cancelled", result_status: "cancelled", completion_status: "cancelled",
        job_id: state.job_id, reason: state.reason || state.message || "The screening job was cancelled by the backend.", data: [],
      };
      if (!state.result || !Array.isArray(state.result.data)) {
        return {
          api_status: "error", result_status: "error", completion_status: "failed",
          result_kind: "physics_assessment", physics_assessment_status: "unavailable", data: [],
          job_id: state.job_id,
          reason: "The completed screening job did not contain a valid result list.",
        };
      }
      // The job status endpoint carries a bounded first page. Hydrate the
      // complete stable result set before handing it to event filters/reports.
      const pagination = state.result.assessment_pagination;
      if (pagination?.has_more) {
        const allRecords = [...state.result.data];
        let page = pagination.next_page;
        while (page != null) {
          const pageResponse = await fetchScreeningRequest(
            `${API_BASE}/api/conjunction-jobs/${encodeURIComponent(jobId)}/assessments?page=${page}&page_size=${pagination.page_size}`,
            {}, deadline, requestTimeoutMs,
          );
          if (!pageResponse.ok) throw new Error(`SSA API returned ${pageResponse.status} retrieving assessment page ${page}`);
          const pagePayload = await pageResponse.json();
          if (pagePayload.job_id !== jobId || pagePayload.page !== page || !Array.isArray(pagePayload.data)) {
            throw new Error("Assessment page identity or contents do not match the selected screening job.");
          }
          allRecords.push(...pagePayload.data);
          page = pagePayload.next_page;
        }
        const expectedCount = pagination.total_records;
        const ids = new Set(allRecords.map((record) => record?.id));
        if (allRecords.length !== expectedCount || ids.size !== expectedCount || allRecords.some((record) => !record?.id)) {
          throw new Error("Assessment pages contained missing or duplicate event records.");
        }
        state.result = { ...state.result, data: allRecords, assessment_pagination: { ...pagination, returned_records: allRecords.length, has_more: false, next_page: null, loaded_all: true } };
      }
      return {
        ...state.result,
        api_status: state.status === "failed" ? "error" : "available",
        result_status: state.result.result_status || (state.result.data.length ? "valid_non_empty" : "valid_empty"),
        completion_status: state.status,
        job_id: state.job_id,
      };
    }
  } catch (error) {
    if (error instanceof ScreeningPollTimeout) {
      const timeout = { api_status: "error", result_status: "timeout", completion_status: "failed", job_id: jobId, reason: "Screening status polling timed out. The backend job may still be running; this timeout did not cancel it." };
      onStatus?.({ ...timeout, status: "timed_out" });
      return { ...timeout, data: [], physics_assessment_status: "unavailable" };
    }
    return {
      api_status: "error", result_status: "unavailable", completion_status: "failed", job_id: jobId,
      result_kind: "physics_assessment", physics_assessment_status: "unavailable", data: [],
      reason: error?.message || "Screening status request failed.",
    };
  }
}

class ScreeningPollTimeout extends Error {}
class ScreeningStatusRequestTimeout extends Error {}

async function fetchScreeningRequest(url, options, deadline, requestTimeoutMs = SCREENING_STATUS_REQUEST_TIMEOUT_MS) {
  const remaining = deadline - Date.now();
  if (remaining <= 0) throw new ScreeningPollTimeout();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.min(requestTimeoutMs, remaining));
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) {
      if (Date.now() >= deadline) throw new ScreeningPollTimeout();
      throw new ScreeningStatusRequestTimeout("Screening status request timed out.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export async function getScreeningProxies({ limit = 100, signal } = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  return getStructured(`/api/screening-proxies?${params}`, { signal }, {
    result_status: "unavailable",
    result_kind: "screening_proxy",
    data: [],
  });
}

export async function getSmartFilter({ signal } = {}) {
  return getStructured("/api/smart-filter", { signal }, { data: null });
}

export async function getPhysicalSmartFilter(screeningJobId, { signal } = {}) {
  if (typeof screeningJobId !== "string" || !/^[a-fA-F0-9]{32}$/.test(screeningJobId.trim())) {
    return { status: "unavailable", reason_code: "COMPLETED_SCREENING_JOB_REQUIRED", decisions: [], evaluation: null };
  }
  const response = await fetchWithTimeoutRetry(`${API_BASE}/api/conjunction-jobs/${encodeURIComponent(screeningJobId.trim())}/smart-filter`, { signal });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(responseErrorMessage(payload, `Smart Filter evaluation returned HTTP ${response.status}`));
  if (payload?.result_type !== "physics_smart_filter" || !Array.isArray(payload?.decisions) || !payload?.evaluation) {
    throw new Error("Smart Filter returned an incompatible physical-event result.");
  }
  return payload;
}

export function physicalSmartFilterCsvPath(screeningJobId) {
  if (typeof screeningJobId !== "string" || !/^[a-fA-F0-9]{32}$/.test(screeningJobId.trim())) {
    throw new Error("A completed screening job ID is required to export Smart Filter decisions.");
  }
  return `/api/conjunction-jobs/${encodeURIComponent(screeningJobId.trim())}/smart-filter.csv`;
}

export async function getManeuver(event, { signal, screeningJobId, leadSeconds = 300, burnMagnitudes = [0.01, 0.05], maxDeltaVMs = null, rtnDirection = "all", initialMassKg = null, specificImpulseS = null, covarianceScale = 1 } = {}) {
  if (!event?.id) throw new Error("A selected Stage 2A event ID is required for maneuver assessment.");
  if (event.result_kind !== "physics_assessment") throw new Error("Maneuver assessment requires a trajectory-derived physics event.");
  if (!screeningJobId) throw new Error("The completed screening job ID is unavailable; refresh Collision Analysis and select its event again.");
  if (event.screening_job_id && event.screening_job_id !== screeningJobId) {
    throw new Error("The selected event belongs to a different screening job; select the event from the current Collision Analysis job.");
  }
  const query = new URLSearchParams({ screening_job_id: screeningJobId, lead_seconds: String(leadSeconds), burn_magnitudes_m_s: burnMagnitudes.join(","), rtn_direction: rtnDirection, covariance_scale: String(covarianceScale) });
  if (maxDeltaVMs != null) query.set("max_delta_v_m_s", String(maxDeltaVMs));
  if (initialMassKg != null || specificImpulseS != null) {
    if (initialMassKg == null || specificImpulseS == null) throw new Error("Initial mass and specific impulse must both be supplied for a fuel estimate.");
    query.set("initial_mass_kg", String(initialMassKg));
    query.set("specific_impulse_s", String(specificImpulseS));
  }
  const path = `/api/conjunctions/${encodeURIComponent(event.id)}/maneuver?${query}`;
  const key = JSON.stringify({ path, event });
  let request = maneuverRequests.get(key);
  if (!request) {
    request = fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
    }).then(async (response) => {
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = payload?.detail;
        const reasonCode = typeof detail === "object" ? detail?.reason_code : null;
        const error = new Error(responseErrorMessage(payload, `Maneuver API returned ${response.status}`));
        error.reasonCode = reasonCode || null;
        error.status = response.status;
        throw error;
      }
      if (typeof payload?.screening_job_id !== "string" || !payload.screening_job_id.trim()) {
        throw new Error("Maneuver API response is missing its screening job ID; this backend cannot confirm the selected event's job provenance.");
      }
      if (payload.screening_job_id !== screeningJobId) {
        throw new Error("Maneuver response screening job ID does not match the selected event's screening job.");
      }
      if (payload?.data?.event_id !== event.id) {
        throw new Error("Maneuver response event ID does not match the selected physical event.");
      }
      return payload.data;
    });
    maneuverRequests.set(key, request);
    request.finally(() => { if (maneuverRequests.get(key) === request) maneuverRequests.delete(key); }).catch(() => {});
  }
  if (!signal) return request;
  if (signal.aborted) throw new DOMException("Request aborted", "AbortError");
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException("Request aborted", "AbortError"));
    signal.addEventListener("abort", abort, { once: true });
    request.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}

export async function uploadManeuverEvent(file, { leadSeconds = 300, burnMagnitudeMs = 0.01, rtnDirection = "all", initialMassKg = null, specificImpulseS = null } = {}) {
  if (!file || !/\.(json|csv)$/i.test(file.name || "")) throw new Error("Choose a JSON or CSV maneuver event file.");
  if ((initialMassKg == null) !== (specificImpulseS == null)) throw new Error("Initial mass and specific impulse must both be supplied, or both left blank.");
  const type = /\.csv$/i.test(file.name) ? "text/csv" : "application/json";
  const query = new URLSearchParams({ lead_seconds: String(leadSeconds), burn_magnitude_m_s: String(burnMagnitudeMs), rtn_direction: rtnDirection });
  if (initialMassKg != null) { query.set("initial_mass_kg", String(initialMassKg)); query.set("specific_impulse_s", String(specificImpulseS)); }
  const response = await fetch(`${API_BASE}/api/maneuver/user-upload?${query}`, {
    method: "POST", headers: { "Content-Type": type }, body: file,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    const error = new Error(responseErrorMessage(payload, `Maneuver upload returned HTTP ${response.status}`));
    error.reasonCode = typeof detail === "object" ? detail?.reason_code : null;
    throw error;
  }
  if (!payload?.data?.event_id || !payload?.screening_job_id) throw new Error("Maneuver upload response is missing its event or job identity.");
  return payload;
}

export async function importEventCdm({ screeningJobId, eventId, cdmXml, sourceLabel, assumeIndependentCovariances }) {
  return postEventInput(
    `/api/conjunction-jobs/${encodeURIComponent(screeningJobId)}/events/${encodeURIComponent(eventId)}/cdm`,
    { cdm_xml: cdmXml, source_label: sourceLabel, assume_independent_covariances: assumeIndependentCovariances },
  );
}

export async function calculateReferenceCdmPc({ cdmText, sourceLabel, assumeIndependentCovariances }) {
  return postEventInput("/api/collision-probability/cdm", {
    cdm_xml: cdmText,
    source_label: sourceLabel,
    assume_independent_covariances: assumeIndependentCovariances,
  });
}

export async function calculateNasaCaraReferenceCase() {
  const response = await fetch(`${API_BASE}/api/collision-probability/reference-cases/nasa-cara-foster-2d`, { method: "POST" });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(responseErrorMessage(payload, `NASA CARA reference assessment returned HTTP ${response.status}`));
  return payload;
}

export async function calculateReferenceManeuver({ eventId, maneuveringObjectId, burnLeadSeconds, direction, deltaVMs }) {
  const response = await postEventInput("/api/collision-probability/reference-cases/nasa-cara-foster-2d/maneuver", {
    event_id: eventId,
    maneuvering_object_id: maneuveringObjectId,
    burn_lead_seconds: Number(burnLeadSeconds),
    direction,
    delta_v_m_s: Number(deltaVMs),
  });
  if (response?.data?.event_id !== eventId || response?.result_kind !== "standalone_reference_cdm_maneuver_assessment") {
    throw new Error("Reference maneuver response does not match the selected standalone CDM event.");
  }
  return response;
}

export function referenceManeuverReportPath({ eventId, maneuveringObjectId, burnLeadSeconds, direction, deltaVMs }) {
  const params = new URLSearchParams({
    event_id: eventId,
    maneuvering_object_id: maneuveringObjectId,
    burn_lead_seconds: String(burnLeadSeconds),
    direction,
    delta_v_m_s: String(deltaVMs),
  });
  return `/api/collision-probability/reference-cases/nasa-cara-foster-2d/maneuver-report.pdf?${params}`;
}

export async function calculateScenarioPc({ screeningJobId, eventId, covariancePrimaryKm2, covarianceSecondaryKm2, hbrKm, assumeIndependentCovariances, assumptions }) {
  return postEventInput(
    `/api/conjunction-jobs/${encodeURIComponent(screeningJobId)}/events/${encodeURIComponent(eventId)}/scenario-pc`,
    {
      covariance_primary_km2: covariancePrimaryKm2,
      covariance_secondary_km2: covarianceSecondaryKm2,
      hbr_km: hbrKm,
      assume_independent_covariances: assumeIndependentCovariances,
      assumptions,
    },
  );
}

export async function calculateResearchPcWhatIf({ screeningJobId, eventId, covarianceScale }) {
  return postEventInput(
    `/api/conjunction-jobs/${encodeURIComponent(screeningJobId)}/events/${encodeURIComponent(eventId)}/research-pc-scenario`,
    { covariance_policy: "tle_age_baseline", covariance_scale },
  );
}

async function postEventInput(path, body) {
  if (!path.includes("/undefined/") && !path.includes("/null/")) {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(responseErrorMessage(payload, `Collision probability input returned HTTP ${response.status}`));
    return payload;
  }
  throw new Error("A completed screening job ID and event ID are required.");
}

export function reportUrl(path) {
  return `${API_BASE}${path}`;
}

export function completedScreeningCsvPath(screeningJobId) {
  if (typeof screeningJobId !== "string" || !screeningJobId.trim()) {
    throw new Error("No completed screening job is selected. Wait for a completed run before downloading its assessments.");
  }
  return `/api/conjunction-jobs/${encodeURIComponent(screeningJobId)}/reports/conjunctions.csv`;
}

export function selectedEventReportPath(screeningJobId, eventId, format = "pdf") {
  if (typeof screeningJobId !== "string" || !screeningJobId.trim() || typeof eventId !== "string" || !eventId.trim()) {
    throw new Error("A completed screening job ID and selected event ID are required for the event report.");
  }
  if (!["pdf", "csv", "json"].includes(format)) throw new Error("Selected event reports support PDF, CSV, or JSON.");
  return `/api/conjunction-jobs/${encodeURIComponent(screeningJobId.trim())}/events/${encodeURIComponent(eventId.trim())}/report.${format}`;
}

export function selectedManeuverReportPath(screeningJobId, eventId, format = "pdf") {
  if (typeof screeningJobId !== "string" || !screeningJobId.trim() || typeof eventId !== "string" || !eventId.trim()) throw new Error("A screening job ID and event ID are required for the maneuver report.");
  if (!["pdf", "csv", "json"].includes(format)) throw new Error("Maneuver reports support PDF, CSV, or JSON.");
  const endpoint = format === "pdf" ? "assessment.pdf" : `assessment.${format}`;
  return `/api/conjunction-jobs/${encodeURIComponent(screeningJobId.trim())}/events/${encodeURIComponent(eventId.trim())}/${endpoint}`;
}

export async function downloadTrajectoryAssessmentCsv(screeningJobId) {
  const path = completedScreeningCsvPath(screeningJobId);
  const filename = `trajectory-assessments-${screeningJobId}.csv`;
  await downloadReport(path, filename);
  return filename;
}

export async function restoreArchivedScreeningJob(screeningJobId) {
  if (typeof screeningJobId !== "string" || !/^[a-fA-F0-9]{32}$/.test(screeningJobId.trim())) {
    throw new Error("Enter a 32-character hexadecimal screening job ID to restore an archive.");
  }
  const response = await fetchWithTimeoutRetry(`${API_BASE}/api/conjunction-jobs/${encodeURIComponent(screeningJobId.trim())}/restore`, { method: "POST" });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(payload?.detail || `Archive restore failed with HTTP ${response.status}`);
  if (payload?.job_id !== screeningJobId.trim() || !payload?.archived || !Array.isArray(payload?.result?.data)) {
    throw new Error("The backend returned an invalid archived screening job.");
  }
  return payload;
}

export async function downloadReport(path, filename) {
  const response = await fetch(reportUrl(path));
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(responseErrorMessage(payload, `Download failed with HTTP ${response.status}`));
  }
  const blob = await response.blob();
  if (!blob.size) throw new Error("Download failed: the report is empty");
  const mime = (response.headers.get("content-type") || "").toLowerCase();
  const head = await blob.slice(0, 16).text();
  if (filename.toLowerCase().endsWith(".pdf") && (!mime.includes("application/pdf") || !head.startsWith("%PDF-"))) {
    throw new Error("Download failed: response is not a valid PDF");
  }
  if (filename.toLowerCase().endsWith(".csv") && (!mime.includes("text/csv") || !head.includes("event_id,"))) {
    throw new Error("Download failed: response is not a valid CSV export");
  }
  if (filename.toLowerCase().endsWith(".json")) {
    if (!mime.includes("application/json")) throw new Error("Download failed: response is not JSON");
    try { JSON.parse(await blob.text()); } catch { throw new Error("Download failed: JSON payload is invalid"); }
  }
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } catch (error) {
    window.URL.revokeObjectURL(url);
    anchor.remove();
    throw error;
  }
  anchor.remove();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1_000);
}

async function getStructured(path, { signal } = {}, fallback) {
  try {
    const response = await fetchWithTimeoutRetry(`${API_BASE}${path}`, { signal });
    if (!response.ok) {
      throw new Error(`SSA API returned ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    if (error.name === "AbortError") {
      throw error;
    }
    return { ...fallback, backend_busy: String(error?.message || "").toLowerCase().includes("backend busy") };
  }
}

function normalizeSnapshot(payload) {
  return {
    ...payload,
    source_state: payload.source_state || { status: "unavailable", source: "Source unavailable" },
    objects: payload.objects || [],
    risk_cells: payload.risk_cells || payload.riskCells || [],
    unavailable_objects: payload.unavailable_objects || [],
    source_summary: payload.source_summary || {
      status: "unavailable",
      counts_by_source_type: {},
      object_count: (payload.objects || []).length,
      unavailable_count: (payload.unavailable_objects || []).length,
    },
    stats: {
      tracked_objects: 0,
      active_satellites: 0,
      debris_objects: 0,
      leo: 0,
      meo: 0,
      geo: 0,
      global_heuristic_risk_score: null,
      heuristic_forecast_trend_score: null,
      data_latency_seconds: 0,
      unavailable_objects: 0,
      ...(payload.stats || {}),
    },
  };
}

function unavailableSnapshot(reason) {
  return {
    generated_at: new Date().toISOString(),
    source: "Source unavailable",
    source_state: { status: "unavailable", source: "Source unavailable", last_error_code: reason },
    source_summary: { status: "unavailable", counts_by_source_type: {}, object_count: 0, unavailable_count: 0 },
    stats: {
      tracked_objects: 0, active_satellites: 0, debris_objects: 0,
      leo: 0, meo: 0, geo: 0, data_latency_seconds: 0, unavailable_objects: 0,
    },
    objects: [],
    unavailable_objects: [],
    risk_cells: [],
  };
}

function fallbackHealth() {
  return {
    backend: "offline fallback",
    dataset_loaded: true,
    dataset_source: "Synthetic demo fallback",
    dataset_status: "synthetic_demo",
    source_state: { status: "unavailable", source: "Source unavailable" },
    objects_tracked: 0,
    conjunctions: 0,
    high_priority_events: 0,
    ai_status: "unavailable",
    ai_reason: "no_trained_model_configured",
    gpu_status: "not_used",
    physics_conjunction_assessment: "unavailable",
    version: "offline",
  };
}
