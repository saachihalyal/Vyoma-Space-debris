import test from "node:test";
import assert from "node:assert/strict";
import { getPairType } from "../src/utils/identityModel.js";
import { COLLISION_INVALID_ASSESSMENT_LABEL, COLLISION_PAIR_FILTERS, collisionEventPriority, filterCollisionEvents, getCollisionEventsForDisplay, matchesCollisionPairFilter, matchesReviewPriorityFilter, rankCollisionEvents, rankOrbitalAnomalyEvents, screeningAssessmentCounts, searchAndSortCollisionEvents } from "../src/utils/collisionEventDisplay.js";

const object = (id, object_type) => ({ id, object_type });

test("Collision Analysis pair labels match canonical screening labels for required metadata pairs", () => {
  const cases = [
    ["satellite-debris", "SATELLITE vs DEBRIS", "ACTIVE SATELLITE", "SPACE DEBRIS"],
    ["satellite-rocket", "SATELLITE vs ROCKET BODY", "ACTIVE SATELLITE", "ROCKET BODY"],
    ["satellite-satellite", "SATELLITE vs SATELLITE", "ACTIVE SATELLITE", "ACTIVE SATELLITE"],
    ["satellite-unknown", "SATELLITE vs UNKNOWN", "ACTIVE SATELLITE", undefined],
    ["debris-rocket", "DEBRIS vs ROCKET BODY", "SPACE DEBRIS", "ROCKET BODY"],
  ];
  for (const [name, expected, first, second] of cases) {
    const event = { primary: object(`${name}-a`, first), secondary: object(`${name}-b`, second) };
    assert.equal(getPairType(event.primary, event.secondary), expected, name);
    assert.ok(COLLISION_PAIR_FILTERS.some((option) => option.value === expected), `${name} must have a selectable filter`);
    assert.equal(matchesCollisionPairFilter(event, expected), true, `${name} must pass its matching UI filter`);
    assert.equal(matchesCollisionPairFilter(event, "all"), true, `${name} must pass the all-pairs filter`);
    assert.equal(matchesCollisionPairFilter(event, "SATELLITE vs SATELLITE"), expected === "SATELLITE vs SATELLITE", `${name} must not pass a different type filter`);
  }
});

test("Collision Analysis trusts canonical pair metadata returned by screening", () => {
  const event = { pair_type: "DEBRIS vs ROCKET BODY", primary: object("a", "SPACE DEBRIS"), secondary: object("b", "ROCKET BODY") };
  assert.equal(matchesCollisionPairFilter(event, "DEBRIS vs ROCKET BODY"), true);
  assert.equal(matchesCollisionPairFilter(event, "ROCKET BODY vs DEBRIS"), false);
});

test("Collision Analysis displays all returned events instead of silently truncating at 100", () => {
  const events = Array.from({ length: 121 }, (_, index) => ({ id: `event-${index + 1}` }));
  assert.equal(getCollisionEventsForDisplay(events).length, 121);
  assert.equal(getCollisionEventsForDisplay(events).at(-1).id, "event-121");
  assert.deepEqual(getCollisionEventsForDisplay(null), []);
});

test("Collision Analysis All statuses keeps invalid screening rows visible instead of hiding them by default", () => {
  const events = Array.from({ length: 22 }, (_, index) => ({
    id: `event-${index + 1}`,
    result_kind: "physics_assessment",
    physics_result: { status: index < 10 ? "valid" : "invalid" },
  }));
  assert.equal(filterCollisionEvents(events).length, 22);
  assert.equal(filterCollisionEvents(events, { statusFilter: "valid" }).length, 10);
  assert.equal(filterCollisionEvents(events, { statusFilter: "invalid" }).length, 12);
  assert.equal(filterCollisionEvents(events).at(-1).id, "event-22");
  assert.equal(rankCollisionEvents(events).length, 10);
});

