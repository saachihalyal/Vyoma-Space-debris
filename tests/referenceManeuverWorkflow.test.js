import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { calculateReferenceManeuver, referenceManeuverReportPath } from "../src/api/ssaClient.js";

test("Collision Analysis offers a validated standalone reference event to Maneuver Assessment", () => {
  const cdm = readFileSync(new URL("../src/components/UI/CdmReferenceAssessment.jsx", import.meta.url), "utf8");
  const maneuver = readFileSync(new URL("../src/components/UI/ReferenceManeuverAssessment.jsx", import.meta.url), "utf8");
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(cdm, /Open this reference event in Maneuver Assessment/);
  assert.match(cdm, /pc\?\.status !== "available"/);
  assert.match(app, /setReferenceManeuverEvent\(referenceEvent\)/);
  assert.match(app, /referenceEvent=\{referenceManeuverEvent\}/);
  assert.match(maneuver, /Burn lead before reference TCA/);
  assert.match(maneuver, /Impulse direction in burn-epoch RTN/);
  assert.match(maneuver, /held fixed at both encounter times/);
  assert.match(maneuver, /Pc reduction/);
  assert.match(maneuver, /relative_velocity_km_s/);
  assert.match(maneuver, /data\.probability_change\?\.percentage_reduction/);
  assert.match(maneuver, /Geometric miss-distance change/);
  assert.match(maneuver, /Download Reference Maneuver Report/);
});

test("reference maneuver API validates returned event identity and report path preserves submitted parameters", async () => {
  const originalFetch = globalThis.fetch;
  let calledUrl = "";
  let sent = null;
  globalThis.fetch = async (url, options) => {
    calledUrl = String(url);
    sent = JSON.parse(options.body);
    return new Response(JSON.stringify({
      result_kind: "standalone_reference_cdm_maneuver_assessment",
      data: { event_id: "CDM-test" },
    }), { status: 200 });
  };
  const args = { eventId: "CDM-test", maneuveringObjectId: "000020580", burnLeadSeconds: 300, direction: "along_track+", deltaVMs: 0.05 };
  try {
    const response = await calculateReferenceManeuver(args);
    assert.equal(response.data.event_id, args.eventId);
    assert.match(calledUrl, /reference-cases\/nasa-cara-foster-2d\/maneuver$/);
    assert.deepEqual(sent, { event_id: "CDM-test", maneuvering_object_id: "000020580", burn_lead_seconds: 300, direction: "along_track+", delta_v_m_s: 0.05 });
    const reportPath = referenceManeuverReportPath(args);
    assert.match(reportPath, /maneuver-report\.pdf/);
    assert.match(reportPath, /event_id=CDM-test/);
    assert.match(reportPath, /direction=along_track%2B/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("reference maneuver API rejects a response for a different event", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    result_kind: "standalone_reference_cdm_maneuver_assessment",
    data: { event_id: "CDM-other" },
  }), { status: 200 });
  try {
    await assert.rejects(calculateReferenceManeuver({
      eventId: "CDM-test", maneuveringObjectId: "000020580", burnLeadSeconds: 300, direction: "radial+", deltaVMs: 0.02,
    }), /does not match the selected standalone CDM event/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
