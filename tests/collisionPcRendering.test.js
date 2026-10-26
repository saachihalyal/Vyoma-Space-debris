import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { CollisionPcSummary, CollisionProbabilityCard, formatCollisionProbability, formatProbabilityOdds, formatProbabilityPercentage, formatProbabilityScientific, sourcePcLabel, unavailableNextAction } from "../src/components/UI/CollisionPcSummary.js";

function render(sourceResult, scenarioResult) {
  return renderToStaticMarkup(React.createElement(CollisionPcSummary, { sourceResult, scenarioResult }));
}

test("Collision Analysis distinguishes missing source Pc from an unrun scenario", () => {
  const markup = render({ status: "unavailable", pc: null, reason_codes: ["NO_COVARIANCE", "HBR_UNAVAILABLE"] }, null);
  assert.match(markup, /Event collision probability/);
  assert.doesNotMatch(markup, /Imported CDM/);
  assert.match(markup, /unavailable - NO_COVARIANCE, HBR_UNAVAILABLE/);
  assert.match(markup, /No user-entered scenario has been run/);
  assert.match(markup, /Next action/);
  assert.match(markup, /Import a CDM for this object pair and exact TCA/);
  assert.match(markup, /CelesTrak GP\/OMM provides orbital elements/);
  assert.match(markup, /Upload a conjunction message for event-specific states, covariance, and HBR/);
  assert.doesNotMatch(markup, /0\.00000e\+0/);
});

test("missing HBR and unknown covariance correlation produce distinct next actions", () => {
  assert.match(unavailableNextAction({ reason_codes: ["HBR_UNAVAILABLE"] }), /documented hard-body radius/);
  assert.match(unavailableNextAction({ reason_codes: ["RELATIVE_COVARIANCE_CORRELATION_UNKNOWN"] }), /Authorize the independent-covariance assumption explicitly/);
});

test("Collision Analysis separates imported CDM Pc and explicitly assumed scenario Pc", () => {
  const imported = {
      status: "available",
      pc: 1e-7,
      covariance_sources: [{ source_type: "user_supplied" }, { source_type: "user_supplied" }],
      hbr_provenance: { source: "supplied", source_type: "user_supplied", description: "Combined HBR imported from user-supplied CDM." },
      warnings: ["Imported CDM source label and originator were not authenticated by ORION."],
  };
  const markup = render(
    imported,
    { status: "available", pc: 2e-7, provenance: { is_synthetic: true } },
  );
  assert.match(markup, /Imported CDM-based Foster Pc \(source unverified\)/);
  assert.match(markup, /available - 1\.00000e-7/);
  assert.match(markup, /Research scenario Pc/);
  assert.match(markup, /available - 2\.00000e-7/);
  assert.match(markup, /not authenticated by ORION/);
  assert.match(markup, /Assumed inputs only; separate from source-supported Pc/);
  assert.equal(sourcePcLabel(imported), "Imported CDM-based Foster Pc (source unverified)");
});

test("Pc display preserves method, units, covariance/HBR provenance and warnings", () => {
  const source = {
    status: "available",
    pc: 1e-7,
    method: "Foster 2D encounter-plane Gaussian integral",
    method_version: "1.0",
    provenance: { source: "CDM covariance calculation", source_type: "derived", is_synthetic: false },
    risk_assessment: {
      status: "classified", risk_score: 25, physics_risk_class: "Medium", final_risk_class: "Medium",
      risk_score_pc_channel: "event_specific_foster_pc",
      classification_basis: "Medium from event_specific_foster_pc under orion-physics-pc-risk-v1; this physics class controls the displayed final class.",
    },
    covariance_sources: [{ object_id: "A", source: "declared CDM", source_type: "user_supplied", frame: "TEME", epoch: "2025-01-01T00:00:00+00:00", units: { position: "km^2" } }],
    hbr_source: "supplied",
    hbr_provenance: { source_type: "user_supplied", description: "CDM combined radius; unauthenticated", units: "km" },
    warnings: ["Source authentication was not performed."],
  };
  const markup = render(source, {
    status: "unavailable",
    pc: null,
    method: "Foster 2D encounter-plane Gaussian integral",
    method_version: "1.0",
    reason_codes: ["HBR_UNAVAILABLE"],
    provenance: { source: "User-entered research scenario parameters", source_type: "derived", is_synthetic: true },
  });

  assert.match(markup, /probability dimensionless/);
  assert.match(markup, /declared CDM/);
  assert.match(markup, /TEME/);
  assert.match(markup, /2025-01-01T00:00:00/);
  assert.match(markup, /CDM combined radius/);
  assert.match(markup, /Source authentication was not performed/);
  assert.match(markup, /Physics Pc risk score and class/);
  assert.match(markup, /25\.0 \/ 100 · Medium · based on event_specific_foster_pc/);
  assert.match(markup, /this physics class controls the displayed final class/);
  assert.match(markup, /Research scenario Pc/);
  assert.match(markup, /unavailable - HBR_UNAVAILABLE/);
  assert.doesNotMatch(markup, /Research scenario Pc[^<]*available - 1\.00000e-7/);
});