test("Collision Analysis summary does not claim returned invalid assessments were excluded", () => {
  assert.match(COLLISION_INVALID_ASSESSMENT_LABEL, /full screening result/);
  assert.match(COLLISION_INVALID_ASSESSMENT_LABEL, /not qualifying close approaches/);
  assert.doesNotMatch(COLLISION_INVALID_ASSESSMENT_LABEL, /excluded/i);
});

test("Collision Analysis distinguishes full screening counts from response-limited rows", () => {
  const counts = screeningAssessmentCounts({
    assessment_record_count: 196,
    returned_assessment_record_count: 120,
    assessment_records_truncated: true,
    assessment_response_limit_reached: true,
    invalid_assessment_count: 4,
  }, 120, 0);
  assert.deepEqual(counts, {
    total: 196,
    returned: 120,
    invalidTotal: 4,
    returnedInvalid: 0,
    truncated: true,
  });
});

test("Collision Analysis falls back to the event list when full-run counts are unavailable", () => {
  assert.deepEqual(screeningAssessmentCounts({}, 25, 3), {
    total: 25,
    returned: 25,
    invalidTotal: null,
    returnedInvalid: 3,
    truncated: false,
  });
});

test("Collision Analysis searches catalog identity and sorts by TCA or miss distance with unavailable values last", () => {
  const events = [
    { id: "later", primary: { id: "25544", name: "ISS", object_type: "ACTIVE SATELLITE" }, physics_result: { tca: { status: "available", value: "2026-01-02T00:00:00Z" }, miss_distance: { status: "available", value: 2 } } },
    { id: "earlier", primary: { id: "36086", name: "POISK", object_type: "ACTIVE SATELLITE" }, physics_result: { tca: { status: "available", value: "2026-01-01T00:00:00Z" }, miss_distance: { status: "available", value: 8 } } },
    { id: "unknown", secondary: { name: "Debris object" }, physics_result: { tca: { status: "unavailable" }, miss_distance: { status: "unavailable" } } },
  ];
  assert.deepEqual(searchAndSortCollisionEvents(events, "poisk").map((event) => event.id), ["earlier"]);
  assert.deepEqual(searchAndSortCollisionEvents(events, "debris").map((event) => event.id), ["unknown"]);
  assert.deepEqual(searchAndSortCollisionEvents(events, "", "tca_soonest").map((event) => event.id), ["earlier", "later", "unknown"]);
  assert.deepEqual(searchAndSortCollisionEvents(events, "", "miss_nearest").map((event) => event.id), ["later", "earlier", "unknown"]);
});

test("Collision Analysis review-priority filters keep proxy ranks separate from physical classifications", () => {
  const high = { result_kind: "physics_assessment", review_priority: { category: "HIGH" } };
  const proxy = { result_kind: "screening_proxy", risk_level: "High" };
  assert.equal(matchesReviewPriorityFilter(high, "HIGH"), true);
  assert.equal(matchesReviewPriorityFilter(high, "LOW"), false);
  assert.equal(matchesReviewPriorityFilter({ result_kind: "physics_assessment" }, "UNCLASSIFIED"), true);
  assert.equal(matchesReviewPriorityFilter(proxy, "HIGH"), false);
  assert.equal(matchesReviewPriorityFilter(proxy, "all"), true);
});

test("evidence priority uses event-matched computed Pc before source values and geometry", () => {
  const computedLow = { id: "computed-low", collision_probability: { status: "available", event_id: "computed-low", pc: 1e-6 } };
  const computedHigh = { id: "computed-high", collision_probability: { status: "available", event_id: "computed-high", pc: 1e-4 } };
  const reported = { id: "reported", source_reported_pc: 1e-3, source_reported_event_id: "reported" };
  const geometryHigh = { id: "geometry", review_priority: { status: "classified", category: "HIGH", explanation: "miss ratio" } };
  const orphaned = { id: "orphaned", collision_probability: { status: "available", event_id: "other-event", pc: 0.5 }, review_priority: { status: "classified", category: "LOW" } };
  const events = [geometryHigh, computedLow, orphaned, reported, computedHigh];
  assert.deepEqual(rankCollisionEvents(events).map((event) => event.id), ["computed-high", "computed-low", "reported", "geometry", "orphaned"]);
  assert.deepEqual(searchAndSortCollisionEvents(events, "", "evidence_priority").map((event) => event.id), ["computed-high", "computed-low", "reported", "geometry", "orphaned"]);
  assert.equal(collisionEventPriority(orphaned).label, "Geometry review priority");
  assert.match(collisionEventPriority(orphaned).basis, /geometry-only/);
});

