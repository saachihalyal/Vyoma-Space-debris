import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { EventAnomalyPanel, OrbitalAnomalySummary } from "../src/components/UI/OrbitalAnomalySummary.js";

test("physical event anomaly presentation shows separate model score and actual features", () => {
  const markup = renderToStaticMarkup(React.createElement(OrbitalAnomalySummary, { result: {
    status: "available", classification: "unusual", anomaly_score: 0.97,
    model_name: "ORION orbital feature Isolation Forest", model_version: "1.0.0",
    training_dataset: "ESA Collision Avoidance Challenge training dataset",
    training_reference_event_count: 9000, feature_frame: "instantaneous primary RTN at TCA",
    decision_score: 0.01239424,
    provenance: { source_physics_event_id: "CA-A" },
    input_features: { miss_distance_m: 1234 }, feature_units: { miss_distance_m: "m" },
  } }));
  assert.match(markup, /not danger or collision risk/);
  assert.match(markup, /Flagged unusual/);
  assert.match(markup, /0\.970/);
  assert.match(markup, /1234\.00 m/);
  assert.match(markup, /0\.01239424/);
  assert.doesNotMatch(markup, /Foster|Pc/);
});

test("heuristic proxy presentation never exposes an anomaly prediction", () => {
  const markup = renderToStaticMarkup(React.createElement(EventAnomalyPanel, { physical: false, eventId: "PROXY", result: {
    status: "available", classification: "unusual", anomaly_score: 0.99,
  } }));
  assert.match(markup, /Unavailable for heuristic-only proxy pairs/);
  assert.doesNotMatch(markup, /0\.990|Flagged unusual/);
});

test("physical anomaly prediction from a different event is never rendered for the selection", () => {
  const markup = renderToStaticMarkup(React.createElement(EventAnomalyPanel, { physical: true, eventId: "CA-B", result: {
    status: "available", anomaly_score: 0.97, classification: "unusual",
    provenance: { source_physics_event_id: "CA-A" },
  } }));
  assert.match(markup, /ANOMALY_EVENT_ID_MISMATCH/);
  assert.doesNotMatch(markup, /0\.970|Flagged unusual/);
});

test("unavailable anomaly inference displays a reason and no numeric zero", () => {
  const markup = renderToStaticMarkup(React.createElement(OrbitalAnomalySummary, { result: {
    status: "unavailable", reason_code: "PHYSICS_FRAME_UNAVAILABLE", anomaly_score: null,
  } }));
  assert.match(markup, /Unavailable/);
  assert.match(markup, /PHYSICS_FRAME_UNAVAILABLE/);
  assert.doesNotMatch(markup, /0\.000/);
});
