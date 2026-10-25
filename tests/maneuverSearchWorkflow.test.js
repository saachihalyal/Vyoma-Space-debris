import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("Maneuver Assessment exposes bounded search, best candidate and limitations in its default workflow", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const workbench = readFileSync(new URL("../src/components/UI/ManeuverWorkbench.jsx", import.meta.url), "utf8");
  const api = readFileSync(new URL("../src/api/ssaClient.js", import.meta.url), "utf8");
  const service = readFileSync(new URL("../backend/app/services/conjunction.py", import.meta.url), "utf8");
  assert.match(app, /<ManeuverWorkbench event=/);
  assert.match(workbench, /Event/);
  assert.match(workbench, /Burn lead time/);
  assert.match(workbench, /Maximum delta-v/);
  assert.match(workbench, /Run maneuver search/);
  assert.match(workbench, /Physics-ranked candidates/);
  assert.match(workbench, /RTN direction/);
  assert.match(workbench, /ManeuverUserUpload/);
  assert.match(workbench, /research Pc/);
  assert.match(service, /delta_s ~= 3 \* delta_v \* delta_t/);
  assert.match(workbench, /initialMassKg/);
  assert.match(workbench, /specificImpulseS/);
  assert.match(api, /initial_mass_kg/);
  assert.match(api, /specific_impulse_s/);
  assert.match(api, /uploadManeuverEvent/);
  assert.match(workbench, /Assumptions and sanity check/);
  assert.match(api, /max_delta_v_m_s/);
  assert.match(service, /bounded golden-section maximization of miss distance/);
  assert.match(service, /_maneuver_fuel_estimate/);
});

test("maneuver object-type presentation preserves catalog class and source independently of risk", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const workbench = readFileSync(new URL("../src/components/UI/ManeuverWorkbench.jsx", import.meta.url), "utf8");
  assert.match(workbench, /Catalog object types/);
  assert.match(workbench, /classification_source/);
  assert.match(workbench, /separate from collision-risk severity/);
});
