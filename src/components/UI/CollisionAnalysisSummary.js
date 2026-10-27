import React from "react";
import { searchAndSortCollisionEvents } from "../../utils/collisionEventDisplay.js";
import { hasValidEventFosterPc } from "../../utils/collisionPcPresentation.js";
import { researchPcCatalogSummary } from "../../utils/researchPcAnalytics.js";

function highestPriorityEvent(events) {
  return searchAndSortCollisionEvents(events.filter((event) => event?.physics_result?.status === "valid"
    && event?.physics_result?.tca_status === "valid"
    && Number.isFinite(event?.automatic_research_pc_assessment?.log10_pc)), "", "research_pc")[0] || null;
}

export function CollisionAnalysisSummary({ events = [], displayedEvents = [], screeningStatus = {} }) {
  const screened = Array.isArray(events) ? events : [];
  const displayed = Array.isArray(displayedEvents) ? displayedEvents : [];
  const total = Number.isInteger(screeningStatus?.assessment_record_count)
    ? screeningStatus.assessment_record_count
    : Number.isInteger(screeningStatus?.total_records_available)
      ? screeningStatus.total_records_available
      : screened.length;
  const fosterCount = displayed.filter((event) => event?.physics_result?.status === "valid" && hasValidEventFosterPc(event)).length;
  const validCount = displayed.filter((event) => event?.physics_result?.status === "valid").length;
  const validEvents = screened.filter((event) => event?.physics_result?.status === "valid");
  const highestResearchLogPc = validEvents.map((event) => event?.automatic_research_pc_assessment?.log10_pc).filter(Number.isFinite).sort((a, b) => b - a)[0];
  const highestPcText = Number.isFinite(highestResearchLogPc)
    ? highestResearchLogPc < -300 ? "< 1e-300" : (10 ** highestResearchLogPc).toExponential(2)
    : "not computed in this screening";
  const geometryReviewCount = displayed.filter((event) => event?.review_priority?.status === "classified").length;
  const aiOutputs = displayed.filter((event) => event?.collision_ai_assessment?.status === "available");
  const highest = highestPriorityEvent(displayed);
  const researchSummary = researchPcCatalogSummary(screened);
  const pair = highest
    ? `${highest.primary?.name || highest.primary?.id || "Unknown"} (${highest.primary?.id || "ID unavailable"}) vs ${highest.secondary?.name || highest.secondary?.id || "Unknown"} (${highest.secondary?.id || "ID unavailable"})`
    : "None";
  const diagnosticCounts = React.createElement("div", { className: "collision-analysis-summary-counts" },
    [
      ["Total screened conjunctions", String(total)],
      ["Events currently displayed", `${displayed.length} of ${total}`],
      ["Valid physical conjunctions", `${validCount} of ${displayed.length}`],
      ["Geometry-review evidence available", `${geometryReviewCount} of ${displayed.length}`],
      ["Valid events with research Pc", `${researchSummary.withResearchPc} of ${researchSummary.valid}`],
      ["Valid events with reason code", `${researchSummary.withReasonCode} of ${researchSummary.valid}`],
      ["Valid events without Pc or reason", String(researchSummary.withoutPcOrReason)],
      ["Boundary TCA (not ranked)", String(researchSummary.boundary)],
      ["Event-specific Foster Pc", `${fosterCount} of ${displayed.length}`],
      ["Events with separate AI model outputs", `${aiOutputs.length} of ${displayed.length}`],
    ].map(([label, value]) => React.createElement("span", { key: label }, label, React.createElement("strong", null, value))));
  const histogram = React.createElement("div", { className: "research-pc-histogram", role: "img", "aria-label": "Histogram of exact research log10 Pc values" },
    researchSummary.histogram.map((bin) => React.createElement("span", { key: bin.label, title: `${bin.label}: ${bin.count}`, className: "research-pc-histogram-bin" },
      React.createElement("i", { style: { height: `${Math.max(3, bin.count / Math.max(1, researchSummary.valid) * 100)}%` } }),
      React.createElement("small", null, bin.label), React.createElement("b", null, bin.count))));

  return React.createElement("section", { className: "collision-analysis-summary", "aria-label": "Collision Analysis summary" },
    researchSummary.classCounts.High === 0 && screened.length > 0 ? React.createElement("p", { className: "muted" }, `No High-probability events in this screening (highest Pc ${highestPcText})`) : null,
    (() => {
      const thresholds = validEvents.map((event) => event?.automatic_research_pc_assessment?.risk_assessment?.thresholds).find((value) => Number.isFinite(value?.medium_pc_inclusive) && Number.isFinite(value?.high_pc_inclusive));
      const medium = thresholds?.medium_pc_inclusive ?? 1e-7;
      const high = thresholds?.high_pc_inclusive ?? 1e-4;
      return React.createElement("p", { className: "muted" }, `Research Pc classes: Low < ${medium.toExponential()}, Medium ${medium.toExponential()} to < ${high.toExponential()}, High ≥ ${high.toExponential()}.`);
    })(),
    React.createElement("div", { className: "collision-analysis-highest-priority" },
      React.createElement("span", null, "Highest exact research-Pc event in current screening"),
      React.createElement("strong", null, highest ? `${pair}${Number.isFinite(highest.automatic_research_pc_assessment?.log10_pc) ? ` | log10 Pc ${highest.automatic_research_pc_assessment.log10_pc}` : ""}` : "No valid interior-TCA research Pc is available."),
      React.createElement("p", null, "Ranking basis: exact unfloored log10 Pc, descending; miss/sigma is the tie-breaker. Boundary solutions are shown separately and excluded."),
      React.createElement("p", { className: "muted" }, "Counts use the full current screening result. The research Pc is assumption-based and is never presented as or used to fill operational Foster Pc.")),
    React.createElement("details", { className: "og-acc screening-details" },
      React.createElement("summary", null, "Screening details"), diagnosticCounts, histogram),
    React.createElement("section", { className: "research-pc-catalog-summary", "aria-label": "Research Pc class summary and encounter groups" },
      React.createElement("div", { className: "research-pc-class-counts", "aria-label": "Research Pc class counts by encounter group" }, Object.entries(researchSummary.classCounts).map(([name, count]) => {
        const rawCount = researchSummary.classRawEventCounts[name] || 0;
        return React.createElement("span", { key: name }, `${name}: ${count} ${count === 1 ? "encounter" : "encounters"} (${rawCount} raw ${rawCount === 1 ? "event" : "events"})`);
      })),
      researchSummary.encounterGroups.length ? React.createElement("details", { className: "encounter-group-summary" }, React.createElement("summary", null, `Likely co-located encounter groups (${researchSummary.encounterGroups.length}); raw event records retained`), React.createElement("ul", null, researchSummary.encounterGroups.map((group) => React.createElement("li", { key: group.representativeEventId }, `${group.representativeEventId}: 1 encounter (${group.memberEventIds.length} raw events); +${group.coLocatedObjectCount} co-located objects`)))) : null));
}