test("available scenario Pc remains separate when source Pc is unavailable", () => {
  const markup = render(
    { status: "unavailable", pc: null, reason_codes: ["NO_COVARIANCE"] },
    { status: "available", pc: 2e-7, provenance: { source: "user-entered scenario", source_type: "derived", is_synthetic: true } },
  );
  assert.match(markup, /Event collision probability[\s\S]*unavailable - NO_COVARIANCE/);
  assert.match(markup, /Research scenario Pc[\s\S]*available - 2\.00000e-7/);
  assert.match(markup, /Assumed inputs only; separate from source-supported Pc/);
});

test("user-supplied covariance without CDM provenance keeps a neutral event label", () => {
  assert.equal(sourcePcLabel({
    status: "available",
    covariance_sources: [{ source_type: "user_supplied" }, { source_type: "user_supplied" }],
    hbr_provenance: { source_type: "user_supplied", description: "User supplied HBR" },
  }), "Event collision probability");
});

test("unsupported and invalid covariance inputs remain labeled and have no numeric Pc", () => {
  const markup = render(
    { status: "invalid", pc: null, reason_codes: ["INVALID_COVARIANCE"] },
    { status: "unsupported", pc: null, reason_codes: ["RELATIVE_COVARIANCE_CORRELATION_UNKNOWN"] },
  );
  assert.match(markup, /invalid - INVALID_COVARIANCE/);
  assert.match(markup, /unsupported - RELATIVE_COVARIANCE_CORRELATION_UNKNOWN/);
  assert.doesNotMatch(markup, /e\+0/);
});

test("Pc formatting never turns null, zero, or invalid numbers into zero probability", () => {
  assert.equal(formatCollisionProbability(null), "Pc unavailable");
  assert.equal(formatCollisionProbability(0), "Pc unavailable");
  assert.equal(formatCollisionProbability(Number.NaN), "Pc unavailable");
  assert.equal(formatCollisionProbability(1e-7), "1.000e-7");
});

test("an available status with zero Pc is rendered as invalid with an explicit reason", () => {
  const markup = render({ status: "available", pc: 0, reason_codes: [] }, null);
  assert.match(markup, /Event collision probability[\s\S]*invalid - INVALID_PC_VALUE/);
  assert.doesNotMatch(markup, /available - 0(?:\.0+)?(?:<|\s)/);
});

test("Pc summary formats scientific notation, percentage, odds, method and source without inventing values", () => {
  assert.equal(formatProbabilityScientific(1.862e-5), "1.862 × 10^-5");
  assert.equal(formatProbabilityPercentage(1.862e-5), "1.862e-3%");
  assert.equal(formatProbabilityOdds(1.862e-5), "about 1 in 53,706");
  assert.equal(formatProbabilityScientific(0), "0.000 × 10^+0");
  const markup = renderToStaticMarkup(React.createElement(CollisionProbabilityCard, {
    result: { status: "available", event_id: "E1", pc: 1.862e-5, method: "Foster 2D", method_version: "1.0", covariance_status: "available", covariance_frame: "EME2000", covariance_epoch: "2025-01-01T00:00:00Z", hbr_source: "supplied", provenance: { source: "NASA CARA fixture" }, source_reported_pc_provenance: { source: "fixture.cdm", input_sha256: "abc123", authenticated: false } },
    sourceReportedPc: 1.9e-5,
    sourceReportedMethod: "CDM-reported Foster-1992",
  }));
  assert.match(markup, /COMPUTED/);
  assert.match(markup, /1\.862 × 10\^-5/);
  assert.match(markup, /Percentage/);
  assert.match(markup, /Foster 2D v1\.0/);
  assert.match(markup, /NASA CARA fixture/);
  assert.match(markup, /SOURCE-REPORTED/);
  assert.match(markup, /CDM-reported Foster-1992/);
  assert.match(markup, /kept separate from Vyoma/);
  assert.match(markup, /fixture\.cdm/);
  assert.match(markup, /SHA-256 abc123/);
});

test("zero source-reported probability has zero percent and no undefined reciprocal odds", () => {
  assert.equal(formatProbabilityScientific(0), "0.000 × 10^+0");
  assert.equal(formatProbabilityPercentage(0), "0.000e+0%");
  assert.equal(formatProbabilityOdds(0), "not defined for Pc = 0");
  const markup = renderToStaticMarkup(React.createElement(CollisionProbabilityCard, {
    result: { status: "unavailable", reason_codes: ["NO_COVARIANCE"] },
    sourceReportedPc: 0,
    sourceReportedMethod: "source method",
  }));
  assert.match(markup, /SOURCE-REPORTED/);
  assert.match(markup, /not defined for Pc = 0/);
});

test("source Pc is labeled source-reported and unavailable Pc never becomes zero", () => {
  const sourceOnly = renderToStaticMarkup(React.createElement(CollisionProbabilityCard, {
    result: { status: "unavailable", reason_codes: ["NO_COVARIANCE", "HBR_UNAVAILABLE"] },
    sourceReportedPc: 1.862e-5,
    sourceReportedMethod: "Foster-1992",
  }));
  assert.match(sourceOnly, /SOURCE-REPORTED/);
  assert.match(sourceOnly, /Foster-1992/);
  const unavailable = renderToStaticMarkup(React.createElement(CollisionProbabilityCard, {
    result: { status: "unavailable", reason_codes: ["NO_COVARIANCE"] },
  }));
  assert.match(unavailable, /UNAVAILABLE/);
  assert.match(unavailable, /Why is Pc unavailable/);
  assert.match(unavailable, /NO_COVARIANCE/);
  assert.doesNotMatch(unavailable, /0\.000/);
});
