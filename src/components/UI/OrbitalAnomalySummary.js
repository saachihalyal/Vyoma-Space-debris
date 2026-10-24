import React from "react";

const h = React.createElement;

export function OrbitalAnomalySummary({ result }) {
  if (!result || result.status !== "available" || !Number.isFinite(result.anomaly_score)) {
    return h("div", { className: "readout-list", "aria-live": "polite" },
      h("span", null, "AI anomaly assessment", h("strong", null, `Unavailable · ${result?.reason_code || "ANOMALY_RESULT_NOT_RETURNED"}`)),
      h("p", { className: "muted" }, "This result is separate from ESA historical event-risk and Foster collision probability."));
  }
  const rows = Object.entries(result.input_features || {});
  return h("div", { className: "readout-list", "aria-live": "polite" },
    h("span", null, "Interpretation", h("strong", null, "Unusualness relative to historical feature records; not danger or collision risk")),
    h("span", null, "Model assessment", h("strong", null, `${result.classification === "unusual" ? "Flagged unusual" : "Not flagged unusual"} · score ${result.anomaly_score.toFixed(3)} (unitless empirical tail rank)`)),
    Number.isFinite(result.decision_score) ? h("span", null, "Isolation Forest decision_function", h("strong", null, result.decision_score.toPrecision(8))) : null,
    h("span", null, "Model", h("strong", null, `${result.model_name || "Unavailable"} · v${result.model_version || "unknown"}`)),
    h("span", null, "Training reference", h("strong", null, `${result.training_dataset || "Unavailable"} · ${result.training_reference_event_count ?? "?"} training events`)),
    h("span", null, "Feature frame", h("strong", null, result.feature_frame || "Unavailable")),
    h("details", null,
      h("summary", null, "Features used (actual Stage 2A event)"),
      h("ul", null, ...rows.map(([name, value]) => h("li", { key: name }, `${name}: ${Number(value).toPrecision(6)} ${result.feature_units?.[name] || ""}`)))));
}

export function EventAnomalyPanel({ physical, eventId, result }) {
  if (physical && result?.status === "available" && result.provenance?.source_physics_event_id !== eventId) {
    return h("div", { className: "readout-list", "aria-live": "polite" },
      h("span", null, "AI anomaly assessment", h("strong", null, "Unavailable · ANOMALY_EVENT_ID_MISMATCH")),
      h("p", { className: "muted" }, "The prediction provenance does not match the selected physical event."));
  }
  return physical
    ? h(OrbitalAnomalySummary, { result })
    : h("p", { className: "muted" }, "Unavailable for heuristic-only proxy pairs; no Stage 2A physical event features exist.");
}
