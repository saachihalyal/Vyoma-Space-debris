import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("Maneuver Assessment keeps its one-button flow and bounded research defaults", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const workbench = readFileSync(new URL("../src/components/UI/ManeuverWorkbench.jsx", import.meta.url), "utf8");
  const api = readFileSync(new URL("../src/api/ssaClient.js", import.meta.url), "utf8");
  const service = readFileSync(new URL("../backend/app/services/conjunction.py", import.meta.url), "utf8");
  assert.match(app, /<ManeuverWorkbench event=/);
  assert.match(workbench, /Event/);
  assert.match(workbench, /Find safest maneuver/);
  assert.match(workbench, /<summary>Advanced<\/summary>/);
  assert.match(workbench, /Default: one orbit \(90 min\)/);
  assert.match(workbench, /Maximum delta-v/);
  assert.match(workbench, /Maneuver options/);
  assert.match(workbench, /<span>Direction<\/span>/);
  assert.match(workbench, /ManeuverUserUpload/);
  assert.match(workbench, /Research Pc/);
  assert.match(service, /delta_s ~= 3 \* delta_v \* delta_t/);
  assert.match(workbench, /initialMassKg/);
  assert.match(workbench, /specificImpulseS/);
  assert.match(api, /initial_mass_kg/);
  assert.match(api, /specific_impulse_s/);
  assert.match(api, /uploadManeuverEvent/);
  assert.match(workbench, /No maneuver needed - collision probability is negligible/);
  assert.match(api, /max_delta_v_m_s/);
  assert.match(service, /bounded golden-section maximization of miss distance/);
  assert.match(service, /_maneuver_fuel_estimate/);
  assert.match(app, /if \(activePage !== "maneuver"\) return undefined/);
  assert.match(app, /setManeuverRequest\(\{ eventId: maneuverAssessmentEvent\.id, screeningJobId: maneuverScreeningJobId, leadSeconds: 1800/);
  assert.match(app, /resolveManeuverEvent\(selectedEvent, savedEvents\)/);
});

test("maneuver event chooser labels each event and Pc, ordered by Pc", () => {
  const workbench = readFileSync(new URL("../src/components/UI/ManeuverWorkbench.jsx", import.meta.url), "utf8");
  assert.match(workbench, /sorted by Pc \(highest first\)/);
  assert.match(workbench, /pcText\(pc\)/);
  assert.match(workbench, /ap !== bp/);
});
