import test from "node:test";
import assert from "node:assert/strict";
import {
  buildSmartFilterView,
  smartFilterObjectReasons,
  smartFilterRecordIdentity,
} from "../src/utils/smartFilterView.js";

// This hand-authored dataset is synthetic and measures software-rule
// conformance only. It is not collision-risk ground truth or an operational
// workload benchmark.
function fixtureObject(id, forecast, risk, inputHash = `hash-${id}`) {
  return {
    id,
    name: id,
    category: "debris",
  provenance: { catalog_id: id, input_hash: inputHash, validity_status: "valid" },
    heuristic_forecast_score: forecast,
    heuristic_risk_score: risk,
  };
}

function proxy(riskLevel, object) {
  return {
    id: `SP-${riskLevel}-${object.name}`,
    risk_level: riskLevel,
    primary: object,
    secondary: { id: `OTHER-${object.name}`, provenance: { input_hash: `other-${object.name}` } },
  };
}

const forecastAbove = fixtureObject("forecast-above", 0.720001, 0.2);
const forecastAt = fixtureObject("forecast-at", 0.72, 0.2);
const forecastBelow = fixtureObject("forecast-below", 0.719999, 0.2);
const riskAbove = fixtureObject("risk-above", 0.2, 0.680001);
const riskAt = fixtureObject("risk-at", 0.2, 0.68);
const riskBelow = fixtureObject("risk-below", 0.2, 0.679999);
const criticalOnly = fixtureObject("critical-only", 0.2, 0.2);
const highOnly = fixtureObject("high-only", 0.2, 0.2);
const mediumOnly = fixtureObject("medium-only", 0.2, 0.2);
const lowOnly = fixtureObject("low-only", 0.2, 0.2);
const safeOnly = fixtureObject("safe-only", 0.2, 0.2);
const duplicateSelected = fixtureObject("DUP-1", 0.2, 0.2, "duplicate-record-a");
const duplicateNotSelected = fixtureObject("DUP-1", 0.2, 0.2, "duplicate-record-b");
const ambiguousA = fixtureObject("DUP-2", 0.2, 0.2, "same-hash");
const ambiguousB = fixtureObject("DUP-2", 0.2, 0.2, "same-hash");
const missingScores = { id: "missing", name: "missing", category: "debris", provenance: { input_hash: "missing", validity_status: "valid" } };
const nullScores = fixtureObject("null-scores", null, null);
const infiniteScore = fixtureObject("infinite-score", 0.2, Number.POSITIVE_INFINITY);
const nanScore = fixtureObject("nan-score", Number.NaN, 0.2);

const catalog = [
  forecastAbove, forecastAt, forecastBelow, riskAbove, riskAt, riskBelow,
  criticalOnly, highOnly, mediumOnly, lowOnly, safeOnly,
  duplicateSelected, duplicateNotSelected, ambiguousA, ambiguousB,
  missingScores, nullScores, infiniteScore, nanScore,
];
const proxies = [
  proxy("Critical", criticalOnly),
  proxy("High", highOnly),
  proxy("Medium", mediumOnly),
  proxy("Low", lowOnly),
  proxy("Safe", safeOnly),
  proxy("Critical", duplicateSelected),
  proxy("High", ambiguousA),
  proxy("Critical", criticalOnly), // repeated pair must not change membership
];

function identities(objects, records) {
  return objects.map((object) => smartFilterRecordIdentity(object, records)).filter(Boolean).sort();
}

function fraction(count, total) {
  return `${count}/${total} (${(count / total).toFixed(4)})`;
}

