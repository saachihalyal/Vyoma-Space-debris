import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { CollisionAnalysisSummary } from "../src/components/UI/CollisionAnalysisSummary.js";

test("Collision Analysis summary reports screened/displayed and Pc/AI counts with the actual top-rank reason", () => {
  const displayed = [
    {
      id: "highest", primary: { id: "A", name: "Alpha" }, secondary: { id: "B", name: "Beta" },
      physics_result: { status: "valid" },
      collision_probability: { status: "available", event_id: "highest", pc: 1e-5 },
      automatic_research_pc_assessment: { status: "prior_based_research_estimate" },
      ai_risk_assessment: { score: 0.72, final_priority_rank: 1, ranking_explanation: "Final rank uses geometry and the compatible Foster Pc percentile." },
    },
    { id: "second", physics_result: { status: "valid" }, ai_risk_assessment: { score: 0.31, final_priority_rank: 2 } },
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
  assert.match(markup, /Numerical research Pc[\s\S]*<strong>1 of 2<\/strong>/);
  assert.match(markup, /AI-prioritized events[\s\S]*<strong>2 of 2<\/strong>/);
  assert.match(markup, /Alpha \(A\) vs Beta \(B\) \| final rank #1/);
  assert.match(markup, /Ranking basis: Final rank uses geometry and the compatible Foster Pc percentile/);
});
