export function predictedEventRiskEstimate(prediction) {
  const value = typeof prediction?.predicted_risk_estimate === "number"
    ? prediction.predicted_risk_estimate
    : prediction?.predicted_risk_probability;
  return typeof value === "number" && Number.isFinite(value) && value > 0 && value <= 1
    ? value
    : null;
}

export function thresholdFlagAtMinus6(prediction) {
  if (typeof prediction?.threshold_flag_at_minus_6 === "boolean") return prediction.threshold_flag_at_minus_6;
  return typeof prediction?.high_risk === "boolean" ? prediction.high_risk : null;
}

export function hasUsableEventPrediction(mlResult, eventId) {
  const prediction = mlResult?.prediction;
  return mlResult?.status === "available"
    && (eventId === undefined || mlResult?.provenance?.source_physics_event_id === eventId)
    && typeof prediction?.predicted_log_risk === "number"
    && Number.isFinite(prediction.predicted_log_risk)
    && prediction.predicted_log_risk <= 0
    && predictedEventRiskEstimate(prediction) !== null
    && thresholdFlagAtMinus6(prediction) !== null;
}

export function usableEventPrediction(mlResult, eventId) {
  return hasUsableEventPrediction(mlResult, eventId) ? mlResult.prediction : null;
}
