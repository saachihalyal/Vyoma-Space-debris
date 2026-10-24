import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { EventRiskEstimate } from "../src/components/UI/EventRiskEstimate.js";

const eventId = "EV-model-test";
const mlResult = {
  status: "available",
  model_name: "ORION ESA event final log10-risk estimator",
  model_version: "2.0.0",
  training_dataset: "ESA Collision Avoidance Challenge training dataset",
  provenance: { source_physics_event_id: eventId, live_feature_semantics_compatibility: "verified" },
  prediction: {
    predicted_log_risk: -7.25,
    predicted_risk_estimate: 5.623e-8,
    predicted_risk_probability: 5.623e-8,
    threshold_flag_at_minus_6: false,
    high_risk: false,
  },
  feature_frame: "instantaneous primary RTN at TCA",
  feature_units: { miss_distance_m: "m", relative_position_t_m: "m" },
  input_features: { miss_distance_m: 125.5, relative_position_t_m: 12.25 },
};

test("Collision Analysis ESA panel displays event-bound output and exact input values with scientific labels", () => {
  const markup = renderToStaticMarkup(React.createElement(EventRiskEstimate, {
    eventId,
    physical: true,
    mlResult,
    comparisonResult: { status: "not_comparable", reason_code: "ESA_LOG_RISK_NOT_PC" },
  }));

  assert.match(markup, /Inference status <strong>available<\/strong>/);
  assert.match(markup, /ESA final log10 historical event-risk; not Pc/);
  assert.match(markup, /Applicable data domain <strong>Historical ESA CDM conjunction records; live TLE-derived feature equivalence is unverified\.<\/strong>/);
  assert.match(markup, /ORION ESA event final log10-risk estimator · v2\.0\.0/);
  assert.match(markup, /Predicted log10 risk <strong>-7\.2500<\/strong>/);
  assert.match(markup, /Model inputs <strong>instantaneous primary RTN at TCA; feature attribution unavailable/);
  assert.match(markup, /Input · miss distance m <strong>125\.50 m<\/strong>/);
  assert.match(markup, /Input · relative position t m <strong>12\.250 m<\/strong>/);
  assert.match(markup, /Not directly comparable/);
  assert.match(markup, /fixed threshold detected 0\/145 high-risk labels/);
  assert.doesNotMatch(markup, /Pc <strong>5\.623/);
});

test("Collision Analysis ESA panel withholds a mismatched event prediction", () => {
  const markup = renderToStaticMarkup(React.createElement(EventRiskEstimate, {
    eventId: "EV-another-event",
    physical: true,
    mlResult,
  }));

  assert.match(markup, /ML_EVENT_ID_MISMATCH/);
  assert.match(markup, /INVALID_PREDICTION_PAYLOAD/);
  assert.doesNotMatch(markup, /-7\.2500|5\.6230e-8|Input · miss distance/);
});

test("Collision Analysis withholds stored output when live and historical feature semantics are unverified", () => {
  const unverified = { ...mlResult, provenance: { source_physics_event_id: eventId } };
  const markup = renderToStaticMarkup(React.createElement(EventRiskEstimate, {
    eventId,
    physical: true,
    mlResult: unverified,
  }));

  assert.match(markup, /Inference status <strong>unavailable · ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED/);
  assert.match(markup, /Feature compatibility/);
  assert.match(markup, /prediction withheld/);
  assert.match(markup, /MAE 6\.8935 log10 units, Spearman 0\.4424/);
  assert.doesNotMatch(markup, /-7\.2500|5\.6230e-8|Input Â· miss distance/);
});
