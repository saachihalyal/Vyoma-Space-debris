import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ManeuverScreeningContext } from "../src/components/UI/ManeuverScreeningContext.js";

test("maneuver context distinguishes accepted partial result from latest failed attempt", () => {
  const markup = renderToStaticMarkup(React.createElement(ManeuverScreeningContext, {
    screeningJobId: "accepted-job-A",
    screeningStatus: { result_status: "partial", completion_status: "partial" },
    screeningAttempt: {
      run_id: "run-B",
      job_id: "failed-job-B",
      result_status: "unavailable",
      completion_status: "failed",
      reason: "screening service failed",
    },
  }));

  assert.match(markup, /Accepted screening job/);
  assert.match(markup, /accepted-job-A/);
  assert.match(markup, /Accepted result/);
  assert.match(markup, /partial.*partial/);
  assert.match(markup, /Latest screening attempt/);
  assert.match(markup, /failed-job-B/);
  assert.match(markup, /unavailable.*failed/);
  assert.match(markup, /accepted screening result is partial/);
  assert.match(markup, /event-specific maneuver assessment uses the selected event.*accepted stored states/);
  assert.doesNotMatch(markup, /completed valid screening result/);
});

test("maneuver context does not invent an accepted job or partial warning", () => {
  const markup = renderToStaticMarkup(React.createElement(ManeuverScreeningContext, {
    screeningStatus: { result_status: "valid_empty", completion_status: "complete" },
  }));

  assert.match(markup, /Accepted screening job/);
  assert.match(markup, /Unavailable/);
  assert.match(markup, /valid_empty.*complete/);
  assert.doesNotMatch(markup, /accepted screening result is partial/);
});