test("geometry review ranking orders events within a band by normalized miss distance", () => {
  const farther = {
    id: "A-farther",
    review_priority: { status: "classified", category: "HIGH", criteria: { miss_distance_fraction: 0.19 } },
  };
  const nearer = {
    id: "Z-nearer",
    review_priority: { status: "classified", category: "HIGH", criteria: { miss_distance_fraction: 0.07 } },
  };
  assert.deepEqual(rankCollisionEvents([farther, nearer]).map((event) => event.id), ["Z-nearer", "A-farther"]);
  assert.deepEqual(searchAndSortCollisionEvents([farther, nearer], "", "evidence_priority").map((event) => event.id), ["Z-nearer", "A-farther"]);
});

test("geometry rank remains available without Pc and ignores scenario and historical ML scores", () => {
  const events = [
    { id: "B-medium", collision_probability: { status: "unavailable", pc: null }, scenario_collision_probability: { status: "available", pc: 0.9 }, ml_result: { status: "available", prediction: { predicted_log_risk: 0 } }, review_priority: { status: "classified", category: "MEDIUM", criteria: { miss_distance_fraction: 0.4 } } },
    { id: "A-high", collision_probability: { status: "unavailable", pc: null }, scenario_collision_probability: { status: "available", pc: 1e-20 }, ml_result: { status: "available", prediction: { predicted_log_risk: -30 } }, review_priority: { status: "classified", category: "HIGH", criteria: { miss_distance_fraction: 0.1 } } },
  ];
  const expected = ["A-high", "B-medium"];
  assert.deepEqual(rankCollisionEvents(events).map((event) => event.id), expected);
  assert.deepEqual(rankCollisionEvents(events).map((event) => event.id), expected);
  assert.deepEqual(searchAndSortCollisionEvents(events, "", "evidence_priority").map((event) => event.id), expected);
});

test("invalid duplicate propagator assessments never receive a risk rank", () => {
  const events = [
    { id: "valid", result_kind: "physics_assessment", review_priority: { status: "classified", category: "HIGH", criteria: { miss_distance_fraction: 0.1 } } },
    { id: "duplicate", result_kind: "physics_assessment", physics_result: { status: "invalid", reason_codes: ["identical_propagation_parameters_for_distinct_catalog_ids"] }, review_priority: { category: "REVIEW_REQUIRED" } },
  ];
  assert.deepEqual(rankCollisionEvents(events).map((event) => event.id), ["valid"]);
});

test("AI feature-screen ranking is deterministic, event-bound, and separate from collision priority", () => {
  const makeEvent = (id, score) => ({
    id, result_kind: "physics_assessment", physics_result: { status: "valid" },
    anomaly_result: { status: "available", anomaly_score: score, model_name: "IForest", model_version: "1", provenance: { source_physics_event_id: id } },
  });
  const events = [makeEvent("B", 0.8), makeEvent("A", 0.8), makeEvent("C", 0.2),
    { ...makeEvent("orphan", 1), anomaly_result: { ...makeEvent("orphan", 1).anomaly_result, provenance: { source_physics_event_id: "other" } } },
    { ...makeEvent("invalid", 1), physics_result: { status: "invalid" } }];
  const ranks = rankOrbitalAnomalyEvents(events);
  assert.deepEqual([...ranks.keys()], ["A", "B", "C"]);
  assert.deepEqual([ranks.get("A").rank, ranks.get("B").rank, ranks.get("C").rank], [1, 2, 3]);
  assert.equal(ranks.get("A").count, 3);
  assert.equal(ranks.get("A").score, 0.8);
  assert.equal(collisionEventPriority(events[0]).label, "Unclassified");
});
