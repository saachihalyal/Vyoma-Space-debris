import test from "node:test";
import assert from "node:assert/strict";
import { searchAndSortCollisionEvents } from "../src/utils/collisionEventDisplay.js";
import { groupCoLocatedEvents, researchPcCatalogSummary } from "../src/utils/researchPcAnalytics.js";

function event(id, a, b, log10pc, { tcaStatus = "valid", reason = null } = {}) {
  return {
    id, primary: { id: a }, secondary: { id: b }, result_kind: "physics_assessment",
    physics_result: { status: "valid", tca_status: tcaStatus, tca: { value: "2026-10-24T17:01:21.000Z" }, miss_distance: { value: 1.2345 }, relative_speed_at_tca: { value: 12.346 } },
    automatic_research_pc_assessment: { log10_pc: log10pc, miss_sigma_ratio: 2, reason_code: reason, risk_assessment: { final_risk_class: "Low" } },
  };
}

test("default research Pc ordering uses exact log10 values and keeps boundary TCA out of ranked lead", () => {
  const boundary = event("edge", "A", "Z", 5, { tcaStatus: "boundary" });
  const low = event("low", "A", "B", -20);
  const high = event("high", "C", "D", -8);
  assert.deepEqual(searchAndSortCollisionEvents([boundary, low, high]).map((item) => item.id), ["high", "low", "edge"]);
});

test("likely co-located raw pairs are grouped without removing records and coverage is counted", () => {
  const a = event("1", "ISS", "RB", -8);
  const b = event("2", "NAUKA", "RB", -8);
  const c = event("3", "POISK", "RB", -8);
  const boundary = event("4", "X", "Y", null, { tcaStatus: "boundary" });
  const events = [a, b, c, boundary];
  const groups = groupCoLocatedEvents(events);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].members.length, 3);
  assert.equal(events.length, 4);
  const summary = researchPcCatalogSummary(events);
  assert.equal(summary.total, 4);
  assert.equal(summary.valid, 3);
  assert.equal(summary.withResearchPc, 3);
  assert.equal(summary.boundary, 1);
  assert.equal(summary.encounterGroups[0].memberEventIds.length, 3);
});
