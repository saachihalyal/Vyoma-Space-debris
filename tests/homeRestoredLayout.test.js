import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/components/UI/HomePage.jsx", import.meta.url), "utf8");

test("Home uses accepted state for six KPI tiles, top events, and class distribution", () => {
  for (const label of ["Objects tracked", "Debris count", "Close approaches screened", "Medium/High events", "Mean congestion score", "Maneuver candidates", "Research briefing", "Top close approaches", "Class distribution"]) assert.ok(source.includes(label));
  assert.match(source, /researchPcCatalogSummary\(events\)/);
  assert.match(source, /event\.automatic_research_pc_assessment/);
  assert.match(source, /event\.collision_ai_assessment/);
  assert.doesNotMatch(source, /BarChart|LineChart|ResearchPcChart|histogram/);
});
