import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ManeuverBaselineComparison } from "../src/components/UI/ManeuverBaselineComparison.js";

const render = (props = {}) => renderToStaticMarkup(React.createElement(ManeuverBaselineComparison, props));

test("comparison table includes zero-burn geometry and candidate output", () => {
  const markup = render({
    zeroBurnBaseline: { status: "evaluated", tca_utc: "2026-10-14T06:22:15Z", miss_distance_km: 21.946217, candidate: { closest_approach_utc: "2026-10-14T06:22:15Z", miss_distance_km: 21.946217, relative_velocity_km_s: [1, 2, 3] } },
    candidates: [{ direction: "along-track +", delta_v_m_s: 0.01, maneuver_epoch_utc: "2026-10-14T06:17:15Z", closest_approach_utc: "2026-10-14T06:22:20Z", predicted_miss_distance_km: 22.1, change_from_zero_burn_km: 0.153783, delta_v_rtn_m_s: [0, 0.01, 0], relative_velocity_km_s: [1, 2, 3] }],
    probabilityBefore: { status: "unavailable", reason_code: "REAL_TLE_PRIOR_INPUTS_AND_VALID_CANDIDATE_TCA_REQUIRED" },
    probabilityAfter: { status: "unavailable", reason_code: "TLE_ELEMENT_EPOCH_UNAVAILABLE" },
    probabilityComparison: { status: "not_comparable", risk_reduction_pct: null },
  });
  assert.match(markup, /Zero-Burn and Candidate Comparison/);
  assert.match(markup, /Zero-burn baseline/);
  assert.match(markup, /Candidate 1/);
  assert.match(markup, /21\.946217/);
  assert.match(markup, /22\.100000/);
  assert.match(markup, /0\.153783/);
  assert.match(markup, /same declared research covariance\/HBR policy/);
  assert.doesNotMatch(markup, /same ESA-prior Foster research covariance\/HBR policy/);
  assert.match(markup, /Pc reduction/);
  assert.match(markup, /REAL_TLE_PRIOR_INPUTS_AND_VALID_CANDIDATE_TCA_REQUIRED/);
  assert.doesNotMatch(markup, /risk reduction[^<]*[0-9]+%/i);
});

test("Pc reduction appears only when the backend marks comparable numerical values", () => {
  const markup = render({
    probabilityBefore: { status: "available", pc: 0.01 },
    probabilityAfter: { status: "available", pc: 0.005 },
    probabilityComparison: { status: "available", risk_reduction_pct: 50 },
  });
  assert.match(markup, /5\.000000e-3/);
  assert.match(markup, /50\.00%/);
});

