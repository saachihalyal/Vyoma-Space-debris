import { selectedEventReportPath } from "../api/ssaClient.js";

export function captureGlobeEventSelection(event, screeningJobId) {
  if (!event?.id) {
    return { event: null, screeningJobId: null, resultKind: null, error: "The selected Globe event identity is unavailable." };
  }
  if (event.result_kind === "physics_assessment") {
    if (!screeningJobId) {
      return {
        event,
        screeningJobId: null,
        resultKind: event.result_kind,
        error: "The selected physical event's screening job identity is unavailable. Return to Collision Analysis and select the event again.",
      };
    }
    return { event, screeningJobId, resultKind: event.result_kind, error: null };
  }
  if (event.result_kind === "screening_proxy") {
    return { event, screeningJobId: null, resultKind: event.result_kind, error: null };
  }
  return { event, screeningJobId: null, resultKind: event.result_kind || null, error: "The selected Globe event type is unavailable or unsupported." };
}

// The same captured handoff is used to choose the displayed event and its report route.
export function resolveGlobeEventSelection(selection) {
  if (!selection || selection.error || !selection.event?.id || selection.event.result_kind !== selection.resultKind) {
    throw new Error(selection?.error || "The original Globe event selection is unavailable or invalid.");
  }
  if (!new Set(["physics_assessment", "screening_proxy"]).has(selection.resultKind)) {
    throw new Error("The original Globe event type is unavailable or unsupported.");
  }
  if (selection.resultKind === "physics_assessment" && !selection.screeningJobId) {
    throw new Error("The selected physical event's screening job identity is unavailable. Return to Collision Analysis and select the event again.");
  }
  if (selection.resultKind === "screening_proxy" && selection.screeningJobId != null) {
    throw new Error("The proxy event handoff contains an invalid physical screening job identity.");
  }
  return {
    event: selection.event,
    screeningJobId: selection.screeningJobId,
    reportPath: globeEventReportPath(selection.event, selection.screeningJobId),
  };
}

export function globeEventReportPath(event, screeningJobId) {
  if (!event?.id) throw new Error("The selected Globe event identity is unavailable.");
  if (event.result_kind === "physics_assessment") {
    if (!screeningJobId) {
      throw new Error("The selected physical event's screening job identity is unavailable. Return to Collision Analysis and select the event again.");
    }
    return selectedEventReportPath(screeningJobId, event.id);
  }
  return `/api/reports/${encodeURIComponent(event.id)}.pdf`;
}

export function downloadGlobeEventReport(selection, download, onError = () => {}) {
  try {
    const resolved = resolveGlobeEventSelection(selection);
    return download(resolved.reportPath, `${resolved.event.id}-report.pdf`);
  } catch (error) {
    onError(error);
    return null;
  }
}
