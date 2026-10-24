import React from "react";
import { hasUsableEventPrediction, predictedEventRiskEstimate, usableEventPrediction } from "../../utils/mlPrediction.js";

const readout = (label, value) => React.createElement(
  "span", { key: label }, label, " ", React.createElement("strong", null, value),
);

export function EventRiskEstimate({ eventId, physical, mlResult = {}, comparisonResult = {}, explainReason = (code) => code || "unavailable" }) {
  if (!physical) {
    return React.createElement("p", { className: "muted" }, "Unavailable for heuristic-only proxies because no physical event features exist.");
  }

  const prediction = usableEventPrediction(mlResult, eventId);
  const featureSemanticsVerified = mlResult.provenance?.live_feature_semantics_compatibility === "verified";
  const hasPrediction = hasUsableEventPrediction(mlResult, eventId) && featureSemanticsVerified;
  const inferenceStatus = hasPrediction
    ? "available"
    : mlResult.status === "available" && !featureSemanticsVerified
      ? "unavailable · ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED"
    : mlResult.status === "available" && mlResult.provenance?.source_physics_event_id !== eventId
      ? "unavailable · ML_EVENT_ID_MISMATCH"
      : mlResult.status === "available"
        ? "error · invalid_prediction_payload"
        : mlResult.status || "unavailable";
  const children = [
    readout("Inference status", inferenceStatus),
    readout("Output target", "ESA final log10 historical event-risk; not Pc"),
    readout("Applicable data domain", "Historical ESA CDM conjunction records; live TLE-derived feature equivalence is unverified."),
    mlResult.model_name ? readout("Model", `${mlResult.model_name} · v${mlResult.model_version || "unknown"}`) : null,
    mlResult.training_dataset ? readout("Training dataset", mlResult.training_dataset) : null,
    mlResult.provenance ? readout("Inference provenance", `event ${mlResult.provenance.source_physics_event_id || "unavailable"}; artifact ${mlResult.provenance.artifact_sha256 || "unavailable"}; dataset ${mlResult.provenance.training_dataset_sha256 || "unavailable"}`) : null,
    !featureSemanticsVerified ? readout("Feature compatibility", "Historical ESA CDM and live TLE-derived feature semantics are unverified; prediction withheld.") : null,
  ];
  if (hasPrediction) {
    children.push(
      readout("Predicted log10 risk", Number(prediction.predicted_log_risk).toFixed(4)),
      readout("Exponentiated ESA event-risk estimate (not calibrated)", Number(predictedEventRiskEstimate(prediction)).toExponential(4)),
      readout("Training target", "ESA final event risk in log10 space"),
      readout("Model inputs", `${mlResult.feature_frame || "Frame unavailable"}; feature attribution unavailable`),
    );
    for (const [name, value] of Object.entries(mlResult.input_features || {})) {
      children.push(readout(`Input · ${name.replaceAll("_", " ")}`, `${Number(value).toPrecision(5)} ${mlResult.feature_units?.[name] || "units unavailable"}`));
    }
  } else {
    const unavailableReason = mlResult.status === "available" && !featureSemanticsVerified
      ? "ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED"
      : mlResult.reason_code || (mlResult.status === "available" ? "INVALID_PREDICTION_PAYLOAD" : null);
    children.push(readout("Unavailable reason", explainReason(unavailableReason)));
  }
  children.push(
    readout("Comparison", comparisonResult.status === "not_comparable" ? "Not directly comparable" : comparisonResult.status || "Unavailable"),
    readout("Comparison reason", comparisonResult.reason_code || "No compatible shared physical quantity exists."),
    readout("Validation limitation", "Mission-held-out test: MAE 6.8935 log10 units, Spearman 0.4424; the fixed threshold detected 0/145 high-risk labels. Historical and live feature semantics are unverified; research only."),
  );
  return React.createElement("div", { className: "readout-list" }, children);
}
