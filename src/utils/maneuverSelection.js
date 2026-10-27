export function eligibleManeuverEvents(events) {
  return selectableManeuverEvents(events).filter((event) => event.physics_result?.status === "valid");
}

export function selectableManeuverEvents(events) {
  if (!Array.isArray(events)) return [];
  const physical = events.filter((event) => event?.result_kind === "physics_assessment");
  const counts = new Map();
  for (const event of physical) {
    if (validEventIdentity(event.id)) counts.set(event.id, (counts.get(event.id) || 0) + 1);
  }
  return physical.filter((event) => validEventIdentity(event.id) && counts.get(event.id) === 1);
}

function validEventIdentity(id) {
  return typeof id === "string"
    && id.length > 0
    && id.trim() === id
    && !/[\u0000-\u001f\u007f]/.test(id);
}

export function selectManeuverEvent(events, eventId) {
  return selectableManeuverEvents(events).find((event) => event.id === eventId) || null;
}

export function resolveManeuverEvent(selectedEvent, events) {
  const selectable = selectableManeuverEvents(events);
  if (selectedEvent) {
    const matched = selectable.find((item) => item.id === selectedEvent.id) || null;
    if (!matched) return null;
    if (matched?.physics_result?.status === "invalid") return matched;
    if (matched && Number.isFinite(matched.automatic_research_pc_assessment?.log10_pc)
      && matched.automatic_research_pc_assessment.log10_pc >= -30) return matched;
  }
  return defaultManeuverEvent(selectable);
}

export function defaultManeuverEvent(events) {
  const eligible = eligibleManeuverEvents(events).filter((event) => (
    Number.isFinite(event.automatic_research_pc_assessment?.log10_pc)
    && event.automatic_research_pc_assessment.log10_pc >= -30
  ));
  return eligible.slice().sort((left, right) => {
    const leftLog = left.automatic_research_pc_assessment?.log10_pc;
    const rightLog = right.automatic_research_pc_assessment?.log10_pc;
    const leftValid = Number.isFinite(leftLog);
    const rightValid = Number.isFinite(rightLog);
    if (leftValid && rightValid && leftLog !== rightLog) return rightLog - leftLog;
    if (leftValid !== rightValid) return leftValid ? -1 : 1;
    const leftMiss = left.physics_result?.miss_distance?.value;
    const rightMiss = right.physics_result?.miss_distance?.value;
    if (Number.isFinite(leftMiss) && Number.isFinite(rightMiss) && leftMiss !== rightMiss) return leftMiss - rightMiss;
    return String(left.id).localeCompare(String(right.id));
  })[0] || null;
}

export function maneuverAssessmentForSelection(assessment, screeningJobId, event) {
  if (event?.result_kind !== "physics_assessment" || !event?.id) return null;
  if (assessment?.screening_job_id !== screeningJobId || assessment?.event_id !== event.id) return null;
  return assessment.result || null;
}

export function isCurrentManeuverRequest(requestGeneration, currentGeneration, signalAborted = false) {
  return !signalAborted && requestGeneration === currentGeneration;
}

export function maneuverPageState(event, events, screeningStatus = {}) {
  const eligible = eligibleManeuverEvents(events);
  const selectable = selectableManeuverEvents(events);
  const selected = event?.result_kind === "physics_assessment"
    && selectable.some((item) => item.id === event.id)
    && (event.physics_result?.status === "invalid" || (
      Number.isFinite(event.automatic_research_pc_assessment?.log10_pc)
      && event.automatic_research_pc_assessment.log10_pc >= -30
    ))
    ? selectable.find((item) => item.id === event.id) : null;
  const invalid = selected?.physics_result?.status === "invalid";
  return {
    status: selected ? (invalid ? "selected_invalid_event" : "selected_event_unavailable_dynamics") : "no_eligible_event",
    selected_event: selected,
    eligible_events: eligible,
    selectable_events: selectable,
    invalid_reason_codes: invalid ? (selected.physics_result?.reason_codes || []) : [],
    empty_title: screeningStatus?.result_status === "valid_empty"
      ? "No qualifying physical conjunction available"
      : "No valid physical event selected",
    empty_text: screeningStatus?.result_status === "valid_empty"
      ? "The accepted Stage 2A run completed with zero qualifying close approaches. Event-specific maneuver assessment requires a valid physical trajectory event; heuristic proxy pairs cannot be used."
      : selectable.length
        ? "The valid event with the highest exact log10 research Pc is selected by default. Choose another physical event if needed; invalid events remain available for review but cannot produce maneuver candidates."
        : "No trajectory-derived physical event is available. Heuristic proxy pairs cannot be used as maneuver inputs.",
  };
}
