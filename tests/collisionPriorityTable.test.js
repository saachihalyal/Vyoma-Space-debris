import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { CollisionPriorityTable } from "../src/components/UI/CollisionPriorityTable.js";
import capturedRealScreeningEvent from "./fixtures/capturedRealScreeningEvent.json" with { type: "json" };
import { CollisionAnalysisSummary } from "../src/components/UI/CollisionAnalysisSummary.js";
import { researchPcPresentation } from "../src/utils/collisionPcPresentation.js";

const capturedRestoredApiEvent = JSON.parse(readFileSync(new URL("./fixtures/capturedRestoredApiEvent.json", import.meta.url), "utf8").replace(/^\uFEFF/, ""));

function render(events) {
  return renderToStaticMarkup(React.createElement(CollisionPriorityTable, {
    events,
    screeningJobId: "job-captured",
    onSelect: () => {},
    onShowInGlobe: () => {},
    onAssessManeuver: () => {},
  }));
}

test("responsive conjunction cards separate Pc provenance, label rule-based review priority, and expose workflow actions", () => {
  const event = {
    id: "computed", result_kind: "physics_assessment",
    primary: { id: "A", name: "Alpha" }, secondary: { id: "B", name: "Beta" },
    physics_result: {
      status: "valid", tca: { status: "available", value: "2026-01-01T00:00:00Z" },
      miss_distance: { status: "available", value: 2 }, relative_speed_at_tca: { status: "available", value: 0.012 },
      relative_velocity_at_tca: { status: "available", value: [0.001, 0.01, 0] },
      encounter_geometry: { frame: "TEME" },
      provenance: { source: "CelesTrak TLE", propagator: "SGP4", reference_frame: "TEME", source_timestamp: "2025-12-30T00:00:00Z" },
    },
    collision_probability: { status: "available", event_id: "computed", pc: 1e-4, method: "Foster 2D", source_reported_pc: 2e-4, source_reported_event_id: "computed", source_reported_pc_method: "CDM", probability_classification: { status: "classified", category: "HIGH" } },
    automatic_research_pc_assessment: { status: "event_specific_foster_available", quality_status: "validated_event_inputs", reason_codes: [] },
    ai_risk_assessment: {
      score: 0.73, category: "High", model_name: "ORION deterministic live-geometry risk prioritizer", model_version: "1.0.0",
      prediction_method: "deterministic_geometry_speed_fallback", final_priority_rank: 1, geometry_rank: 1, foster_pc_rank: 1,
      explanation: "Geometry and speed based queue index", ranking_explanation: "Final priority combines AI index and geometry.",
    },
  };
  const markup = render([event]);
  for (const label of ["Source-reported Pc", "Event-specific Foster Pc", "Assumption-based research Pc", "Review priority", "Technical details and assessment evidence"]) assert.match(markup, new RegExp(label));
  assert.match(markup, /1\.000 \u00d7 10\^-4 Pc/);
  assert.match(markup, /1\.000e-2%/);
  assert.match(markup, /73\.0 \/ 100/);
  assert.match(markup, /Foster Pc class HIGH/);
  assert.match(markup, /ORION deterministic live-geometry risk prioritizer v1\.0\.0/);
  assert.match(markup, /Deterministic prioritization index; not a probability or trained live collision predictor/);
  assert.match(markup, /Show in Globe/);
  assert.match(markup, /Assess Maneuver/);
  assert.match(markup, /conjunction-card-list/);
  assert.doesNotMatch(markup, /<table/);
});

test("selected conjunction details keep Pc channels, AI queue and ranking basis compact while tools stay expandable", () => {
  const app = readFileSync(new URL("../src/components/UI/CollisionWorkbench.jsx", import.meta.url), "utf8")
    + readFileSync(new URL("../src/components/UI/CollisionPriorityTable.js", import.meta.url), "utf8");
  assert.match(app, /covariance_policy_name/);
  assert.match(app, /Separate collision probability channels/);
  assert.match(app, /Ranking details/);
  assert.match(app, /AI class/);
  assert.match(app, /Upload Conjunction Data/);
  const pageWiring = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(pageWiring, /onAssessManeuver=\{\(item\) => selectEvent\(item, "maneuver"\)\}/);
  assert.match(pageWiring, /onShowInGlobe=\{onShowInGlobe\}/);
});

