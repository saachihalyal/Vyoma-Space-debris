import test from "node:test";
import assert from "node:assert/strict";
import { getScreeningJobSelection } from "../src/utils/screeningJobSelection.js";

test("selecting an archived job changes export selection without replacing current live results", () => {
  const livePlatform = {
    conjunctionStatus: { job_id: "live-job", result_status: "complete" },
    conjunctions: [{ id: "CA-live" }],
  };
  const archivedJob = {
    job_id: "0123456789abcdef0123456789abcdef",
    status: "partial",
    archived: true,
    result: { data: [{ id: "CA-archive" }] },
  };

  const selected = getScreeningJobSelection(livePlatform, archivedJob);
  assert.equal(selected.jobId, archivedJob.job_id);
  assert.equal(selected.isArchived, true);
  assert.equal(selected.archivedJob, archivedJob);
  assert.equal(selected.livePlatform, livePlatform);
  assert.deepEqual(livePlatform.conjunctions, [{ id: "CA-live" }]);
  assert.equal(livePlatform.conjunctionStatus.job_id, "live-job");
});

test("clearing archived selection returns CSV export selection to the live job", () => {
  const livePlatform = { conjunctionStatus: { job_id: "live-job" }, conjunctions: [] };
  const selected = getScreeningJobSelection(livePlatform, null);
  assert.equal(selected.jobId, "live-job");
  assert.equal(selected.isArchived, false);
});
