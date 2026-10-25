import test from "node:test";
import assert from "node:assert/strict";
import { buildResearchPcHeatmap } from "../src/utils/researchPcHeatmap.js";

const event = (id, { status = "valid", tcaStatus = "valid", log10Pc = -8, altitude = 500, speed = 7.5 } = {}) => ({
  id, result_kind: "physics_assessment",
  physics_result: { status, tca_status: tcaStatus },
  primary: { altitude_km: altitude, velocity_kms: speed },
  automatic_research_pc_assessment: log10Pc == null ? {} : { log10_pc: log10Pc },
});

test("research Pc heat map names and clips its metric while retaining actual valid values", () => {
  const map = buildResearchPcHeatmap([event("normal"), event("tail", { log10Pc: -80 })]);
  assert.equal(map.metric, "clipped -log10 Pc (0 to 30; research Pc)");
  assert.equal(map.plottedCount, 2);
  assert.equal(map.cells.reduce((sum, cell) => sum + cell.count, 0), 2);
  assert.equal(map.cells.find((cell) => cell.count === 2)?.value, 19);
});

test("missing research Pc, invalid events, and invalid log probabilities stay unplotted", () => {
  const map = buildResearchPcHeatmap([
    event("missing", { log10Pc: null }),
    event("invalid", { status: "invalid" }),
    event("boundary", { tcaStatus: "boundary" }),
    event("bad-pc", { log10Pc: 0.2 }),
    event("missing-coordinate", { altitude: null }),
  ]);
  assert.equal(map.plottedCount, 0);
  assert.equal(map.excludedCount, 5);
  assert.ok(map.cells.every((cell) => cell.value === null && cell.count === 0));
});
