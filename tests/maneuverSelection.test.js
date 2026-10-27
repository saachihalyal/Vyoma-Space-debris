import test from "node:test";
import assert from "node:assert/strict";
import { defaultManeuverEvent, eligibleManeuverEvents, isCurrentManeuverRequest, maneuverAssessmentForSelection, maneuverPageState, resolveManeuverEvent, selectManeuverEvent } from "../src/utils/maneuverSelection.js";

const physical = { id: "EV-1", result_kind: "physics_assessment", physics_result: { status: "valid" }, automatic_research_pc_assessment: { log10_pc: -6 } };
const invalidPhysical = { id: "EV-invalid", result_kind: "physics_assessment", physics_result: { status: "invalid" } };
const proxy = { id: "SP-1", result_kind: "screening_proxy" };

test("an explicitly selected proxy cannot fall through to an unrelated physical event", () => {
  assert.equal(resolveManeuverEvent(proxy, [physical]), null);
  assert.equal(resolveManeuverEvent(null, [physical]), physical);
  assert.equal(resolveManeuverEvent(invalidPhysical, [invalidPhysical]), invalidPhysical);
  assert.equal(selectManeuverEvent([invalidPhysical], invalidPhysical.id), invalidPhysical);
  assert.equal(resolveManeuverEvent(physical, [physical]), physical);
});

test("unselected maneuver event defaults to the highest exact research Pc", () => {
  const events = [
    { id: "lower", result_kind: "physics_assessment", physics_result: { status: "valid" }, automatic_research_pc_assessment: { log10_pc: -9 } },
    { id: "higher", result_kind: "physics_assessment", physics_result: { status: "valid" }, automatic_research_pc_assessment: { log10_pc: -6 } },
  ];
  assert.equal(defaultManeuverEvent(events).id, "higher");
  assert.equal(resolveManeuverEvent(null, events).id, "higher");
});

test("maneuver selection never defaults below 1e-30 and permits the exact floor", () => {
  const belowFloor = [
    { id: "lower", result_kind: "physics_assessment", physics_result: { status: "valid" }, automatic_research_pc_assessment: { log10_pc: -31 } },
    { id: "lower-still", result_kind: "physics_assessment", physics_result: { status: "valid" }, automatic_research_pc_assessment: { log10_pc: -42 } },
  ];
  assert.equal(defaultManeuverEvent(belowFloor), null);
  assert.equal(resolveManeuverEvent(null, belowFloor), null);
  const atFloor = { ...belowFloor[0], automatic_research_pc_assessment: { log10_pc: -30 } };
  assert.equal(defaultManeuverEvent([belowFloor[1], atFloor]), atFloor);
});

test("missing, malformed, and duplicate physical IDs are unavailable for maneuver selection", () => {
  const duplicateA = { ...physical, physics_result: { status: "valid" } };
  const duplicateB = { ...physical, physics_result: { status: "valid" }, attachedData: "duplicate" };
  const missingId = { result_kind: "physics_assessment", physics_result: { status: "valid" } };
  const malformedId = { ...missingId, id: "  " };

  assert.deepEqual(eligibleManeuverEvents([duplicateA, duplicateB, missingId, malformedId]), []);
  assert.equal(selectManeuverEvent([duplicateA, duplicateB], physical.id), null);
  assert.equal(resolveManeuverEvent(duplicateA, [duplicateA, duplicateB]), null);
});

test("valid empty screening explains why event-specific maneuver assessment is unavailable", () => {
  const state = maneuverPageState(null, [], { result_status: "valid_empty" });
  assert.equal(state.status, "no_eligible_event");
  assert.equal(state.empty_title, "No qualifying physical conjunction available");
  assert.match(state.empty_text, /accepted Stage 2A run completed with zero qualifying close approaches/);
  assert.match(state.empty_text, /heuristic proxy pairs cannot be used/);
});

