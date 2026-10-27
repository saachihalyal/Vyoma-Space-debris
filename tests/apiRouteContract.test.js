import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const client = readFileSync(new URL("../src/api/ssaClient.js", import.meta.url), "utf8");
const backend = readFileSync(new URL("../backend/app/main.py", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const maneuver = readFileSync(new URL("../src/components/UI/ManeuverWorkbench.jsx", import.meta.url), "utf8");
const screening = readFileSync(new URL("../backend/app/services/trajectory_screening.py", import.meta.url), "utf8");

test("Smart Filter and maneuver client routes exist in FastAPI", () => {
  for (const route of [
    "/api/conjunction-jobs/{job_id}/smart-filter",
    "/api/conjunction-jobs/{job_id}/smart-filter.csv",
    "/api/event-library",
    "/api/conjunctions/{event_id}/maneuver",
    "/api/maneuver/user-upload",
    "/api/version",
  ]) assert.ok(backend.includes(`\"${route}\"`), `backend route missing: ${route}`);
  assert.match(client, /\/api\/conjunction-jobs\/\$\{encodeURIComponent\(screeningJobId\.trim\(\)\)\}\/smart-filter/);
  assert.match(client, /\/api\/conjunctions\/\$\{encodeURIComponent\(event\.id\)\}\/maneuver/);
  assert.match(client, /\/api\/event-library\?/);
  assert.match(client, /\/api\/maneuver\/user-upload/);
});

test("saved event library deduplicates by pair and feeds Home, Collision, and Maneuver", () => {
  assert.match(backend, /@app\.get\("\/api\/event-library"\)/);
  assert.match(backend, /best_by_pair/);
  assert.match(backend, /screening_run_date/);
  assert.match(backend, /screening_library_current/);
  assert.match(backend, /"Low": 0, "Medium": 0, "High": 0/);
  assert.match(backend, /references\.append\(\{/);
  assert.match(backend, /await calculate_nasa_cara_reference_case\(\)/);
  assert.match(backend, /"reference_label": "Reference"/);
  assert.match(backend, /"reference_assessment"/);
  assert.match(backend, /horizon_hours: float = Query\(DEFAULT_HORIZON_HOURS, ge=0\.01, le=168\)/);
  assert.match(backend, /limit=min\(limit, 400\), min_pc=None, risk=None, horizon_hours=horizon_hours/);
  assert.match(backend, /hard_deadline = loop\.time\(\) \+ 9 \* 60/);
  assert.match(screening, /target_shell and debris_group/);
  assert.match(client, /getSavedEventLibrary/);
  assert.match(app, /eventLibrary=\{eventLibrary\}/);
  assert.match(app, /events=\{savedEvents\}/);
  assert.match(maneuver, /from saved screenings/);
  assert.match(app, /screeningHorizonHours=\{screeningHorizonHours\}/);
});
