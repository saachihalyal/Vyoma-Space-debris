import React from "react";
import { collisionEventPriority, explainPhysicsReason, searchAndSortCollisionEvents } from "../../utils/collisionEventDisplay.js";
import { groupCoLocatedEvents } from "../../utils/researchPcAnalytics.js";
import { formatProbabilityPercentage, formatProbabilityScientific, isValidProbability } from "./CollisionPcSummary.js";
import { hasValidEventFosterPc, operationalFosterStatus, researchPcPresentation } from "../../utils/collisionPcPresentation.js";

function value(field, unit = "") {
  if (field?.status === "available" && field.value != null && Number.isFinite(Number(field.value))) {
    return `${field.value}${unit}`;
  }
  return "No value in event data";
}

function probability(pc) {
  return `${formatProbabilityScientific(pc)} Pc (${formatProbabilityPercentage(pc)})`;
}

function eventPair(event) {
  const object = (item) => `${item?.name || item?.canonicalName || "Unknown object"} (${item?.id || "ID not recorded"}; ${item?.object_type || "type not recorded"}${item?.classification_source === "group_based_fallback" ? ", group-based fallback" : ""})`;
  return `${object(event.primary)} vs ${object(event.secondary)}`;
}

function matchedSourcePc(event) {
  const result = event.collision_probability || {};
  const pc = event.source_reported_pc ?? result.source_reported_pc;
  const eventId = event.source_reported_event_id ?? result.source_reported_event_id;
  return eventId === event.id && isValidProbability(pc) ? pc : null;
}

function primaryPc(event, fosterAvailable, sourcePc, research) {
  if (fosterAvailable) return { label: "Event-specific Foster Pc", value: probability(event.collision_probability.pc) };
  if (sourcePc !== null) return { label: "Source-reported Pc", value: probability(sourcePc) };
  if (research?.status === "prior_based_research_estimate") {
    const formatted = researchPcPresentation(research);
    return { label: "Research estimate — assumption-based", value: `${formatted.value} Pc (${formatted.percentage})` };
  }
  return { label: "Collision probability", value: "No compatible probability inputs in this event" };
}

function ProbabilityChannel({ label, value: channelValue, method }) {
  return React.createElement("div", { className: "conjunction-pc-channel" },
    React.createElement("span", null, label),
    React.createElement("strong", null, channelValue),
    method ? React.createElement("small", null, method) : null);
}

