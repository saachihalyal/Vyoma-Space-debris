import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/components/UI/ManeuverWorkbench.jsx", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const theme = readFileSync(new URL("../src/og-theme.css", import.meta.url), "utf8");
const reference = readFileSync(new URL("../src/components/UI/ReferenceManeuverAssessment.jsx", import.meta.url), "utf8");

test("Maneuver Workbench uses the one-button flow with advanced fields collapsed", () => {
  assert.match(app, /<ManeuverWorkbench event=/);
  assert.match(source, /className="og-page og-maneuver"/);
  assert.match(source, /Choose an event/);
  assert.match(source, /sorted by Pc \(highest first\)/);
  assert.match(source, /<summary>Advanced<\/summary>/);
  assert.match(source, /const defaultLeadSeconds = 1800/);
  assert.match(source, /Avoidance Action Plan/);
  assert.match(source, /Find safest maneuver/);
  assert.match(source, /Try sample conjunction/);
  assert.match(theme, /\.og-card/);
});

test("Maneuver keeps before/after, action metrics, burn window, options, reports, and ranking status", () => {
  for (const phrase of ["Before", "After", "Fuel cost", "Maneuver options", "Show all", "ranking_used === false", "Burn window", "Physics rank", "AI rank"]) {
    assert.ok(source.includes(phrase), `missing ${phrase}`);
  }
  assert.match(source, /selectedManeuverReportPath/);
  assert.match(source, /ManeuverUserUpload/);
  assert.doesNotMatch(source, /ManeuverScreeningContext|partial/);
  assert.match(source, /No maneuver needed - collision probability is negligible/);
  assert.match(source, /No maneuver needed - collision probability is negligible/);
  assert.match(reference, /AI ranking not used: this standalone CDM comparison evaluates one specified burn/);
  assert.doesNotMatch(source, /log10 Pc = -\d{2,}/);
});
