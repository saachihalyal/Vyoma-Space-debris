import test from "node:test";
import assert from "node:assert/strict";
import { formatPriorProbability, hasValidEventFosterPc, operationalFosterStatus, physicsPcRiskPresentation, researchPcPresentation } from "../src/utils/collisionPcPresentation.js";

test("ESA-prior Pc values and extreme sensitivities render in readable scientific notation", () => {
  assert.equal(formatPriorProbability("1.56e-167"), "1.56e-167");
  assert.equal(formatPriorProbability("5.79e-9574", 2), "5.79e-9572");
  const formatted = researchPcPresentation({
    status: "prior_based_research_estimate",
    estimated_pc_scientific: "1.56e-167",
    percentage_scientific: "1.56e-165",
    lower_sensitivity_pc_scientific: "5.79e-9574",
    upper_sensitivity_pc_scientific: "2.72e-10",
    sensitivity_reason: "Coupled prior scenarios; not a confidence interval.",
  });
  assert.equal(formatted.value, "1.56e-167");
  assert.equal(formatted.percentage, "1.56e-165%");
  assert.match(formatted.sensitivity, /5\.79e-9574 to 2\.72e-10 Pc/);
  assert.match(formatted.sensitivity, /% to/);
});

test("event-specific Foster Pc requires a usable number and matching event identity", () => {
  const event = { id: "event-1", collision_probability: { status: "available", event_id: "event-1", pc: 1e-5 } };
  assert.equal(hasValidEventFosterPc(event), true);
  assert.equal(hasValidEventFosterPc({ ...event, collision_probability: { ...event.collision_probability, event_id: "other" } }), false);
  assert.equal(hasValidEventFosterPc({ ...event, collision_probability: { ...event.collision_probability, pc: null } }), false);
});

test("physics risk presentation states the Pc channel controlling the final class", () => {
  const display = physicsPcRiskPresentation({
    status: "classified", risk_score: 35.2, final_risk_class: "Medium",
    risk_score_pc_channel: "research_pc",
    classification_basis: "Medium from research_pc under orion-physics-pc-risk-v1.",
  });
  assert.equal(display.value, "35.2 / 100 · Medium · based on research_pc");
  assert.match(display.basis, /orion-physics-pc-risk-v1/);
  assert.equal(physicsPcRiskPresentation({ status: "unavailable" }).value, "Unavailable · no class is inferred without a valid physics Pc");
});

test("TLE-only Foster Pc unavailability explains the missing covariance and HBR inputs", () => {
  const status = operationalFosterStatus({
    id: "event-1",
    provenance: { source: "CelesTrak GP/OMM TLE" },
    physics_result: { status: "valid" },
    collision_probability: { status: "unavailable", reason_codes: ["NO_COVARIANCE", "HBR_UNAVAILABLE"] },
  });
  assert.match(status, /Unavailable: missing event-matched covariance for both objects and a sourced hard-body radius/);
});

test("unevaluable research Pc shows a human explanation and the machine reason code", () => {
  const display = researchPcPresentation({
    status: "not_estimable",
    reason_codes: ["TCA_STATE_UNAVAILABLE"],
    reason_message: "The event does not contain valid same-epoch TEME position and velocity states for both objects at TCA.",
  });
  assert.match(display.reason, /does not contain valid same-epoch TEME position and velocity states/);
  assert.match(display.reason, /TCA_STATE_UNAVAILABLE/);
});