test("synthetic Smart Filter evaluation compares all, threshold-only, and current selection", (t) => {
  const allObjects = [...catalog];
  const thresholdOnly = catalog.filter((object) => smartFilterObjectReasons(object, [], catalog).length > 0);
  const current = buildSmartFilterView({ objects: catalog, risk_cells: [], stats: { tracked_objects: catalog.length } }, proxies).objects;

  const thresholdIds = identities(thresholdOnly, catalog);
  const currentIds = identities(current, catalog);
  const proxyIncrement = currentIds.filter((identity) => !thresholdIds.includes(identity));
  const withoutRepeatedProxy = buildSmartFilterView(
    { objects: catalog, risk_cells: [], stats: {} },
    proxies.slice(0, -1),
  ).objects;

  assert.equal(catalog.length, 19);
  assert.equal(allObjects.length, 19);
  assert.equal(thresholdOnly.length, 4); // two threshold matches plus two ambiguous records held for review
  assert.equal(current.length, 8);
  assert.deepEqual(thresholdOnly.map((object) => object.id).sort(), ["DUP-2", "DUP-2", "forecast-above", "risk-above"]);
  assert.deepEqual(current.map((object) => object.name).sort(), [
    "DUP-1", "DUP-2", "DUP-2", "critical-only", "forecast-above", "high-only", "medium-only", "risk-above",
  ]);
  assert.deepEqual(identities(withoutRepeatedProxy, catalog), currentIds);
  assert.equal(proxyIncrement.length, 4);
  assert.equal(current.includes(duplicateSelected), true);
  assert.equal(current.includes(duplicateNotSelected), false); // stable per-record identity is uniquely resolved
  assert.equal(current.includes(ambiguousA), true);
  assert.equal(current.includes(ambiguousB), true);
  assert.equal(smartFilterRecordIdentity(ambiguousA, catalog), null);

  t.diagnostic(`Synthetic selection-contract counts; no physical risk labels: all objects ${fraction(allObjects.length, catalog.length)}; threshold-only ${fraction(thresholdOnly.length, catalog.length)}; current Smart Filter ${fraction(current.length, catalog.length)}; incremental selections associated with proxy membership ${proxyIncrement.length}.`);
});

test("synthetic selection is stable under equivalent catalog/proxy input orderings", () => {
  const forward = buildSmartFilterView({ objects: catalog, risk_cells: [], stats: {} }, proxies).objects;
  const reversed = buildSmartFilterView({ objects: [...catalog].reverse(), risk_cells: [], stats: {} }, [...proxies].reverse()).objects;

  assert.deepEqual(identities(forward, catalog), identities(reversed, catalog));
  assert.deepEqual(identities(forward, catalog), identities(forward, catalog));

  // Exact-boundary and non-finite/missing values do not pass numeric rules.
  for (const object of [forecastAt, forecastBelow, riskAt, riskBelow, nullScores, infiniteScore, nanScore]) {
    assert.equal(smartFilterObjectReasons(object, [], catalog).length, 0, object.name || object.id);
  }
  for (const object of [lowOnly, safeOnly]) {
    assert.equal(smartFilterObjectReasons(object, proxies, catalog).length, 0, object.name || object.id);
  }
});

test("unknown class, stale catalog, and invalid provenance stay inconclusive in review", () => {
  const objects = [
    fixtureObject("unknown-class", 0.1, 0.1),
    fixtureObject("stale", 0.1, 0.1),
    fixtureObject("invalid", 0.1, 0.1),
  ];
  objects[0].category = "unknown";
  objects[2].provenance.validity_status = "invalid";
  const view = buildSmartFilterView({ objects, risk_cells: [], source_state: { status: "stale" }, stats: {} }, []);
  assert.deepEqual(view.objects, objects);
  assert.equal(smartFilterObjectReasons(objects[0], [], objects, "live").some((reason) => reason.includes("UNKNOWN_CLASS_REVIEW")), true);
  assert.equal(smartFilterObjectReasons(objects[2], [], objects, "live").some((reason) => reason.includes("INVALID_OR_MISSING_PROVENANCE_REVIEW")), true);
  assert.equal(smartFilterObjectReasons(objects[1], [], objects, "stale").some((reason) => reason.includes("STALE_CATALOG_REVIEW")), true);
});
