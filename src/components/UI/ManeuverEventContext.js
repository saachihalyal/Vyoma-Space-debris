import React from "react";

function value(field, units = "") {
  return field?.status === "available" && typeof field.value === "number" && Number.isFinite(field.value)
    ? `${field.value}${units}`
    : "Unavailable";
}

function pcLabel(item, key) {
  return item?.status === "available" && Number.isFinite(item[key])
    ? `${item[key].toExponential(5)}${item.method ? ` · ${item.method}` : ""}`
    : "Unavailable";
}

export function ManeuverEventContext({ event, context }) {
  if (!event) return null;
  const physics = event.physics_result || {};
  const ctx = context || {};
  const pc = event.collision_probability || {};
  const pcBoundToEvent = pc.status === "available"
    && pc.event_id === event.id
    && pc.object_1_id === event.primary?.id
    && pc.object_2_id === event.secondary?.id
    && pc.tca_utc === (ctx.tca_utc || physics.tca?.value)
    && Number.isFinite(pc.pc) && pc.pc >= 0 && pc.pc <= 1;
  const research = event.automatic_research_pc_assessment || {};
  const researchAvailable = research.status === "prior_based_research_estimate"
    && typeof research.estimated_pc_scientific === "string";
  const ai = event.ai_risk_assessment || {};
  return React.createElement("section", { className: "panel maneuver-event-context", "aria-label": "Selected conjunction context" },
    React.createElement("div", { className: "panel-heading" }, React.createElement("h2", null, "Selected Conjunction Context")),
    React.createElement("div", { className: "maneuver-summary-grid" },
      React.createElement("span", null, "Event / object IDs", React.createElement("strong", null, `${event.id} · ${event.primary?.id} / ${event.secondary?.id}`)),
      React.createElement("span", null, "TCA", React.createElement("strong", null, ctx.tca_utc || physics.tca?.value || "Unavailable")),
      React.createElement("span", null, "Stage 2A miss distance", React.createElement("strong", null, `${value(physics.miss_distance, " km")} · SGP4`)),
      React.createElement("span", null, "Relative velocity", React.createElement("strong", null, `${(ctx.relative_velocity_km_s ?? physics.relative_velocity_at_tca?.value)?.map?.((x) => Number(x).toFixed(6)).join(", ") || "Unavailable"} km/s`)),
      React.createElement("span", null, "State frame", React.createElement("strong", null, physics.state_information?.source_frame || "Unavailable")),
      React.createElement("span", null, "Source-reported Pc", React.createElement("strong", null, pcLabel({ status: pc.source_reported_event_id === event.id && Number.isFinite(pc.source_reported_pc) && pc.source_reported_pc >= 0 && pc.source_reported_pc <= 1 ? "available" : "unavailable", pc: pc.source_reported_pc, method: pc.source_reported_pc_method }, "pc"))),
      React.createElement("span", null, "Event-specific Foster Pc", React.createElement("strong", null, pcLabel({ ...pc, status: pcBoundToEvent ? "available" : "unavailable" }, "pc"))),
      React.createElement("span", null, "Research Pc estimate", React.createElement("strong", null, researchAvailable ? `${research.estimated_pc_scientific} · ${research.method_name || "research model"}` : `Unavailable · ${research.reason_code || "model inputs unavailable"}`)),
      React.createElement("span", null, "Review priority (rule-based)", React.createElement("strong", null, Number.isFinite(ai.score) ? `${ai.score.toFixed(4)} · ${ai.category || "review band"}` : "Unavailable")),
      React.createElement("span", null, "Covariance / HBR provenance", React.createElement("strong", null, pcBoundToEvent
        ? `${pc.covariance_status || "validated"} · ${pc.covariance_sources?.map?.((source) => source.source).filter(Boolean).join(", ") || "source recorded"} · HBR ${pc.hbr_km ?? "unavailable"} km (${pc.hbr_source || "source unavailable"})`
        : `${physics.covariance?.reason_code || "covariance unavailable"} · ${physics.hard_body_radius?.reason_code || "HBR unavailable"}`))),
    React.createElement("p", { className: "muted" }, "These Pc sources and the rule-based review priority are separate evidence. A maneuver comparison uses the declared research covariance/HBR policy at the zero-burn and candidate TCAs; that covariance is assigned at TCA rather than dynamically propagated."));
}
