import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { CollisionAnalysisSummary } from "../src/components/UI/CollisionAnalysisSummary.js";

test("Collision Analysis summary reports full-screening coverage and exact research-Pc ranking", () => {
  const displayed = [
    {
      id: "highest", primary: { id: "A", name: "Alpha" }, secondary: { id: "B", name: "Beta" },
      result_kind: "physics_assessment",
      physics_result: { status: "valid", tca_status: "valid", tca: { status: "available", value: "2026-10-24T12:00:00Z" } },
      collision_probability: { status: "available", event_id: "highest", pc: 1e-5 },
      automatic_research_pc_assessment: {
        status: "prior_based_research_estimate", log10_pc: -5, miss_sigma_ratio: 2,
        risk_assessment: { final_risk_class: "Medium", risk_score: 70 },
      },
      collision_ai_assessment: { status: "available" },
      ai_risk_assessment: { score: 0.72, final_priority_rank: 1, ranking_explanation: "Composite queue rank is separate from exact research-Pc ranking." },
    },
    {
      id: "second", result_kind: "physics_assessment",
      physics_result: { status: "valid", tca_status: "valid", tca: { status: "available", value: "2026-10-24T12:01:00Z" } },
      automatic_research_pc_assessment: { status: "unavailable", reason_codes: ["EVENT_MATCHED_COVARIANCE_AND_HBR_REQUIRED"] },
      ai_risk_assessment: { score: 0.31, final_priority_rank: 2 },
    },
  ];
  const markup = renderToStaticMarkup(React.createElement(CollisionAnalysisSummary, {
    events: [...displayed, { id: "not-returned", result_kind: "physics_assessment" }],
    displayedEvents: displayed,
    screeningStatus: { assessment_record_count: 22 },
  }));
  assert.match(markup, /Total screened conjunctions/);
  assert.match(markup, /<strong>22<\/strong>/);
  assert.match(markup, /Events currently displayed/);
  assert.match(markup, /<strong>2 of 22<\/strong>/);
  assert.match(markup, /Valid physical conjunctions[\s\S]*<strong>2 of 2<\/strong>/);
  assert.match(markup, /Event-specific Foster Pc[\s\S]*<strong>1 of 2<\/strong>/);
  assert.match(markup, /Valid events with research Pc[\s\S]*<strong>1 of 2<\/strong>/);
  assert.match(markup, /Valid events with reason code[\s\S]*<strong>1 of 2<\/strong>/);
  assert.match(markup, /Valid events without Pc or reason[\s\S]*<strong>0<\/strong>/);
  assert.match(markup, /Events with separate AI model outputs[\s\S]*<strong>1 of 2<\/strong>/);
  assert.match(markup, /Alpha \(A\) vs Beta \(B\)[\s\S]*log10 Pc -5/);
  assert.match(markup, /Ranking basis: exact unfloored log10 Pc, descending; miss\/sigma is the tie-breaker/);
  assert.match(markup, /Medium: 1/);
  assert.match(markup, /<details class="og-acc screening-details"><summary>Screening details<\/summary>/);
  assert.match(markup, /Histogram of exact research log10 Pc values/);
  assert.doesNotMatch(markup, /No actionable conjunctions/);
});