test("Show in Globe and Maneuver Assessment pass the exact selected event identity", () => {
  const selected = {
    id: "event-selected", result_kind: "physics_assessment",
    primary: { id: "10114", name: "Object A" }, secondary: { id: "25544", name: "Object B" },
    physics_result: { status: "valid", tca: { value: "2026-10-13T12:56:17Z" } },
  };
  let globeCall;
  let maneuverCall;
  const tree = CollisionPriorityTable({
    events: [selected], screeningJobId: "job-selected", onSelect: () => {},
    onShowInGlobe: (...args) => { globeCall = args; },
    onAssessManeuver: (event) => { maneuverCall = event; },
  });
  const buttons = [];
  function visit(node) {
    if (Array.isArray(node)) { node.forEach(visit); return; }
    if (!React.isValidElement(node)) return;
    if (typeof node.type === "function") { visit(node.type(node.props)); return; }
    if (node.type === "button") buttons.push(node);
    visit(node.props.children);
  }
  visit(tree);
  buttons.find((button) => button.props.children === "Show in Globe").props.onClick();
  buttons.find((button) => button.props.children === "Assess Maneuver").props.onClick();
  assert.equal(globeCall[0], selected.primary.id);
  assert.equal(globeCall[1], selected);
  assert.deepEqual([globeCall[1].primary.id, globeCall[1].secondary.id], ["10114", "25544"]);
  assert.equal(globeCall[1].physics_result.tca.value, "2026-10-13T12:56:17Z");
  assert.equal(globeCall[2], "job-selected");
  assert.equal(maneuverCall, selected);
});

test("captured real screening API event keeps research Pc numerical through card and summary rendering", () => {
  const event = capturedRealScreeningEvent;
  assert.equal(event.id, "CA-CDBC9233F65C7BE0EE0A");
  assert.equal(event.primary.id, "33762");
  assert.equal(event.secondary.id, "33776");
  assert.equal(event.physics_result.tca.value, "2026-10-14T06:22:15.243148+00:00");
  assert.equal(event.automatic_research_pc_assessment.estimated_pc_scientific, "1.55992e-167");
  assert.equal(event.ai_risk_assessment.category, "Low");
  assert.equal(researchPcPresentation(event.automatic_research_pc_assessment).value, "1.55992e-167");

  const markup = render([event]);
  assert.match(markup, /Assumption-based research Pc/);
  assert.match(markup, /1\.55992e-167 Pc \(1\.55992e-165%\)/);
  assert.match(markup, /assumption-based research Pc/i);
  assert.match(markup, /33\.3 \/ 100/);
  assert.doesNotMatch(markup, /class Low/);
  assert.match(markup, /Deterministic prioritization index; not a probability or trained live collision predictor/);

  const summary = renderToStaticMarkup(React.createElement(CollisionAnalysisSummary, {
    events: [event], displayedEvents: [event], screeningStatus: { assessment_record_count: 1 },
  }));
  assert.match(summary, /Valid events with research Pc/);
  assert.match(summary, /0 of 1/);
});

test("actual restored backend API event keeps the same Pc and AI values in frontend card rendering", () => {
  const event = capturedRestoredApiEvent;
  assert.equal(event.id, "CA-0E45D17A7FD97444E98C");
  assert.equal(event.primary.id, "33762");
  assert.equal(event.secondary.id, "33776");
  assert.equal(event.physics_result.tca.value, "2026-10-14T06:22:15.243382+00:00");
  assert.equal(event.automatic_research_pc_assessment.estimated_pc_scientific, "1.55352e-167");
  assert.equal(researchPcPresentation(event.automatic_research_pc_assessment).value, "1.55352e-167");
  assert.equal(event.ai_risk_assessment.score, 0.3329003363206914);
  assert.equal(event.ai_risk_assessment.category, "Low");
  assert.equal(event.ai_risk_assessment.prediction_method, "deterministic_geometry_speed_fallback");
  assert.equal(event.collision_probability.status, "unavailable");

  const html = render([event]);
  assert.match(html, /1\.55352e-167 Pc \(1\.55352e-165%\)/);
  assert.match(html, /33\.3 \/ 100/);
  assert.doesNotMatch(html, /class Low/);
  assert.match(html, /assumption-based research Pc/i);
  assert.match(html, /Show in Globe/);
  assert.match(html, /Assess Maneuver/);
});

