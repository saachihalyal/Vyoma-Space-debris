let explicitRefreshSequence = 0;

export function shouldStartScreeningRun({ explicitRefresh = false, runActive = false } = {}) {
  return explicitRefresh && !runActive;
}

export function createExplicitRefreshHandler(startExplicitRefresh) {
  return () => {
    const invocationId = `refresh-${Date.now()}-${++explicitRefreshSequence}`;
    console.info("[ORION screening diagnostic] TopBar refresh click", { invocationId });
    if (typeof startExplicitRefresh !== "function") {
      console.warn("[ORION screening diagnostic] Refresh callback is unavailable.", { invocationId });
      return undefined;
    }
    return startExplicitRefresh(invocationId);
  };
}

export function beginScreeningAttempt(previous, attempt) {
  return { ...previous, screeningAttempt: attempt };
}

export function screeningStatusForEmptyResults(acceptedStatus, latestAttempt) {
  if (acceptedStatus?.result_status !== "not_started" || acceptedStatus?.job_id || !latestAttempt?.run_id) {
    return acceptedStatus || {};
  }
  return { ...acceptedStatus, ...latestAttempt };
}

export function screeningSummaryDisplay(acceptedStatus, latestAttempt) {
  const useLatestAttempt = acceptedStatus?.result_status === "not_started"
    && !acceptedStatus?.job_id
    && Boolean(latestAttempt?.run_id);
  const status = useLatestAttempt ? { ...acceptedStatus, ...latestAttempt } : acceptedStatus || {};
  return {
    label: useLatestAttempt ? "Latest screening attempt" : acceptedStatus?.job_id ? "Last accepted result" : "Screening state",
    text: `${status.result_status || "unavailable"} · ${status.completion_status || "not completed"} · job ${status.job_id || "unavailable"}`,
  };
}

export function collisionScreeningState(acceptedStatus = {}, latestAttempt = null) {
  const attempt = latestAttempt || {};
  if (["queued", "pending", "starting"].includes(attempt.result_status)) return "starting";
  if (attempt.result_status === "running") return "running";
  if (attempt.completion_status === "failed" || attempt.result_status === "failed") return "failed";
  if (["complete", "partial"].includes(acceptedStatus.completion_status)
      && acceptedStatus.job_id
      && ["valid_empty", "valid_non_empty", "partial"].includes(acceptedStatus.result_status)) return "completed";
  if (attempt.run_id && ["complete", "partial"].includes(attempt.completion_status)) return "completed";
  return "ready";
}

export function updateScreeningAttempt(previous, runId, update) {
  if (previous.screeningAttempt?.run_id !== runId) return previous;
  return { ...previous, screeningAttempt: { ...previous.screeningAttempt, ...update } };
}

export function retainSelectedPhysicalEvent(selectedEvent, events) {
  if (selectedEvent?.result_kind !== "physics_assessment") return null;
  return uniquePhysicalEventById(selectedEvent.id, events).event;
}

export function screeningResultMatchesRun(run, payload) {
  return Boolean(run?.runId && run?.jobId && payload?.job_id === run.jobId
    && ["complete", "partial"].includes(payload?.completion_status)
    && ["valid_empty", "valid_non_empty", "partial"].includes(payload?.result_status)
    && Array.isArray(payload?.data) && payload?.api_status !== "error");
}

function validEventIdentity(id) {
  return typeof id === "string"
    && id.length > 0
    && id.trim() === id
    && !/[\u0000-\u001f\u007f]/.test(id);
}

function uniquePhysicalEventById(id, events) {
  if (!validEventIdentity(id) || !Array.isArray(events)) {
    return { event: null, reason: "invalid_identity" };
  }
  const matches = events.filter((event) => event?.result_kind === "physics_assessment" && event.id === id);
  if (matches.length === 1) return { event: matches[0], reason: null };
  return { event: null, reason: matches.length > 1 ? "ambiguous_identity" : "not_found" };
}

function physicalMatchFor(candidate, events) {
  if (!candidate || !Array.isArray(events)) return { event: null, reason: "not_found" };
  if (candidate.result_kind === "physics_assessment") {
    return uniquePhysicalEventById(candidate.id, events);
  }
  const primaryId = candidate.primary?.id;
  const secondaryId = candidate.secondary?.id;
  if (primaryId == null || secondaryId == null) return { event: null, reason: "not_found" };
  const requestedPair = [String(primaryId), String(secondaryId)].sort().join("|");
  return {
    event: events.find((event) => event?.result_kind === "physics_assessment"
      && [String(event.primary?.id), String(event.secondary?.id)].sort().join("|") === requestedPair) || null,
    reason: "not_found",
  };
}