function EventCard({ event, rank, onSelect, onShowInGlobe, onAssessManeuver, screeningJobId }) {
  const physics = event.physics_result || {};
  const fosterAvailable = hasValidEventFosterPc(event);
  const foster = event.collision_probability || {};
  const research = event.automatic_research_pc_assessment;
  const researchDisplay = researchPcPresentation(research);
  const sourcePc = matchedSourcePc(event);
  const preferred = primaryPc(event, fosterAvailable, sourcePc, research);
  const ai = event.ai_risk_assessment;
  const collisionAi = event.collision_ai_assessment;
  const pcSurrogate = collisionAi?.pc_surrogate;
  const riskSurrogate = collisionAi?.risk_classifier;
  const physicsClass = research?.risk_assessment?.final_risk_class || event.collision_probability?.probability_classification?.category || "Class not assigned";
  const aiClass = riskSurrogate?.ai_risk_class;
  const classComparison = !aiClass ? "AI class not returned" : !["Low", "Medium", "High"].includes(physicsClass) ? `AI class ${aiClass}; physics class not assigned` : `AI class ${aiClass} (${aiClass === physicsClass ? "agrees" : "differs"})`;
  const valid = physics.status === "valid";
  const queueScore = Number.isFinite(ai?.score) ? `${(ai.score * 100).toFixed(1)} / 100` : "No score returned";
  const deterministicGeometryIndex = !ai?.prediction_method || ai.prediction_method === "deterministic_geometry_speed_fallback";
  // This record is a deterministic geometry queue; its category is never a
  // Pc-derived risk class. Trained classes are shown from collisionAi below.
  const category = null;
  const provenance = physics.provenance || event.provenance || {};
  const sourceProvenance = foster.source_reported_pc_provenance || event.source_reported_pc_provenance || {};
  const tca = physics.tca?.value || "No TCA in event data";
  const miss = value(physics.miss_distance, " km");
  const speed = value(physics.relative_speed_at_tca, " km/s");
  const rankLabel = !valid
    ? `Not ranked (${physics.status || "assessment status not returned"})`
    : Number.isFinite(research?.log10_pc)
      ? rank ? `#${rank}` : "Unranked"
      : "Unranked (no Pc value in event data)";
  const card = React.createElement("article", { className: `conjunction-card ${valid ? "is-valid" : "is-review"}`, key: event.id },
    React.createElement("header", { className: "conjunction-card-heading" },
      React.createElement("div", null,
        React.createElement("span", { className: "conjunction-card-rank" }, `Research Pc rank ${rankLabel}`),
        React.createElement("h3", null, eventPair(event)),
        React.createElement("span", { className: `physics-status-badge ${valid ? "is-valid" : ""}` }, `Physics assessment: ${physics.status || "status not returned"}`)),
      React.createElement("div", { className: "conjunction-ai-score", "aria-label": `Prioritization index ${queueScore}${category ? `, model class ${category}` : ""}` },
        React.createElement("span", null, "Review priority (rule-based)"),
        React.createElement("strong", null, queueScore),
        category ? React.createElement("b", null, category) : null)),
    React.createElement("div", { className: "conjunction-card-metrics" },
      [["TCA (UTC)", tca], ["Miss distance", miss], ["Relative speed", speed]].map(([label, metric]) => React.createElement("div", { key: label }, React.createElement("span", null, label), React.createElement("strong", null, metric)))),
    React.createElement("section", { className: "conjunction-pc-primary", "aria-label": "Available collision probability" },
      React.createElement("span", null, preferred.label), React.createElement("strong", null, preferred.value)),
    React.createElement("p", { className: "conjunction-class-comparison" }, `Physics class ${physicsClass} · ${classComparison}`),
    React.createElement("div", { className: "conjunction-card-channels", "aria-label": "Separate collision probability channels" },
      React.createElement(ProbabilityChannel, { label: "Source-reported Pc", value: sourcePc !== null ? probability(sourcePc) : "No source value supplied for this event", method: sourcePc !== null ? `${foster.source_reported_pc_method || event.source_reported_pc_method || "Method undeclared"}; ${sourceProvenance.source || "Source not recorded"}` : null }),
      React.createElement(ProbabilityChannel, { label: "Event-specific Foster Pc", value: fosterAvailable ? probability(foster.pc) : "No Foster Pc value in this event", method: fosterAvailable ? `${foster.method || "Foster 2D"}; event-matched inputs` : "Requires compatible event covariance, frames, epochs, and sourced HBR" }),
      React.createElement(ProbabilityChannel, { label: "Assumption-based research Pc", value: research?.status === "prior_based_research_estimate" ? `${researchDisplay.value} Pc (${researchDisplay.percentage})` : "No research Pc estimate for this event", method: research?.status === "prior_based_research_estimate" ? `${research.covariance_policy_name || research.method_name}; sensitivity ${researchDisplay.sensitivity}` : researchDisplay.reason })),
    React.createElement("div", { className: "conjunction-card-ai" },
      React.createElement("strong", null, `Review priority (rule-based): ${queueScore}${category ? ` · ${category}` : ""}`),
      React.createElement("span", null, `${ai?.model_name || "No AI prioritization assessment"}${ai?.model_version ? ` v${ai.model_version}` : ""}; ${ai?.prediction_method || "Method not recorded"}`),
      React.createElement("small", null, ai ? `${ai.explanation || "No explanation supplied."} Deterministic prioritization index; not a probability or trained live collision predictor.` : "A score requires valid event geometry and relative speed.")),
    React.createElement("details", { className: "conjunction-collision-models" },
      React.createElement("summary", null, `Collision model · ${collisionAi?.status || pcSurrogate?.status || riskSurrogate?.status || "No model result returned"}`),
      React.createElement("p", null, `Pc surrogate: ${pcSurrogate?.status === "available"
        ? `${pcSurrogate.ai_predicted_log10_pc?.toFixed(4)} log10(Pc) · ${pcSurrogate.model_name || "model"} v${pcSurrogate.model_version || "unknown"}`
        : pcSurrogate?.status === "fallback"
          ? `AI estimate not emitted; deterministic research reference ${pcSurrogate.deterministic_reference_log10_pc?.toFixed(4)} log10(Pc) (${pcSurrogate.fallback_method}).`
          : `No Pc model result (${pcSurrogate?.reason_code || "not assessed"}).`}`),
      React.createElement("p", null, `Risk classifier: ${riskSurrogate?.status === "available"
        ? `${riskSurrogate.ai_risk_class} · ${riskSurrogate.model_name || "model"} v${riskSurrogate.model_version || "unknown"}`
        : riskSurrogate?.status === "fallback"
          ? `AI class not emitted; deterministic physics class ${riskSurrogate.deterministic_reference_risk_class} (${riskSurrogate.fallback_method}).`
          : `No classifier result (${riskSurrogate?.reason_code || "not assessed"}).`}`),
      React.createElement("small", null, "Model outputs support triage only. The physics research Pc remains authoritative; neither model is validated against observed collisions.")),
    React.createElement("p", { className: "conjunction-ranking-basis" }, React.createElement("b", null, "Ranking basis: "), Number.isFinite(research?.log10_pc)
      ? `Exact unfloored log10 Pc ${research.log10_pc}, descending; miss/sigma ${Number.isFinite(research.miss_sigma_ratio) ? research.miss_sigma_ratio : "not supplied"} breaks ties.`
      : "No research Pc value; shown for geometry review only and not as a calibrated collision-risk probability."),
    React.createElement("div", { className: "conjunction-card-actions" },
      React.createElement("button", { type: "button", className: "secondary-action", onClick: () => onSelect?.(event), "aria-label": `Open details for ${eventPair(event)}` }, "Details"),
      React.createElement("button", { type: "button", className: "secondary-action", disabled: !valid || !onShowInGlobe, title: valid ? "Show both event identities and focus the selected object in Visualization." : "A valid physical conjunction is required.", onClick: () => valid && onShowInGlobe?.(event.primary?.id, event, screeningJobId) }, "Show in Globe"),
      React.createElement("button", { type: "button", className: "primary-action", disabled: !valid, title: valid ? "Open Maneuver Assessment with this event." : "A valid physical conjunction is required.", onClick: () => valid && onAssessManeuver?.(event) }, "Assess Maneuver")),
    React.createElement("details", { className: "conjunction-technical-details" },
      React.createElement("summary", null, "Technical details and assessment evidence"),
      React.createElement("dl", null,
        React.createElement("dt", null, "Event identity"), React.createElement("dd", null, `${event.id || "ID not recorded"}; ${event.primary?.id || "?"} / ${event.secondary?.id || "?"}`),
        React.createElement("dt", null, "Assessment validity"), React.createElement("dd", null, `${physics.status || "Status not returned"}; ${(physics.reason_codes || []).map((code) => `${code}: ${explainPhysicsReason(code)}`).join("; ") || "No validation errors reported"}`),
        React.createElement("dt", null, "Foster Pc availability"), React.createElement("dd", null, operationalFosterStatus(event, fosterAvailable)),
        React.createElement("dt", null, "Foster method and provenance"), React.createElement("dd", null, fosterAvailable ? `${foster.method || "Foster 2D"}; event ID ${foster.event_id}; ${JSON.stringify(foster.provenance || {})}` : `${operationalFosterStatus(event, fosterAvailable)} Reason codes: ${(foster.reason_codes || []).join(", ") || "not supplied"}. No covariance, HBR, or Pc was inferred.`),
        React.createElement("dt", null, "Research estimate assumptions"), React.createElement("dd", null, research?.status === "prior_based_research_estimate" ? `${(research.assumptions || []).join(" ")} ${researchDisplay.reason} Provenance: ${research.provenance?.source || "ESA-derived prior"}; ${research.method_name || "research method"} v${research.method_version || "unknown"}. Not operational Pc.` : `${researchDisplay.reason} ${(research?.reason_codes || []).join(", ")}`),
        React.createElement("dt", null, "Source Pc provenance"), React.createElement("dd", null, sourcePc !== null ? `${foster.source_reported_pc_method || event.source_reported_pc_method || "Method undeclared"}; ${sourceProvenance.source || "Source not recorded"}; authenticated ${sourceProvenance.authenticated === true ? "yes" : "no / unverified"}` : "No event-matched source value."),
        React.createElement("dt", null, "Priorities and classification"), React.createElement("dd", null, `Review priority (rule-based) ${queueScore} (${ai?.model_name || "Method not recorded"}); Foster Pc class ${fosterAvailable ? foster.probability_classification?.category || "Not classified" : "No Foster Pc value"}; geometry review priority is not a Pc class.`),
        React.createElement("dt", null, "Trajectory source"), React.createElement("dd", null, `${provenance.source || "source unavailable"}; ${provenance.propagator || provenance.method || "propagator unavailable"}; frame ${provenance.reference_frame || physics.encounter_geometry?.frame || "unavailable"}; catalog timestamp ${provenance.source_timestamp || "unavailable"}`))));
  return card;
}