test("cards reject a Foster Pc belonging to another event", () => {
  const markup = render([{ id: "event-A", result_kind: "physics_assessment", primary: { id: "A" }, secondary: { id: "B" }, physics_result: { status: "valid" }, collision_probability: { status: "available", event_id: "event-B", pc: 0.25 } }]);
  assert.match(markup, /Event-specific Foster Pc/);
  assert.match(markup, /Rejected: Pc event identity mismatch/);
  assert.doesNotMatch(markup, /2\.500e-1/);
});

test("invalid assessments are isolated from physical ranking and actions", () => {
  const markup = render([{ id: "invalid", result_kind: "physics_assessment", primary: { id: "A" }, secondary: { id: "B" }, physics_result: { status: "invalid", reason_codes: ["duplicate_tle_state_for_distinct_catalog_ids"] } }]);
  assert.match(markup, /Invalid physical assessments \(1\)/);
  assert.match(markup, /Physics assessment: invalid/);
  assert.match(markup, /duplicate_tle_state_for_distinct_catalog_ids/);
  assert.match(markup, /duplicate TLE states; this pair is ambiguous/i);
  assert.match(markup, /disabled=""/);
  assert.match(markup, /Not ranked/);
});

test("horizon-boundary assessments are kept outside valid conjunction cards and are unranked", () => {
  const markup = render([{ id: "boundary", result_kind: "physics_assessment", primary: { id: "A" }, secondary: { id: "B" }, physics_result: { status: "boundary", reason_codes: ["TCA_ON_SCREENING_BOUNDARY"] } }]);
  assert.match(markup, /Other assessments \(1\)/);
  assert.match(markup, /no valid interior TCA; excluded from physical risk ranking/);
  assert.match(markup, /Research Pc rank Not ranked \(boundary\)/);
  assert.match(markup, /disabled=""/);
});

test("malformed AI data gets a concise missing-score reason and is not classified as low", () => {
  const markup = render([{ id: "malformed-ai", result_kind: "physics_assessment", primary: { id: "A" }, secondary: { id: "B" }, physics_result: { status: "valid" }, ai_risk_assessment: { category: "High", score: null } }]);
  assert.match(markup, /Review priority \(rule-based\)/);
  assert.match(markup, /Review priority \(rule-based\): No score returned/);
  assert.match(markup, /Physics class Class not assigned · AI class not returned/);
  assert.doesNotMatch(markup, /AI class High/);
});

test("collision surrogates remain distinct from deterministic fallback values", () => {
  const markup = render([{
    id: "ai-fallback", result_kind: "physics_assessment",
    primary: { id: "A" }, secondary: { id: "B" }, physics_result: { status: "valid" },
    automatic_research_pc_assessment: { status: "prior_based_research_estimate", estimated_pc_scientific: "2.0e-8" },
    collision_ai_assessment: {
      status: "fallback",
      pc_surrogate: { status: "fallback", deterministic_reference_log10_pc: -7.69897, fallback_method: "physics_research_pc_reference" },
      risk_classifier: { status: "fallback", deterministic_reference_risk_class: "Low", fallback_method: "physics_research_pc_classification" },
    },
  }]);
  assert.match(markup, /Collision model · fallback/);
  assert.match(markup, /AI estimate not emitted; deterministic research reference -7\.6990 log10\(Pc\)/);
  assert.match(markup, /AI class not emitted; deterministic physics class Low/);
  assert.doesNotMatch(markup, /AI predicted log10/);
});

