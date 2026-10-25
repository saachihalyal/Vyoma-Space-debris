import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ManeuverEventContext } from "../src/components/UI/ManeuverEventContext.js";
import { selectManeuverEvent } from "../src/utils/maneuverSelection.js";

test("selected event context renders identity, state provenance, and distinct risk channels", () => {
  const event = {
    result_kind: "physics_assessment",
    id: "CA-ARCHIVE-1", primary: { id: "33762" }, secondary: { id: "33776" },
    physics_result: {
      status: "valid",
      tca: { value: "2026-10-14T06:22:15.243148+00:00" },
      miss_distance: { status: "available", value: 21.9462179503 },
      relative_velocity_at_tca: { status: "available", value: [1.2, -2.3, 3.4] },
      state_information: { source_frame: "TEME" },
    },
    collision_probability: { status: "available", event_id: "other-event", source_reported_event_id: "other", source_reported_pc: 0.2, object_1_id: "33762", object_2_id: "33776", tca_utc: "2026-10-14T06:22:15.243148+00:00", pc: 0.5 },
    automatic_research_pc_assessment: { status: "prior_based_research_estimate", estimated_pc_scientific: "< 1e-30", log10_pc: -58, method_name: "ORION TLE-age baseline" },
    ai_risk_assessment: { status: "available", score: 0.71, category: "review" },
  };
  const selected = selectManeuverEvent([event], event.id);
  assert.equal(selected, event);
  const markup = renderToStaticMarkup(React.createElement(ManeuverEventContext, {
    event: selected,
  }));
  assert.match(markup, /CA-ARCHIVE-1/);
  assert.match(markup, /33762 \/ 33776/);
  assert.match(markup, /2026-10-14T06:22:15/);
  assert.match(markup, /21\.9462179503 km/);
  assert.match(markup, /1\.200000, -2\.300000, 3\.400000 km\/s/);
  assert.match(markup, /TEME/);
  assert.match(markup, /Event-specific Foster Pc/);
  assert.match(markup, /Event-specific Foster Pc<strong>Unavailable/);
  assert.doesNotMatch(markup, /5\.00000e-1/);
  assert.match(markup, /Research Pc estimate/);
  assert.match(markup, /&lt; 1e-30 · ORION TLE-age baseline/);
  assert.match(markup, /Review priority \(rule-based\)/);
  assert.doesNotMatch(markup, /AI queue priority/);
  assert.match(markup, /rather than dynamically propagated/);
});
