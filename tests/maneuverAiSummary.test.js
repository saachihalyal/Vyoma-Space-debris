import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ManeuverAiSummary } from "../src/components/UI/ManeuverAiSummary.js";

test("Maneuver Assessment labels model outputs research-only and shows held-out evidence", () => {
  const markup = renderToStaticMarkup(React.createElement(ManeuverAiSummary, {
    result: {
      status: "research_only",
      reason_code: "HELD_OUT_RANKING_NOT_USEFUL_VS_BASELINE",
      model_name: "ORION simulated two-body maneuver miss-distance ranker",
      model_version: "1.0.0",
      is_simulator_surrogate: true,
      synthetic_training_labels: true,
      ranking_used: false,
      score_name: "predicted two-body simulated closest-approach miss distance",
      score_units: "km",
      score_semantics: "Diagnostic estimate only, not used to rank candidates.",
      evaluation_summary: {
        held_out_scenario_count: 12,
        held_out_candidate_count: 72,
        mean_within_scenario_spearman: -0.0686,
        top1_agreement_with_simulator_best: 0.25,
        model_mean_regret_km: 0.0591,
        minimum_delta_v_baseline_mean_regret_km: 0.0370,
      },
      provenance: { source_event_id: "EV-1", screening_job_id: "JOB-1" },
    },
  }));
  assert.match(markup, /research_only · HELD_OUT_RANKING_NOT_USEFUL_VS_BASELINE/);
  assert.match(markup, /ORION simulated two-body maneuver miss-distance ranker v1\.0\.0/);
  assert.match(markup, /predicted two-body simulated closest-approach miss distance \(km\); diagnostic only, not used to rank candidates/);
  assert.match(markup, /12 scenarios \/ 72 candidates/);
  assert.match(markup, /top-1 agreement 25%/);
  assert.match(markup, /model regret 0\.0591 km/);
  assert.match(markup, /minimum-Δv baseline regret 0\.0370 km/);
  assert.match(markup, /synthetic simulator surrogate is not Pc, safety, or a verified improvement/);
  assert.match(markup, /Synthetic simulator-generated miss distance; not a real maneuver outcome/);
  assert.match(markup, /Not used; physics sweep order is unchanged/);
  assert.match(markup, /JOB-1/);
});

test("unavailable maneuver model is explicit and never rendered as a numeric score", () => {
  const markup = renderToStaticMarkup(React.createElement(ManeuverAiSummary, {
    result: { status: "unavailable", reason_code: "MANEUVER_MODEL_ARTIFACT_UNAVAILABLE", candidate_scores: {} },
  }));
  assert.match(markup, /MANEUVER_MODEL_ARTIFACT_UNAVAILABLE/);
  assert.match(markup, /No model score is available/);
  assert.doesNotMatch(markup, /0\.000000/);
});