export function resolvePhysicalEventSelection(candidate, events) {
  const { event, reason } = physicalMatchFor(candidate, events);
  if (event) return { event, context: event, notice: null };
  if (!candidate) return { event: null, context: null, notice: null };
  const proxy = candidate.result_kind !== "physics_assessment";
  return {
    event: null,
    context: candidate,
    notice: proxy
      ? `Heuristic proxy ${candidate.id || "selection"} has no matching physical Stage 2A event. It cannot be used for collision or maneuver assessment.`
      : reason === "invalid_identity"
        ? "The selected physical event has a missing or malformed event identity and cannot be matched safely. Select a valid current physical event to continue."
        : reason === "ambiguous_identity"
          ? `The selected physical event identity ${candidate.id} is duplicated in the accepted screening result. Select an unambiguous event to continue.`
          : `The selected physical event ${candidate.id || ""} is not present in the accepted screening result. Select a current physical event to continue.`,
  };
}

export function reconcilePhysicalEventSelection(selection, events) {
  const candidate = selection?.context || selection?.event || null;
  if (!candidate) {
    const firstValid = (Array.isArray(events) ? events : [])
      .filter((event) => event?.result_kind === "physics_assessment"
        && event?.physics_result?.status === "valid"
        && uniquePhysicalEventById(event.id, events).event === event)
      .slice()
      .sort((left, right) => {
        const leftTca = Date.parse(left.physics_result?.tca?.value || "") || Number.POSITIVE_INFINITY;
        const rightTca = Date.parse(right.physics_result?.tca?.value || "") || Number.POSITIVE_INFINITY;
        return leftTca - rightTca || String(left.id).localeCompare(String(right.id));
      })[0] || null;
    return firstValid
      ? { event: firstValid, context: firstValid, notice: null }
      : { event: null, context: null, notice: null };
  }
  return resolvePhysicalEventSelection(candidate, events);
}

export function finishScreeningAttempt(previous, runId, payload, physicalEvents) {
  if (previous.screeningAttempt?.run_id !== runId) return previous;

  const completion = payload?.completion_status;
  const resultStatus = payload?.result_status;
  const expectedJobId = previous.screeningAttempt.job_id;
  const jobMatches = Boolean(expectedJobId && payload?.job_id && expectedJobId === payload.job_id);
  const accepted = ["complete", "partial"].includes(completion)
    && ["valid_empty", "valid_non_empty", "partial"].includes(resultStatus)
    && Array.isArray(payload?.data)
    && payload?.api_status !== "error"
    && jobMatches;
  const mismatchedTerminal = Boolean(completion && ["complete", "partial"].includes(completion) && !jobMatches);
  const attempt = {
    ...previous.screeningAttempt,
    api_status: mismatchedTerminal ? "error" : payload?.api_status || (accepted ? "available" : "error"),
    result_status: mismatchedTerminal ? "unavailable" : resultStatus || (completion === "cancelled" ? "cancelled" : "unavailable"),
    completion_status: mismatchedTerminal ? "failed" : completion || "failed",
    job_id: jobMatches ? payload?.job_id : previous.screeningAttempt.job_id || null,
    reason: payload?.reason || payload?.message || (mismatchedTerminal ? "Completed result did not match the active screening job ID." : null),
    progress: payload?.progress || null,
  };

  if (!accepted) return { ...previous, screeningAttempt: attempt };

  const validCount = (events) => (Array.isArray(events) ? events : []).filter((event) =>
    event?.result_kind === "physics_assessment"
      && event?.physics_result?.status === "valid"
      && event?.physics_result?.tca_status === "valid").length;
  if (validCount(previous.conjunctions) > validCount(physicalEvents)) {
    return { ...previous, screeningAttempt: attempt };
  }

  return {
    ...previous,
    conjunctions: physicalEvents,
    conjunctionStatus: {
      api_status: payload.api_status,
      result_status: resultStatus,
      completion_status: completion,
      job_id: payload.job_id || previous.screeningAttempt.job_id || null,
      reason: payload.reason || payload.message || null,
      physics_assessment_status: payload.physics_assessment_status || "unavailable",
      ml_status: payload.ml_status || "unavailable",
      ml_model: payload.ml_model || null,
      screening: payload.screening || null,
      source_summary: payload.source_summary || null,
      run_date: payload.run_date || payload.finished_at || payload.created_at || null,
      performance: payload.performance || null,
      structurally_invalid_excluded_count: payload.structurally_invalid_excluded_count ?? 0,
    },
    screeningAttempt: attempt,
  };
}
