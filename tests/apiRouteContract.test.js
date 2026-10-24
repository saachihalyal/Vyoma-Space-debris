import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const client = readFileSync(new URL("../src/api/ssaClient.js", import.meta.url), "utf8");
const backend = readFileSync(new URL("../backend/app/main.py", import.meta.url), "utf8");

test("Smart Filter and maneuver client routes exist in FastAPI", () => {
  for (const route of [
    "/api/conjunction-jobs/{job_id}/smart-filter",
    "/api/conjunction-jobs/{job_id}/smart-filter.csv",
    "/api/conjunctions/{event_id}/maneuver",
    "/api/maneuver/user-upload",
    "/api/version",
  ]) assert.ok(backend.includes(`\"${route}\"`), `backend route missing: ${route}`);
  assert.match(client, /\/api\/conjunction-jobs\/\$\{encodeURIComponent\(screeningJobId\.trim\(\)\)\}\/smart-filter/);
  assert.match(client, /\/api\/conjunctions\/\$\{encodeURIComponent\(event\.id\)\}\/maneuver/);
  assert.match(client, /\/api\/maneuver\/user-upload/);
});
