import test from "node:test";
import assert from "node:assert/strict";
import { compactPcText, researchPcPresentation } from "../src/utils/collisionPcPresentation.js";
import { formatProbabilityScientific } from "../src/components/UI/CollisionPcSummary.js";

test("workbench numeric cell strings stay within 40 characters", () => {
  const numericCells = [
    "21.848 km",
    "7.2029 km/s",
    "2026-10-25T21:22:11.871Z",
    "0.123 / 4.567 km",
    "2.6 x 10^-7 (negligible)",
  ];
  for (const value of numericCells) assert.ok(value.length <= 40, `${value} exceeds 40 characters`);
});

test("Pc display strings never contain an exponent outside plus or minus 300", () => {
  const pcStrings = [
    compactPcText(researchPcPresentation({ status: "prior_based_research_estimate", estimated_pc_scientific: "2.6e-7" }).value),
    compactPcText(researchPcPresentation({ status: "prior_based_research_estimate", estimated_pc_scientific: "5.79e-9574" }).value),
    compactPcText(researchPcPresentation({ status: "prior_based_research_estimate", estimated_pc_scientific: "1.2e301" }).value),
    formatProbabilityScientific(5e-324),
  ];
  for (const value of pcStrings) {
    for (const match of value.matchAll(/10\^([+-]?\d+)/g)) assert.ok(Math.abs(Number(match[1])) <= 300, `${value} exceeds exponent bounds`);
  }
  assert.equal(pcStrings[0], "2.6 x 10^-7");
  assert.equal(pcStrings[1], "< 1 x 10^-300");
  assert.equal(pcStrings[2], "> 1 x 10^300");
  assert.equal(pcStrings[3], "< 1e-300");
});
