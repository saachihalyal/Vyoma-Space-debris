import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ManeuverAiSummary } from "../src/components/UI/ManeuverAiSummary.js";

test("maneuver research-Pc ranker shows held-out parent metrics and physics ordering", () => {
  const markup = renderToStaticMarkup(React.createElement(ManeuverAiSummary, { result: {
    status: "fallback_physics_ranking", model_name: "ORION physics-supervised maneuver research-Pc reduction ranker",
    model_version: "1.0.0", ranking_used: false, score_name: "predicted log10 research-Pc reduction",
    score_units: "log10 ratio; positive predicts reduction", evaluation_summary: {
      held_out_scenario_count: 9, held_out_candidate_count: 51, mean_within_scenario_spearman: 0.4222,
      top1_agreement_with_physics_best: 0.3333, model_mean_regret_log10_pc_reduction: 0.6623,
      baseline_mean_regret_log10_pc_reduction: 1.5622,
    }, provenance: { source_event_id: "EV-1", screening_job_id: "JOB-1" },
  } }));
  assert.match(markup, /ORION physics-supervised maneuver research-Pc reduction ranker v1\.0\.0/);
  assert.match(markup, /Physics-generated log10\(Pc zero-burn \/ Pc candidate\)/);
  assert.match(markup, /9 parents \/ 51 candidates/);
  assert.match(markup, /top-1 agreement 33\.3%/);
  assert.match(markup, /model regret 0\.6623 vs baseline 1\.5622 log10 units/);
  assert.match(markup, /Deterministic physics research-Pc ordering is used/);
  assert.match(markup, /JOB-1/);
});

test("unavailable maneuver model is explicit and never rendered as a numeric score", () => {
  const markup = renderToStaticMarkup(React.createElement(ManeuverAiSummary, { result: { status: "unavailable", reason_code: "MANEUVER_MODEL_ARTIFACT_UNAVAILABLE", candidate_scores: {} } }));
  assert.match(markup, /MANEUVER_MODEL_ARTIFACT_UNAVAILABLE/);
  assert.match(markup, /AI artifact unavailable or invalid/);
  assert.doesNotMatch(markup, /0\.000000/);
});
