import React from "react";
import { collisionEventPriority, rankCollisionEvents } from "../../utils/collisionEventDisplay.js";
import { hasValidEventFosterPc } from "../../utils/collisionPcPresentation.js";

function highestPriorityEvent(events) {
  const ranked = events
    .filter((event) => event?.physics_result?.status === "valid"
      && Number.isInteger(event?.ai_risk_assessment?.final_priority_rank) && event.ai_risk_assessment.final_priority_rank > 0)
    .slice()
    .sort((left, right) => left.ai_risk_assessment.final_priority_rank - right.ai_risk_assessment.final_priority_rank || String(left.id).localeCompare(String(right.id)));
  if (ranked.length) return ranked[0];
  return rankCollisionEvents(events.filter((event) => event?.physics_result?.status === "valid"))[0] || null;
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
  const criticalHighCount = displayed.filter((event) => ["CRITICAL", "HIGH"].includes(event?.review_priority?.category)).length;
  const researchCount = displayed.filter((event) => event?.physics_result?.status === "valid" && event?.automatic_research_pc_assessment?.status === "prior_based_research_estimate").length;
  const aiEvents = displayed.filter((event) => event?.physics_result?.status !== "invalid"
    && Number.isFinite(event?.ai_risk_assessment?.score)
    && Number.isInteger(event?.ai_risk_assessment?.final_priority_rank)
    && event.ai_risk_assessment.final_priority_rank > 0);
  const highest = highestPriorityEvent(displayed);
  const ai = highest?.ai_risk_assessment;
  const priorityReason = !highest
    ? "No valid event priority is available in the current display."
    : ai?.ranking_explanation || ai?.explanation || `${collisionEventPriority(highest).label}: ${collisionEventPriority(highest).basis}`;
  const pair = highest
    ? `${highest.primary?.name || highest.primary?.id || "Unknown"} (${highest.primary?.id || "ID unavailable"}) vs ${highest.secondary?.name || highest.secondary?.id || "Unknown"} (${highest.secondary?.id || "ID unavailable"})`
    : "None";

  return React.createElement("section", { className: "collision-analysis-summary", "aria-label": "Collision Analysis summary" },
    React.createElement("div", { className: "collision-analysis-summary-counts" },
      [
        ["Total screened conjunctions", String(total)],
        ["Events currently displayed", `${displayed.length} of ${total}`],
        ["Valid physical conjunctions", `${validCount} of ${displayed.length}`],
        ["Critical / High geometry priority", `${criticalHighCount} of ${displayed.length}`],
        ["Numerical research Pc", `${researchCount} of ${displayed.length}`],
        ["Event-specific Foster Pc", `${fosterCount} of ${displayed.length}`],
        ["AI-prioritized events", `${aiEvents.length} of ${displayed.length}`],
      ].map(([label, value]) => React.createElement("span", { key: label }, label, React.createElement("strong", null, value)))),
    React.createElement("div", { className: "collision-analysis-highest-priority" },
      React.createElement("span", null, "Highest-priority event in current display"),
      React.createElement("strong", null, highest ? `${pair}${Number.isInteger(ai?.final_priority_rank) ? ` | final rank #${ai.final_priority_rank}` : ""}` : pair),
      React.createElement("p", null, `Ranking basis: ${priorityReason}`),
      React.createElement("p", { className: "muted" }, "Counts for valid events, Pc and AI use the currently displayed set. The research Pc is assumption-based and is never presented as or used to fill operational Foster Pc.")));
}
