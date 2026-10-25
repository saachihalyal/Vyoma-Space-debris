import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/components/UI/ManeuverWorkbench.jsx", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const theme = readFileSync(new URL("../src/og-theme.css", import.meta.url), "utf8");

test("Maneuver Workbench is wired into the app with Nebula Glass layout and the requested lead presets", () => {
  assert.match(app, /<ManeuverWorkbench event=/);
  assert.match(source, /className="og-page og-maneuver"/);
  assert.match(source, /Inputs/);
  assert.match(source, /\[\["300", "5 min"\], \["1800", "30 min"\], \["5400", "90 min · one orbit"\], \["10800", "3 hours"\]\]/);
  assert.match(source, /useState\("5400"\)/);
  assert.match(source, /Run maneuver search/);
  assert.match(theme, /\.og-card/);
});

test("Maneuver Workbench keeps numerical before/after, fuel, candidate, report and model-status outputs", () => {
  for (const phrase of ["Before", "After", "Pc change", "Fuel estimate", "Physics-ranked candidates", "Show all", "Assumptions and sanity check", "estimated from default assumptions", "ranking_used === false"]) {
    assert.ok(source.includes(phrase), `missing ${phrase}`);
  }
  assert.match(source, /selectedManeuverReportPath/);
  assert.match(source, /ManeuverUserUpload/);
  assert.match(source, /ManeuverEventContext/);
  assert.match(source, /Baseline already negligible \(log10 Pc =/);
  assert.doesNotMatch(source, /\u2014|Unavailable/);
});
