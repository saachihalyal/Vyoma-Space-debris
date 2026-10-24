import React, { useState } from "react";
import { calculateNasaCaraReferenceCase, calculateReferenceCdmPc } from "../../api/ssaClient.js";
import { formatProbabilityOdds, formatProbabilityPercentage, formatProbabilityScientific, isValidProbability } from "./CollisionPcSummary.js";
import { referenceAssessmentMatchesIndependence } from "../../utils/cdmAssessmentState.js";

export function CdmReferenceAssessment({ onUseReferenceEvent = () => {} }) {
  const [cdmText, setCdmText] = useState("");
  const [sourceLabel, setSourceLabel] = useState("");
  const [assumeIndependent, setAssumeIndependent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [assessment, setAssessment] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("Validating the standalone CDM and evaluating its own TCA states...");
    setAssessment(null);
    try {
      const response = await calculateReferenceCdmPc({
        cdmText,
        sourceLabel,
        assumeIndependentCovariances: assumeIndependent,
      });
      setAssessment(response.data);
      setMessage(`CDM event ${response.data?.event_id || "unavailable"}: ${response.data?.collision_probability?.status || "unavailable"}.`);
    } catch (error) {
      setMessage(error?.message || "CDM assessment was rejected.");
    } finally {
      setBusy(false);
    }
  }

  async function runBundledReference() {
    setBusy(true);
    setMessage("Loading and validating the bundled NASA CARA reference event...");
    setAssessment(null);
    try {
      const response = await calculateNasaCaraReferenceCase();
      setAssessment(response.data);
      setAssumeIndependent(true);
      const comparison = response.data?.reference_case;
      const result = response.data?.collision_probability;
      setMessage(result?.status === "available"
        ? `NASA CARA reference calculation succeeded; source comparison is ${comparison?.within_tolerance ? "within published rounding tolerance" : "outside published rounding tolerance"}.`
        : `NASA CARA reference calculation unavailable: ${(result?.reason_codes || []).join(", ") || result?.status || "no Pc result"}.`);
    } catch (error) {
      setMessage(error?.message || "Bundled NASA CARA reference assessment failed.");
    } finally {
      setBusy(false);
    }
  }

  const pc = assessment?.collision_probability;
  const assessmentMatchesCurrentAssumption = referenceAssessmentMatchesIndependence(assessment, assumeIndependent);
  return <section className="panel cdm-reference-assessment" aria-label="Collision probability calculator">
    <div className="cdm-reference-heading"><div><span className="reference-eyebrow">Separate reference assessment</span><h2>Collision Probability Calculator</h2>
      <p className="muted">Run the bundled CDM directly. Its results stay separate from live TLE screening events and never replace the selected live event.</p></div>
      <button className="primary-action" type="button" disabled={busy} onClick={runBundledReference}>{busy ? "Assessing reference…" : "Run bundled reference assessment"}</button>
    </div>
    {message ? <p className="reference-assessment-status" role="status">{message}</p> : null}
    {assessment?.reference_case ? <p className="reference-comparison-caveat">The bundled CDM's rounded Pc is a source value for comparison; agreement here is not independent validation against NASA CARA software.</p> : null}
    {assessment && assessmentMatchesCurrentAssumption ? <div className="reference-result-grid" aria-live="polite">
      <span>TCA<strong>{assessment.tca_utc || "Unavailable"}</strong></span>
      <span>Miss distance<strong>{pc?.miss_distance_km == null ? "Unavailable" : `${Number(pc.miss_distance_km).toFixed(6)} km (ORION states)`}{assessment.source_reported_miss_distance_km == null ? "" : ` · ${assessment.source_reported_miss_distance_km} km source`}</strong></span>
      <span>Combined HBR<strong>{pc?.hbr_km == null ? "Unavailable" : `${pc.hbr_km} km`}</strong></span>
      <span>Method<strong>{pc?.method || "Unavailable"}</strong></span>
      <span>ORION-computed Pc<strong>{isValidProbability(pc?.pc) && pc?.status === "available" ? `${formatProbabilityScientific(pc.pc)} · ${formatProbabilityPercentage(pc.pc)}` : `Unavailable · ${(pc?.reason_codes || []).join(", ") || pc?.status || "no numeric Pc"}`}</strong></span>
      <span>CDM source-reported Pc<strong>{isValidProbability(assessment.source_reported_pc) ? `${formatProbabilityScientific(assessment.source_reported_pc)} · ${formatProbabilityPercentage(assessment.source_reported_pc)} · ${assessment.source_reported_pc_method || "method undeclared"}` : "Not supplied as a valid probability"}</strong></span>
      {assessment.reference_case ? <span>Difference from rounded source Pc<strong>{assessment.reference_case.absolute_difference == null ? "Unavailable" : `${Number(assessment.reference_case.absolute_difference).toExponential(3)} (tolerance ${assessment.reference_case.comparison_tolerance}) · ${assessment.reference_case.within_tolerance ? "within rounding tolerance" : "outside rounding tolerance"}`}</strong></span> : null}
    </div> : null}
    {assessment && !assessmentMatchesCurrentAssumption ? <p className="muted" role="status">The covariance-independence setting changed after this result. Run the assessment again to refresh it.</p> : null}
    <details className="optional-cdm-upload"><summary>Upload Conjunction Data</summary>
    <p className="muted">Upload a CCSDS XML, KVN, or JSON conjunction message. The calculator uses the file's object IDs, TCA states, covariance, reference frame, and supplied hard-body radius when compatible. Unsupported frames are explained before a probability is returned. Source labels and originators are not authenticated.</p>
    <form className="readout-list" onSubmit={submit}>
      <label>CDM source label<input required maxLength={200} value={sourceLabel} onChange={(event) => setSourceLabel(event.target.value)} /></label>
      <label>Conjunction data file (XML, KVN, or JSON)<input required type="file" accept=".cdm,.xml,.json,application/json,application/xml,text/xml,text/plain" onChange={async (event) => {
        const file = event.target.files?.[0];
        if (!file) { setCdmText(""); return; }
        if (file.size > 1_000_000) { setCdmText(""); setMessage("CDM input exceeds the 1 MB limit."); return; }
        setCdmText(await file.text());
      }} /></label>
      <label className="filter-checkbox"><input type="checkbox" checked={assumeIndependent} onChange={(event) => {
        setAssumeIndependent(event.target.checked);
        if (assessment) setMessage("The independence assumption changed after this assessment. Submit again to calculate with the checked assumption.");
      }} /> Explicitly assume independent object covariances</label>
      <button className="secondary-action" type="submit" disabled={busy || !cdmText || !sourceLabel.trim()}>{busy ? "Evaluating..." : "Evaluate standalone CDM Pc"}</button>
    </form></details>
    {assessment && assessmentMatchesCurrentAssumption ? <details className="reference-advanced-details"><summary>Advanced provenance, covariance and calculation diagnostics</summary><div className="readout-list" aria-live="polite">
      <span>CDM event identity<strong>{assessment.event_id}</strong></span>
      <span>Input format<strong>{assessment.source_format || "Unavailable"}</strong></span>
      {assessment.object_hbr_inputs_km ? <span>Per-object supplied HBR<strong>{Object.entries(assessment.object_hbr_inputs_km).map(([id, value]) => `${id}: ${value == null ? "not separately supplied" : `${value} km`}`).join(" · ")}</strong></span> : null}
      <span>Object 1<strong>{assessment.object_1?.name || "Name unavailable"} · {assessment.object_1?.id || "ID unavailable"}</strong></span>
      <span>Object 2<strong>{assessment.object_2?.name || "Name unavailable"} · {assessment.object_2?.id || "ID unavailable"}</strong></span>
      <span>CDM TCA / state frame<strong>{assessment.tca_utc || "Unavailable"} · {assessment.reference_frame || "Unavailable"}</strong></span>
      <span>CDM-reported miss distance<strong>{assessment.source_reported_miss_distance_km == null ? "Not supplied" : `${assessment.source_reported_miss_distance_km} km (source-reported)`}</strong></span>
      <span>Combined HBR used<strong>{pc?.hbr_km == null ? "Unavailable" : `${pc.hbr_km} km · ${pc.hbr_provenance?.description || "source details unavailable"}`}</strong></span>
      <span>Covariance validation<strong>{pc?.covariance_status || "unavailable"} · {pc?.covariance_frame || assessment.reference_frame || "frame unavailable"} · epoch {pc?.covariance_epoch || assessment.tca_utc || "unavailable"}</strong></span>
      <span>ORION Foster 2D Pc<strong>{isValidProbability(pc?.pc) && pc?.status === "available" ? `COMPUTED · ${formatProbabilityScientific(pc.pc)} · ${formatProbabilityPercentage(pc.pc)} · ${formatProbabilityOdds(pc.pc)}` : `UNAVAILABLE · ${(pc?.reason_codes || []).join(", ") || pc?.status || "no numeric Pc"}`}</strong></span>
      {pc?.probability_classification?.status === "classified" ? <span>Pc reference category<strong>{pc.probability_classification.category} · {pc.probability_classification.explanation}</strong></span> : null}
      <span>CDM-reported Pc (separate source value)<strong>{isValidProbability(assessment.source_reported_pc) ? `SOURCE-REPORTED · ${formatProbabilityScientific(assessment.source_reported_pc)} · ${formatProbabilityPercentage(assessment.source_reported_pc)} · ${formatProbabilityOdds(assessment.source_reported_pc)} · ${assessment.source_reported_pc_method || "method not declared"}` : "Not supplied as a valid probability"}</strong></span>
      <span>Input validation<strong>{pc?.status || "unavailable"} · {pc?.applicability_status || "not assessed"} · covariance {pc?.covariance_status || "unavailable"} · HBR {pc?.hbr_source || "unavailable"}</strong></span>
      {(pc?.assumptions || []).map((assumption, index) => <span key={`assumption-${index}`}>Calculation assumption<strong>{assumption}</strong></span>)}
      {assessment.reference_case ? <>
        <span>Reference source<strong>{assessment.reference_case.name} · {assessment.reference_case.source_url}</strong></span>
        <span>Calculated versus source Pc<strong>{assessment.reference_case.computed_pc ?? "unavailable"} vs {assessment.reference_case.expected_pc ?? "unavailable"} · absolute difference {assessment.reference_case.absolute_difference ?? "unavailable"} · tolerance {assessment.reference_case.comparison_tolerance} · {assessment.reference_case.within_tolerance ? "within tolerance" : "outside tolerance"}</strong></span>
        <span>Comparison rule<strong>{assessment.reference_case.tolerance_basis}</strong></span>
        <span>Reference identity<strong>{assessment.event_id} · {assessment.message_id || "message ID unavailable"} · standalone historical case; not a live screening event</strong></span>
      </> : null}
      <span>Input provenance<strong>{assessment.input_sha256 || "Unavailable"} · {assessment.reference_case ? "bundled public reference fixture; source not authenticated by ORION" : "unauthenticated user-supplied CDM"}</strong></span>
      {(pc?.warnings || []).map((warning, index) => <span key={index}>Warning<strong>{warning}</strong></span>)}
      {assessment.reference_case ? <button className="secondary-action" type="button" disabled={pc?.status !== "available" || !assessmentMatchesCurrentAssumption} onClick={() => onUseReferenceEvent(assessment)}>Open this reference event in Maneuver Assessment</button> : null}
    </div></details> : null}
  </section>;
}