export function CollisionPriorityTable({ events = [], onSelect, onShowInGlobe, onAssessManeuver, screeningJobId, anomalyRanks: _anomalyRanks = new Map() }) {
  if (!events.length) return React.createElement("p", { className: "muted" }, "No screening events are available.");
  const ranked = searchAndSortCollisionEvents(events.filter((item) => item?.physics_result?.status === "valid" && item?.physics_result?.tca_status === "valid"), "", "research_pc");
  const invalid = events.filter((event) => event?.physics_result?.status === "invalid");
  const validEvents = events.filter((event) => event?.physics_result?.status === "valid" && event?.physics_result?.tca_status !== "boundary");
  const boundaryEvents = events.filter((event) => event?.physics_result?.tca_status === "boundary");
  const needsReview = events.filter((event) => !["valid", "invalid"].includes(event?.physics_result?.status)
    || event?.physics_result?.status === "valid" && !["valid", "boundary"].includes(event?.physics_result?.tca_status));
  const groups = groupCoLocatedEvents(validEvents);
  const groupByRepresentative = new Map(groups.map((group) => [group.representative.id, group]));
  const groupedIds = new Set(groups.flatMap((group) => group.members.map((member) => member.id)));
  const rankedIds = new Set(ranked.map((event) => event.id));
  const cards = [
    ...ranked.filter((event) => !groupedIds.has(event.id) || groupByRepresentative.has(event.id)),
    ...validEvents.filter((event) => !rankedIds.has(event.id) && (!groupedIds.has(event.id) || groupByRepresentative.has(event.id))),
  ];
  const rankById = new Map(cards.map((event, index) => [event.id, index + 1]));
  const renderCard = (event, index, boundary = false) => {
    const group = groupByRepresentative.get(event.id);
    return React.createElement(React.Fragment, { key: event.id || index },
      group ? React.createElement("p", { className: "encounter-group-label" }, `Encounter group: 1 encounter (${group.members.length} raw events) · +${group.coLocatedObjectCount} co-located objects; raw records retained`) : null,
      boundary ? React.createElement("p", { className: "boundary-solution-caveat", role: "note" }, "Boundary solution — TCA is at the screening-window edge; shown for review and excluded from ranking.") : null,
      React.createElement(EventCard, { event, rank: boundary ? null : rankById.get(event.id), onSelect, onShowInGlobe, onAssessManeuver, screeningJobId }),
      group ? React.createElement("details", { className: "encounter-group-members" },
        React.createElement("summary", null, `Show ${group.members.length} raw event records`),
        React.createElement("ul", null, group.members.map((member) => React.createElement("li", { key: member.id }, `${member.primary?.name || member.primary?.id} / ${member.secondary?.name || member.secondary?.id} · ${member.id}`)))) : null);
  };
  return React.createElement("div", { className: "conjunction-card-list" },
    validEvents.length ? cards.map((event, index) => renderCard(event, index)) : null,
    boundaryEvents.length ? React.createElement("details", { className: "invalid-assessment-group boundary-assessment-group" },
      React.createElement("summary", null, `Boundary solutions (${boundaryEvents.length}) — TCA at window edge; not ranked`),
      boundaryEvents.map((event, index) => renderCard(event, index, true))) : null,
    needsReview.length ? React.createElement("details", { className: "invalid-assessment-group" },
      React.createElement("summary", null, `Other assessments (${needsReview.length}) — no valid interior TCA; excluded from physical risk ranking`),
      React.createElement("div", { className: "conjunction-card-list invalid-assessment-list" }, needsReview.map((event, index) => React.createElement(EventCard, { key: event.id || index, event, rank: null, onSelect, onShowInGlobe, onAssessManeuver, screeningJobId })))) : null,
    invalid.length ? React.createElement("details", { className: "invalid-assessment-group" },
      React.createElement("summary", null, `Invalid physical assessments (${invalid.length}) — excluded from physical risk ranking`),
      React.createElement("div", { className: "conjunction-card-list invalid-assessment-list" }, invalid.map((event, index) => React.createElement(EventCard, { key: event.id || index, event, rank: null, onSelect, onShowInGlobe, onAssessManeuver, screeningJobId })))) : null);
}
