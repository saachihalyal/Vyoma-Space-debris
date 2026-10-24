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
  if (selectedEvent) return selectable.find((item) => item.id === selectedEvent.id) || null;
  return null;
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
  const selected = event?.result_kind === "physics_assessment" && selectable.some((item) => item.id === event.id) ? selectable.find((item) => item.id === event.id) : null;
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
        ? "The earliest valid event from the accepted run is selected automatically. You can choose another physical event; invalid events remain available for review but cannot produce maneuver candidates."
        : "No trajectory-derived physical event is available. Heuristic proxy pairs cannot be used as maneuver inputs.",
  };
}
