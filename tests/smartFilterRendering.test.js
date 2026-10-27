import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { SmartFilterPage } from "../src/components/UI/SmartFilterPage.js";
import { eligibleManeuverEvents, maneuverPageState, selectManeuverEvent } from "../src/utils/maneuverSelection.js";
import { buildSmartFilterView, smartFilterObjectReasons, smartFilterRecordIdentity } from "../src/utils/smartFilterView.js";
import { catalogHoverDetails } from "../src/utils/catalogHover.js";
import { hasUsableEventPrediction, predictedEventRiskEstimate, thresholdFlagAtMinus6, usableEventPrediction } from "../src/utils/mlPrediction.js";

const baseSnapshot = {
  objects: [],
  risk_cells: [],
  stats: { tracked_objects: 0 },
};

test("physical Smart Filter workbench is wired to API decisions and key science labels", () => {
  const source = readFileSync(new URL("../src/components/UI/SmartFilterWorkbench.jsx", import.meta.url), "utf8");
  const client = readFileSync(new URL("../src/api/ssaClient.js", import.meta.url), "utf8");
  const backend = readFileSync(new URL("../backend/app/main.py", import.meta.url), "utf8");
  assert.match(source, /getLatestConjunctionJob\(\{ signal: controller\.signal \}\)/);
  assert.match(source, /getPhysicalSmartFilter\(job\.job_id/);
  assert.match(source, /const jobId = acceptedJob\?\.job_id/);
  assert.doesNotMatch(source, /platform\.conjunctionStatus\?\.job_id/);
  assert.match(source, /physicalSmartFilterCsvPath\(jobId\)/);
  assert.match(source, /globePositions\.before_objects/);
  assert.match(source, /globePositions\.after_objects/);
  assert.match(source, /propagationEpoch=\{propagationEpoch\}/);
  assert.match(backend, /def _smart_filter_globe_positions\(/);
  assert.match(backend, /satellite\.sgp4\(jd, fr\)/);
  assert.match(backend, /"before_objects"/);
  assert.match(backend, /"after_objects"/);
  assert.match(source, /plainReason/);
  assert.match(source, /Download CSV/);
  assert.match(source, /disabled=\{!jobId \|\| !decisions\.length\}/);
  assert.match(source, /Physics vs AI/);
  assert.match(source, /smart-filter-count-columns/);
  assert.match(source, /Agree on \{agree\} of \{rows\.length\} pairs/);
  assert.match(source, /smart-filter-excluded/);
  assert.match(source, /Excluded \(\{excludedRows\.length\}\)/);
  assert.match(source, /plainReason/);
  assert.match(source, /smart-filter-globes/);
  assert.match(source, /const groups = new Map\(\)/);
  assert.match(source, /groups\.get\(key\)\.push\(row\)/);
  assert.match(source, /smart-filter-cloud-heading/);
  assert.match(source, /smart-filter-object-count/);
  assert.match(source, /smart-filter-reduction/);
  assert.match(source, /physicsFiltered/);
  assert.match(source, /aiFiltered/);
  assert.doesNotMatch(source, /Both keep/);
  assert.match(source, /setTimeout\(poll, 3000\)/);
  assert.match(source, /Smart Filter progress/);
  assert.match(source, /result\.status === "computing"/);
  assert.match(client, /payload\?\.status === "computing"/);
  assert.doesNotMatch(source, /Model confidence|Safety guard<|event_id\}<small>/);
  assert.doesNotMatch(source, /Review band/);
  assert.doesNotMatch(source, /filteredRate/);
  assert.match(client, /\/smart-filter`, \{ signal \}, \{ timeoutMs: 60_000, retries: 1 \}/);
});

test("visualization uses local hover details, typed colors, full-width matrix, and no Heat Map route", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const visualization = readFileSync(new URL("../src/components/UI/VisualizationPage.jsx", import.meta.url), "utf8");
  const field = readFileSync(new URL("../src/components/Scene/SatelliteField.jsx", import.meta.url), "utf8");
  const globe = readFileSync(new URL("../src/components/Scene/SmartFilterGlobe.jsx", import.meta.url), "utf8");
  assert.match(app, /import\("\.\/components\/UI\/VisualizationPage\.jsx"\)/);
  assert.match(visualization, /const \[hoveredObject, setHoveredObject\] = useState\(null\)/);
  assert.match(visualization, /onHoverObject=\{setHoveredObject\}/);
  assert.match(visualization, /globe-hover-tooltip/);
  assert.match(app, /Current Screening Proxy Matrix/);
  assert.match(app, /Orbital altitude \(km\)/);
  assert.match(app, /Primary-object speed magnitude \(km\/s\)/);
  assert.match(app, /activePage\) \|\| !snapshot/);
  assert.doesNotMatch(app, /Load charts/);
  assert.doesNotMatch(app, /label: "Heat Map"|navigate\("heatmap"\)|activePage === "heatmap"/);
  assert.match(field, /"#070a10"/);
  assert.match(field, /"#ffd166"/);
  assert.match(field, /"#8bd5ff"/);
  assert.match(globe, /"#ffffff"/);
  assert.match(globe, /"#8bd5ff"/);
});
const proxy = {
  id: "SP-proxy-1",
  primary: { id: "1", name: "Catalog Object 1", category: "active", band: "LEO", orbit_type: "LEO", altitude_km: 500, inclination_deg: 50, velocity_kms: 7.6 },
  secondary: { id: "2", name: "Catalog Object 2", category: "debris", band: "LEO", orbit_type: "LEO", altitude_km: 501, inclination_deg: 51, velocity_kms: 7.5 },
  pair_type: "SATELLITE vs DEBRIS",
  risk_level: "High",
  risk_score: 0.9,
  priority_score: 80,
  suggested_action: "Heuristic review only",
};
const physicalEvent = {
  id: "EV-physical-1",
  result_kind: "physics_assessment",
  physics_result: { status: "valid" },
  automatic_research_pc_assessment: { log10_pc: -6 },
  primary: proxy.primary,
  secondary: proxy.secondary,
  pair_type: proxy.pair_type,
  comparison_result: { status: "not_comparable" },
  ml_result: {
    status: "available",
    provenance: { source_physics_event_id: "EV-physical-1", live_feature_semantics_compatibility: "verified" },
    prediction: { predicted_log_risk: -7.2, predicted_risk_estimate: 6.3e-8, predicted_risk_probability: 6.3e-8, threshold_flag_at_minus_6: false, high_risk: false },
  },
};

function renderSmart(platform, physicalFilterResult = null) {
  return renderToStaticMarkup(React.createElement(SmartFilterPage, {
    snapshot: baseSnapshot,
    smartSnapshot: baseSnapshot,
    platform,
    physicalFilterResult,
  }));
}

test("Smart Filter shows physics-classifier metrics, event counts, safety guard, and decision reasons", () => {
  const markup = renderSmart({
    conjunctionStatus: { job_id: "0123456789abcdef0123456789abcdef" },
    conjunctions: [], screeningProxies: [], smart: {},
  }, {
    result_type: "physics_smart_filter", status: "available",
    model: { status: "available", model_name: "ORION Physics-Supervised Smart Filter Classifier", model_version: "1.0.0", dataset_scenario_count: 804, dataset_independent_parent_count: 67,
      split_counts: { train: { parent_event_count: 46, scenario_count: 552 }, validation: { parent_event_count: 10, scenario_count: 120 }, test: { parent_event_count: 11, scenario_count: 132 } }, metrics: { test: {
      recall_significant: 0.959, precision_significant: 1, false_negative_significant_count: 5,
      sample_count: 132, parent_event_count: 11, confusion_matrix_rows_true_columns_predicted: [[10, 0], [5, 117]],
      majority_class_baseline: { accuracy: 0.924 },
    } } },
    policy: { significant_pc_threshold: 1e-4, safety_miss_distance_threshold_km: 1, scenario_count: 12 },
    evaluation: { before_count: 2, kept_count: 1, filtered_count: 1, safety_guard_retained_count: 1 },
    decisions: [{ event_id: "A-B", object_ids: ["A", "B"], object_names: ["Alpha", "Beta"], miss_distance_km: 0.5,
      maximum_scenario_pc_scientific: "1.2e-4", decision: "retain", model_status: "available", model_prediction: "significant",
      confidence: 0.91, safety_guard_retained: true, safety_guard_reasons: ["SAFETY_GUARD_MISS_DISTANCE"],
      reason: "SAFETY_GUARD_MISS_DISTANCE" }],
  });
  assert.match(markup, /Physics-Supervised Conjunction Filter/);
  assert.match(markup, /Events before filter<strong>2/);
  assert.match(markup, /Events kept<strong>1/);
  assert.match(markup, /Events filtered<strong>1/);
  assert.match(markup, /false negatives 5/);
  assert.match(markup, /804 generated scenarios from 67 independent parent events/);
  assert.match(markup, /SAFETY_GUARD_MISS_DISTANCE/);
  assert.match(markup, /Download Decisions CSV/);
});

test("Smart Filter renders unavailable ML status without a blank page", () => {
  const markup = renderSmart({
    smart: { ml_model_status: { status: "unavailable", reason_code: "artifact_unavailable" } },
    conjunctions: [],
    screeningProxies: [],
  });
  assert.match(markup, /Smart Filter/);
  assert.match(markup, /No ML prediction is emitted/);
  assert.match(markup, /No physics-assessed event currently has an available ML estimate/);
});

test("globe hover metadata uses catalog values and marks missing values unavailable", () => {
  assert.deepEqual(catalogHoverDetails({ id: "25544", name: "ISS", object_type: "PAYLOAD", altitude_km: 420.5, inclination_deg: 51.6, velocity_kms: 7.66 }), {
    name: "ISS", catalogId: "25544", classification: "PAYLOAD", altitude: "420.5 km", inclination: "51.60°", speed: "7.660 km/s",
  });
  assert.deepEqual(catalogHoverDetails({ id: "x" }), {
    name: "Unnamed catalog object", catalogId: "x", classification: "Unavailable", altitude: "Unavailable", inclination: "Unavailable", speed: "Unavailable",
  });
});

test("Smart Filter renders the empty event state when the model exists but no events qualify", () => {
  const markup = renderSmart({
    smart: { ml_model_status: { status: "available", model_name: "ESA", model_version: "1" } },
    conjunctions: [],
    screeningProxies: [],
  });
  assert.match(markup, /predictions are limited to physical events with all nine features/);
  assert.match(markup, /No physics-assessed event currently has an available ML estimate/);
});

test("Smart Filter renders populated ML events separately from heuristic proxies", () => {
  const markup = renderSmart({
    smart: { ml_model_status: { status: "available", model_name: "ESA", model_version: "1" } },
    conjunctions: [physicalEvent],
    screeningProxies: [proxy],
  });
  assert.match(markup, /EV-physical-1/);
  assert.match(markup, /-7\.200 log10/);
  assert.match(markup, /exponentiated ESA risk estimate/i);
  assert.match(markup, /not a calibrated probability or Foster Pc/);
  assert.match(markup, /Historical ESA CDM and live TLE feature semantics are unverified; model outputs are withheld/);
  assert.doesNotMatch(markup, /0 of 51 high-risk labels/);
  assert.match(markup, /threshold flags are not validated alert rules/i);
  assert.match(markup, /Historical ESA CDM and live TLE feature semantics are unverified; model outputs are withheld/);
  assert.doesNotMatch(markup, /high-risk recall was poor|0\s*\/\s*55/);
  assert.match(markup, /SP-proxy-1/);
  assert.match(markup, /Heuristic-only proxy pairs/);
  assert.doesNotMatch(markup, /\bPc\s*[:=]\s*6\.3e-8/i);
});

test("Smart Filter withholds a legacy prediction when feature compatibility evidence is absent", () => {
  const oldPrediction = {
    ...physicalEvent,
    ml_result: {
      ...physicalEvent.ml_result,
      provenance: { source_physics_event_id: physicalEvent.id },
    },
  };
  const markup = renderSmart({
    smart: { ml_model_status: { status: "unavailable", artifact_status: "available", reason_code: "ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED" } },
    conjunctions: [oldPrediction],
  });
  assert.match(markup, /No ML prediction is emitted: ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED/);
  assert.match(markup, /Physics-only, ML unavailable<strong>1<\/strong>/);
  assert.match(markup, /ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED \(1\)/);
  assert.doesNotMatch(markup, /Predicted log10 risk|6\.3000e-8/);
});

test("Smart Filter treats null ML values as unavailable rather than zero risk", () => {
  const markup = renderSmart({
    smart: { ml_model_status: { status: "available", model_name: "ESA", model_version: "1" } },
    conjunctions: [{ ...physicalEvent, ml_result: { status: "available", prediction: { predicted_log_risk: null, predicted_risk_probability: null, high_risk: false } } }],
    screeningProxies: [],
  });
  assert.match(markup, /Physics-only, ML unavailable<strong>1<\/strong>/);
  assert.match(markup, /ML-supported physical events<strong>0<\/strong>/);
  assert.doesNotMatch(markup, /0\.000 log10|0\.000e\+0 exponentiated ESA risk estimate/);
});

test("Smart Filter preserves ESA inapplicability and never displays a stale prediction", () => {
  const markup = renderSmart({
    smart: { ml_model_status: { status: "available", model_name: "ESA", model_version: "1" } },
    conjunctions: [{ ...physicalEvent, ml_result: {
      status: "unavailable",
      reason_code: "ESA_INPUT_TIME_TO_TCA_BELOW_MINIMUM",
      prediction: { predicted_log_risk: -8, predicted_risk_estimate: 1e-8 },
    } }],
    screeningProxies: [],
  });
  assert.match(markup, /Physics-only, ML unavailable<strong>1<\/strong>/);
  assert.match(markup, /ESA_INPUT_TIME_TO_TCA_BELOW_MINIMUM/);
  assert.doesNotMatch(markup, /-8\.000 log10|1\.000e-8 exponentiated ESA risk estimate/);
});

test("ML prediction validation rejects malformed values and only accepts complete available output", () => {
  assert.equal(hasUsableEventPrediction(physicalEvent.ml_result), true);
  assert.deepEqual(usableEventPrediction(physicalEvent.ml_result), physicalEvent.ml_result.prediction);
  const missing = { status: "available", prediction: { predicted_log_risk: null, predicted_risk_probability: null, high_risk: false } };
  assert.equal(hasUsableEventPrediction(missing), false);
  assert.equal(usableEventPrediction(missing), null);
  const zeroDisplay = { status: "available", prediction: { predicted_log_risk: -7, predicted_risk_probability: 0, high_risk: false } };
  assert.equal(hasUsableEventPrediction(zeroDisplay), false);
  assert.equal(usableEventPrediction(zeroDisplay), null);
  assert.equal(hasUsableEventPrediction({ status: "available", prediction: { predicted_log_risk: 0.1, predicted_risk_probability: 0.7, high_risk: true } }), false);
  assert.equal(hasUsableEventPrediction({ status: "unavailable", prediction: physicalEvent.ml_result.prediction }), false);
});

test("event-scoped ML predictions require matching physical-event provenance", () => {
  assert.equal(hasUsableEventPrediction(physicalEvent.ml_result, physicalEvent.id), true);
  assert.equal(hasUsableEventPrediction(physicalEvent.ml_result, "EV-other"), false);
  assert.equal(usableEventPrediction(physicalEvent.ml_result, "EV-other"), null);
});

test("ML response accepts legacy fields but prefers canonical event-risk and threshold fields", () => {
  const legacy = { status: "available", prediction: {
    predicted_log_risk: -7,
    predicted_risk_probability: 1e-7,
    high_risk: false,
  } };
  assert.equal(hasUsableEventPrediction(legacy), true);
  assert.equal(predictedEventRiskEstimate(legacy.prediction), 1e-7);
  assert.equal(thresholdFlagAtMinus6(legacy.prediction), false);

  const canonical = { status: "available", prediction: {
    predicted_log_risk: -5,
    predicted_risk_estimate: 1e-5,
    predicted_risk_probability: 1e-7,
    threshold_flag_at_minus_6: true,
    high_risk: false,
  } };
  assert.equal(hasUsableEventPrediction(canonical), true);
  assert.equal(predictedEventRiskEstimate(canonical.prediction), 1e-5);
  assert.equal(thresholdFlagAtMinus6(canonical.prediction), true);
});

test("heuristic proxy scores with attached prediction-shaped data never enter ESA event ranking", () => {
  const proxyWithPredictionShape = { ...proxy, ml_result: physicalEvent.ml_result };
  const markup = renderSmart({
    smart: { ml_model_status: { status: "available", model_name: "ESA", model_version: "1" } },
    conjunctions: [],
    screeningProxies: [proxyWithPredictionShape],
  });
  assert.match(markup, /Heuristic-only proxy pairs/);
  assert.match(markup, /SP-proxy-1/);
  assert.doesNotMatch(markup, /-7\.200 log10/);
  assert.match(markup, /No physics-assessed event currently has an available ML estimate/);
});

test("maneuver selection only accepts completed physical events and exposes unavailable empty state", () => {
  assert.deepEqual(eligibleManeuverEvents([]), []);
  assert.equal(maneuverPageState(null, []).status, "no_eligible_event");
  assert.deepEqual(eligibleManeuverEvents([proxy, physicalEvent]), [physicalEvent]);
  assert.equal(selectManeuverEvent([proxy, physicalEvent], "SP-proxy-1"), null);
  assert.equal(selectManeuverEvent([proxy, physicalEvent], "EV-physical-1"), physicalEvent);
  assert.equal(maneuverPageState(physicalEvent, [proxy, physicalEvent]).status, "selected_event_unavailable_dynamics");
});

test("Smart Filter view applies heuristic predicates and keeps unresolved records inconclusive", () => {
  const object = (id, forecast, risk) => ({ id, name: `Object ${id}`, category: "debris", provenance: { validity_status: "valid" }, heuristic_forecast_score: forecast, heuristic_risk_score: risk });
  const objects = [
    object("critical-pair", 0.1, 0.1), object("high-pair", 0.1, 0.1), object("medium-pair", 0.1, 0.1),
    object("low-pair", 0.1, 0.1), object("forecast", 0.721, 0.1), object("heuristic", 0.1, 0.681),
    object("thresholds", 0.72, 0.68), object("excluded", 0.2, 0.3),
  ];
  const pair = (risk_level, id) => ({ risk_level, primary: { id }, secondary: { id: `${id}-secondary` } });
  const proxies = [pair("Critical", "critical-pair"), pair("High", "high-pair"), pair("Medium", "medium-pair"), pair("Low", "low-pair")];
  const snapshot = { objects, source_state: { status: "live" }, risk_cells: [{ heuristic_risk_score: 0.49 }, { heuristic_risk_score: 0.48 }], stats: { tracked_objects: objects.length } };
  const view = buildSmartFilterView(snapshot, proxies);

  assert.deepEqual(view.objects.map((item) => item.id), ["critical-pair", "high-pair", "medium-pair", "forecast", "heuristic"]);
  assert.equal(smartFilterRecordIdentity(objects[4], objects), "catalog:forecast");
  assert.equal(view.stats.tracked_objects, 5);
  assert.equal(view.risk_cells.length, 1);
  assert.match(smartFilterObjectReasons(objects[0], proxies, objects).join(";"), /PROXY_PAIR_REVIEW_BAND/);
  assert.match(smartFilterObjectReasons(objects[4], proxies, objects).join(";"), /HEURISTIC_FORECAST_GT_0_72/);
  assert.match(smartFilterObjectReasons(objects[5], proxies, objects).join(";"), /HEURISTIC_RISK_GT_0_68/);
  assert.deepEqual(smartFilterObjectReasons(objects[6], proxies), []);
  assert.deepEqual(smartFilterObjectReasons(objects[7], proxies, objects), []);
});

test("duplicate catalog IDs use per-record identity for explanations and retained labels", () => {
  const duplicateRecords = [
    { id: "DUP-1", name: "Record A", category: "debris", provenance: { validity_status: "valid", input_hash: "record-hash-a", element_epoch: "26001.1" }, heuristic_forecast_score: 0.2, heuristic_risk_score: 0.2 },
    { id: "DUP-1", name: "Record B", category: "debris", provenance: { validity_status: "valid", input_hash: "record-hash-b", element_epoch: "26001.2" }, heuristic_forecast_score: 0.2, heuristic_risk_score: 0.2 },
  ];
  const proxies = [{
    id: "SP-DUPLICATE-IDENTITY",
    risk_level: "High",
    primary: { id: "DUP-1", provenance: { input_hash: "record-hash-a" } },
    secondary: { id: "OTHER", provenance: { input_hash: "other-hash" } },
  }];
  const snapshot = { ...baseSnapshot, objects: duplicateRecords };
  const smartSnapshot = buildSmartFilterView(snapshot, proxies);
  const markup = renderToStaticMarkup(React.createElement(SmartFilterPage, {
    snapshot,
    smartSnapshot,
    platform: { screeningProxies: proxies, conjunctions: [] },
  }));

  assert.deepEqual(smartSnapshot.objects.map((object) => object.name), ["Record A"]);
  assert.match(smartFilterObjectReasons(duplicateRecords[0], proxies, duplicateRecords).join(";"), /PROXY_PAIR_REVIEW_BAND/);
  assert.deepEqual(smartFilterObjectReasons(duplicateRecords[1], proxies, duplicateRecords), []);
  assert.equal((markup.match(/in review view/g) || []).length, 1);
  assert.equal((markup.match(/not selected/g) || []).length, 1);
  assert.equal((markup.match(/Record [AB] · DUP-1/g) || []).length, 2);
});

test("duplicate records without stable provenance are labeled ambiguous", () => {
  const objects = [
    { id: "DUP-2", name: "Record A", provenance: { element_epoch: "26001.1" }, heuristic_forecast_score: 0.2, heuristic_risk_score: 0.2 },
    { id: "DUP-2", name: "Record B", provenance: { element_epoch: "26001.2" }, heuristic_forecast_score: 0.2, heuristic_risk_score: 0.2 },
  ];
  const markup = renderToStaticMarkup(React.createElement(SmartFilterPage, {
    snapshot: { ...baseSnapshot, objects },
    smartSnapshot: buildSmartFilterView({ ...baseSnapshot, objects }, []),
    platform: { screeningProxies: [], conjunctions: [] },
  }));

  assert.equal(smartFilterRecordIdentity(objects[0], objects), null);
  assert.equal((markup.match(/inconclusive · identity ambiguous; kept in review view/g) || []).length, 2);
  assert.doesNotMatch(markup, /exclude · not selected/);
});

test("physical events remain individually available for review when AI inference is unavailable", () => {
  const unavailableEvent = {
    ...physicalEvent,
    id: "EV-unavailable-1",
    ml_result: { status: "unavailable", reason_code: "ESA_INPUT_FEATURES_INCOMPLETE" },
  };
  const markup = renderSmart({ smart: {}, conjunctions: [unavailableEvent], screeningProxies: [] });
  assert.match(markup, /Physical Events for Review/);
  assert.match(markup, /EV-unavailable-1/);
  assert.match(markup, /ESA_INPUT_FEATURES_INCOMPLETE/);
  assert.match(markup, /retain for review/);
  assert.match(markup, /risk-badge review/);
  assert.doesNotMatch(markup, /risk-badge low/);
});

test("Smart Filter renders backend deterministic AI score and final priority for physical events", () => {
  const event = {
    ...physicalEvent,
    ai_risk_assessment: {
      score: 0.731, category: "High", final_priority_rank: 2, geometry_rank: 1,
      foster_pc_rank: null, research_pc_rank: 1,
      model_name: "ORION deterministic live-geometry risk prioritizer",
    },
  };
  const markup = renderSmart({ conjunctions: [event], screeningProxies: [] });
  assert.match(markup, /Live Event Queue · Deterministic AI Fallback/);
  assert.match(markup, /High[\s\S]{0,20}73\.1 \/ 100/);
  assert.match(markup, /Final priority #2/);
  assert.match(markup, /research Pc #1/);
  assert.match(markup, /not Pc/);
});
