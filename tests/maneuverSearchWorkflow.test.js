import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("Maneuver Assessment exposes bounded search, best candidate and limitations in its default workflow", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const api = readFileSync(new URL("../src/api/ssaClient.js", import.meta.url), "utf8");
  const service = readFileSync(new URL("../backend/app/services/conjunction.py", import.meta.url), "utf8");
  assert.match(app, /Select a trajectory-derived event/);
  assert.match(app, /Burn lead before baseline TCA/);
  assert.match(app, /Maximum Δv \(m\/s\)/);
  assert.match(app, /Run Maneuver Search/);
  assert.match(app, /Best Physics-Evaluated Candidate/);
  assert.match(app, /RTN direction to assess/);
  assert.match(app, /ManeuverUserUpload/);
  assert.match(app, /research Pc/);
  assert.match(service, /delta_s ~= 3 \* delta_v \* delta_t/);
  assert.match(app, /initialMassKg/);
  assert.match(app, /specificImpulseS/);
  assert.match(api, /initial_mass_kg/);
  assert.match(api, /specific_impulse_s/);
  assert.match(api, /uploadManeuverEvent/);
  assert.match(app, /advanced-maneuver-details/);
  assert.match(api, /max_delta_v_m_s/);
  assert.match(service, /bounded golden-section maximization of miss distance/);
  assert.match(service, /_maneuver_fuel_estimate/);
});

test("maneuver object-type presentation preserves catalog class and source independently of risk", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(app, /Catalog object type/);
  assert.match(app, /Classification source:/);
  assert.match(app, /raw source class:/);
  assert.match(app, /It is not collision-risk severity/);
});
