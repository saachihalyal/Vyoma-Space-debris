import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { referenceAssessmentMatchesIndependence } from "../src/utils/cdmAssessmentState.js";
import { importEventCdm } from "../src/api/ssaClient.js";
import { calculateNasaCaraReferenceCase } from "../src/api/ssaClient.js";

test("Collision Analysis exposes separate CCSDS and TraCSS CDM assessment with explicit provenance limits", () => {
  const source = readFileSync(new URL("../src/components/UI/CdmReferenceAssessment.jsx", import.meta.url), "utf8");
  assert.match(source, /Collision Probability Calculator/);
  const upload = source.match(/<details className="optional-cdm-upload">([\s\S]*?)<\/details>/)?.[1] || "";
  assert.match(upload, /<summary>Upload Conjunction Data<\/summary>/);
  assert.match(upload, /Upload a CCSDS XML, KVN, or JSON conjunction message/);
  assert.doesNotMatch(upload, /NASA|TraCSS|Space-Track/);
  assert.match(upload, /Unsupported frames are explained/);
  assert.match(source, /Per-object supplied HBR/);
  assert.match(source, /Combined HBR used/);
  assert.match(source, /Covariance validation/);
  assert.match(source, /separate from live TLE screening events/);
  assert.match(source, /Explicitly assume independent object covariances/);
  assert.match(source, /Evaluate standalone CDM Pc/);
  assert.match(source, /Run bundled reference assessment/);
  assert.match(source, /Difference from rounded source Pc/);
  assert.match(source, /not independent validation against NASA CARA software/);
  assert.match(source, /optional-cdm-upload/);
  assert.match(source, /Advanced provenance, covariance and calculation diagnostics/);
  assert.match(source, /Pc reference category/);
  assert.match(source, /CDM-reported Pc \(separate source value\)/);
  assert.match(source, /COMPUTED/);
  assert.match(source, /SOURCE-REPORTED/);
  assert.match(source, /formatProbabilityPercentage/);
  assert.match(source, /formatProbabilityOdds/);
  assert.match(source, /Source labels and originators are not authenticated/);
  assert.match(source, /assumeIndependentCovariances: assumeIndependent/);
  assert.match(source, /referenceAssessmentMatchesIndependence\(assessment, assumeIndependent\)/);
  assert.match(source, /The independence assumption changed after this assessment/);
});

test("bundled reference action is visible in both empty and selected-event views", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.equal((source.match(/<CdmReferenceAssessment onUseReferenceEvent=\{onUseReferenceEvent\} \/>/g) || []).length, 2);
  assert.match(source, /collision-maneuver-entry/);
  assert.match(source, /selectEvent\(event, "maneuver"\)/);
});

test("bundled NASA CARA workflow calls its dedicated standalone reference endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let calledUrl = "";
  globalThis.fetch = async (url) => {
    calledUrl = String(url);
    return new Response(JSON.stringify({ success: true, result_kind: "standalone_nasa_cara_reference_assessment" }), { status: 200 });
  };
  try {
    const response = await calculateNasaCaraReferenceCase();
    assert.match(calledUrl, /\/api\/collision-probability\/reference-cases\/nasa-cara-foster-2d$/);
    assert.equal(response.result_kind, "standalone_nasa_cara_reference_assessment");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("live-event CDM import accepts all parser-supported document formats", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(source, /<strong>Upload Conjunction Data<\/strong>/);
  assert.match(source, /uploaded file must match both object IDs, exact TCA/);
  assert.match(source, /\.xml,\.cdm,\.kvn,\.txt,\.json,application\/xml,text\/xml,application\/json,text\/plain/);
  assert.match(source, /must match both object IDs, exact TCA, and the event frame shown here/);
  assert.match(source, /unsupported terrestrial frames are rejected because no validated Earth-orientation transform is applied/);
  assert.match(source, /Match CDM to event and calculate imported Pc/);
});

test("standalone CDM result is current only while its independence assumption matches the checkbox", () => {
  const unauthorizedResult = { collision_probability: { independence_assumption_authorized: false } };
  const authorizedResult = { collision_probability: { independence_assumption_authorized: true } };
  assert.equal(referenceAssessmentMatchesIndependence(unauthorizedResult, false), true);
  assert.equal(referenceAssessmentMatchesIndependence(unauthorizedResult, true), false);
  assert.equal(referenceAssessmentMatchesIndependence(authorizedResult, true), true);
  assert.equal(referenceAssessmentMatchesIndependence(authorizedResult, false), false);
  assert.equal(referenceAssessmentMatchesIndependence({}, true), false);
});

test("event-bound CDM validation surfaces structured reason codes", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: { reason_code: "CDM_TCA_MISMATCH", message: "Cdm tca mismatch" },
  }), { status: 422 });
  try {
    await assert.rejects(
      importEventCdm({ screeningJobId: "job-A", eventId: "event-A", cdmXml: "<cdm/>", sourceLabel: "test", assumeIndependentCovariances: true }),
      /CDM_TCA_MISMATCH: Cdm tca mismatch/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("external CDM retrieval is disconnected from the UI and API client", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const api = readFileSync(new URL("../src/api/ssaClient.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /Space-Track|spaceTrack|onRetrieveSpaceTrack/);
  assert.doesNotMatch(api, /Space-Track|spaceTrack|space-track/);
});

