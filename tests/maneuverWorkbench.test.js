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
  assert.match(source, /Try NASA example \(Medium risk\)/);
  assert.match(source, /Loads the bundled NASA CARA conjunction case and its reference maneuver assessment/);
  assert.match(source, /maneuver-search-button/);
  assert.match(source, /Searching for safest maneuver/);
  assert.match(source, /maneuver-request-error/);
  assert.match(source, /Pc reduction/);
  assert.match(source, /Burn direction/);
  assert.match(source, /fuelCostKg/);
  assert.match(theme, /\.og-card/);
  assert.match(theme, /\.og-maneuver\{max-width:1200px;margin-inline:auto;font-size:13px\}/);
  assert.match(app, /everyManeuverEventBelowFloor/);
  assert.match(app, /loadManeuverDemo\(\)/);
  assert.match(app, /burnLeadSeconds: 1800/);
  assert.match(source, /Sample conjunction \(NASA CARA\)/);
});

test("Maneuver keeps before/after, action metrics, burn window, options, reports, and ranking status", () => {
  for (const phrase of ["Before", "After", "Fuel estimate", "Maneuver options", "Show all", "ranking.ranking_used === false", "Burn window", "Physics rank", "AI rank"]) {
    assert.ok(source.includes(phrase), `missing ${phrase}`);
  }
  assert.match(source, /selectedManeuverReportPath/);
  assert.match(source, /ManeuverUserUpload/);
  assert.doesNotMatch(source, /ManeuverScreeningContext|partial/);
  assert.match(source, /No maneuver needed - collision probability is negligible/);
  assert.match(source, /No maneuver needed - collision probability is negligible/);
  assert.match(reference, /AI ranking not used: this standalone CDM comparison evaluates one specified burn/);
  assert.doesNotMatch(source, /log10 Pc = -\d{2,}/);
  assert.match(source, /Pc can fall even if the miss distance shrinks, because uncertainty is larger in one direction\./);
  assert.match(source, /maneuver-recommended-badge">Recommended<\/span>/);
  assert.doesNotMatch(source, /isRecommended \? " · Recommended"/);
  assert.match(source, /\["available", "available_with_warning"\]\.includes\(result\.status\) \? "Assessment complete"/);
});