test("invalid physical event remains reviewable with exact reason and is excluded from valid set", () => {
  const invalid = { ...invalidPhysical, physics_result: { status: "invalid", reason_codes: ["identical_propagation_parameters_for_distinct_catalog_ids"] } };
  const state = maneuverPageState(invalid, [invalid]);
  assert.equal(state.selected_event, invalid);
  assert.deepEqual(state.eligible_events, []);
  assert.deepEqual(state.invalid_reason_codes, ["identical_propagation_parameters_for_distinct_catalog_ids"]);
  assert.equal(state.status, "selected_invalid_event");
});

test("maneuver assessment is visible only for its matching physical event and screening job", () => {
  const assessment = {
    screening_job_id: "job-A",
    event_id: "EV-1",
    result: { status: "available_with_warning", event_id: "EV-1", candidates: [{ direction: "R", maneuver_ml_rank: 1, maneuver_ml_predicted_miss_distance_km: 0.5 }], ml_result: { status: "available", provenance: { source_event_id: "EV-1", screening_job_id: "job-A" } } },
  };
  assert.deepEqual(maneuverAssessmentForSelection(assessment, "job-A", physical), assessment.result);
  assert.equal(maneuverAssessmentForSelection(assessment, "job-B", physical), null);
  assert.equal(maneuverAssessmentForSelection(assessment, "job-A", { ...physical, id: "EV-2" }), null);
  assert.equal(maneuverAssessmentForSelection(assessment, "job-B", physical), null);
  assert.equal(maneuverAssessmentForSelection(assessment, "job-A", proxy), null);
});

test("changing selection immediately hides the previous assessment", () => {
  const assessment = { screening_job_id: "job-A", event_id: "EV-1", result: { status: "available" } };
  assert.equal(maneuverAssessmentForSelection(assessment, "job-A", { ...physical, id: "EV-2" }), null);
  assert.equal(maneuverAssessmentForSelection(assessment, "job-A", null), null);
});

test("late responses from an older event or repeated same-event request cannot replace the latest", async () => {
  let activeGeneration = 0;
  let visible = null;
  let resolveA;
  let resolveB;
  const eventA = new Promise((resolve) => { resolveA = resolve; });
  const eventB = new Promise((resolve) => { resolveB = resolve; });
  const apply = async (identity, promise, generation) => {
    const result = await promise;
    if (isCurrentManeuverRequest(generation, activeGeneration)) visible = { ...identity, result };
  };
  const generationA = ++activeGeneration;
  const pendingA = apply({ screening_job_id: "job-A", event_id: "EV-1" }, eventA, generationA);
  const generationB = ++activeGeneration;
  const pendingB = apply({ screening_job_id: "job-A", event_id: "EV-2" }, eventB, generationB);
  resolveB({ status: "available", event_id: "EV-2" });
  await pendingB;
  resolveA({ status: "available", event_id: "EV-1" });
  await pendingA;
  assert.equal(visible.event_id, "EV-2");

  let resolveOld;
  let resolveLatest;
  const oldRequest = new Promise((resolve) => { resolveOld = resolve; });
  const latestRequest = new Promise((resolve) => { resolveLatest = resolve; });
  const sameSelection = { screening_job_id: "job-A", event_id: "EV-1" };
  const oldGeneration = ++activeGeneration;
  const oldPending = apply(sameSelection, oldRequest, oldGeneration);
  const latestGeneration = ++activeGeneration;
  const latestPending = apply(sameSelection, latestRequest, latestGeneration);
  resolveLatest({ status: "available_with_warning", marker: "latest" });
  await latestPending;
  resolveOld({ status: "available_with_warning", marker: "older" });
  await oldPending;
  assert.equal(visible.result.marker, "latest");
});

test("clearing selection or aborting a request prevents a pending response from applying", async () => {
  let activeGeneration = 0;
  let visible = null;
  let resolve;
  const pendingResult = new Promise((done) => { resolve = done; });
  const requestGeneration = ++activeGeneration;
  const pending = pendingResult.then((result) => {
    if (isCurrentManeuverRequest(requestGeneration, activeGeneration)) visible = result;
  });
  ++activeGeneration; // Selection cleared; invalidate the pending request.
  resolve({ status: "available", event_id: "EV-1" });
  await pending;
  assert.equal(visible, null);
  assert.equal(isCurrentManeuverRequest(requestGeneration, activeGeneration, true), false);
});
