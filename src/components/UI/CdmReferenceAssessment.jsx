import React, { useState } from "react";
import { calculateNasaCaraReferenceCase, calculateReferenceCdmPc } from "../../api/ssaClient.js";
import { formatProbabilityOdds, formatProbabilityPercentage, formatProbabilityScientific, isValidProbability } from "./CollisionPcSummary.js";
import { referenceAssessmentMatchesIndependence } from "../../utils/cdmAssessmentState.js";

function plainCdmError(error) {
  const code = error?.message?.match(/CDM_[A-Z0-9_]+/)?.[0] || "";
  if (code.includes("FRAME_UNSUPPORTED") || code.includes("FRAME_MISMATCH")) return "The file uses an incompatible or unsupported reference frame. Provide both object states and covariance in one supported frame (TEME, EME2000, or GCRF).";
  if (["CDM_TCA_STATE_MISSING", "CDM_OBJECT_METADATA_OR_COVARIANCE_MISSING", "CDM_HBR_MISSING", "CDM_MUST_CONTAIN_TWO_SEGMENTS", "CDM_RELATIVE_METADATA_REQUIRED"].includes(code)) return "The conjunction file is incomplete. It must include two object segments, their TCA states and covariance, a TCA, and a hard-body radius.";
  if (code || /parse|xml|json|invalid/i.test(error?.message || "")) return `The conjunction file is malformed or invalid (${code || "INPUT_FORMAT_INVALID"}). Check the file syntax and required fields.`;
  return error?.message || "The conjunction file could not be assessed. Check its format and required fields.";
}

function downloadAssessment(format, assessment) {
  const text = format === "json" ? JSON.stringify(assessment, null, 2) : ["field,value", `event_id,${assessment.event_id || ""}`, `tca_utc,${assessment.tca_utc || ""}`, `event_specific_foster_pc,${assessment.collision_probability?.pc ?? ""}`, `source_reported_pc,${assessment.source_reported_pc ?? ""}`, `status,${assessment.collision_probability?.status || ""}`].join("\r\n");
  const blob = new Blob([text], { type: format === "json" ? "application/json" : "text/csv" });
  const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `${assessment.event_id || "conjunction-report"}.${format}`; link.click(); URL.revokeObjectURL(url);
}

export function CdmReferenceAssessment({ onUseReferenceEvent = () => {}, standalone = false, compact = false }) {
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
      setMessage(standalone ? plainCdmError(error) : error?.message || "CDM assessment was rejected.");
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
  if (compact) return <section className="report-calculation-check" aria-label="NASA CARA calculation check">
    <button className="og-btn" type="button" disabled={busy} onClick={runBundledReference}>{busy ? "Checking..." : "Calculation check"}</button>
    {message ? <p role="status">{message}</p> : null}
  </section>;
  return <section className={`panel cdm-reference-assessment ${standalone ? "upload-page" : ""}`} aria-label="Collision probability calculator">
    {standalone ? <><header className="og-maneuver-header"><div><span className="og-prov read">Conjunction assessment</span><h1>Upload Conjunction Data</h1><p className="og-sub">Validate a conjunction message and calculate its event-specific collision probability.</p></div></header><ol className="upload-steps" aria-label="Upload steps"><li className={!assessment ? "active" : "complete"}>1 · Upload</li><li className={busy ? "active" : assessment ? "complete" : ""}>2 · Validate</li><li className={assessment ? "active" : ""}>3 · Results</li></ol></> : <div className="cdm-reference-heading"><div><span className="reference-eyebrow">Separate reference assessment</span><h2>Collision Probability Calculator</h2>
      <p className="muted">Run the bundled CDM directly. Its results stay separate from live TLE screening events and never replace the selected live event.</p></div>
      {!standalone ? <button className="primary-action" type="button" disabled={busy} onClick={runBundledReference}>{busy ? "Assessing reference..." : "Run bundled reference assessment"}</button> : null}
    </div>}
    {message ? <p className="reference-assessment-status" role="status">{message}</p> : null}
    {!standalone && assessment?.reference_case ? <p className="reference-comparison-caveat">The bundled CDM's rounded Pc is a source value for comparison; agreement here is not independent validation against NASA CARA software.</p> : null}
    {assessment && assessmentMatchesCurrentAssumption ? <div className="reference-result-grid" aria-live="polite">
      <span>TCA<strong>{assessment.tca_utc || "Unavailable"}</strong></span>
      <span>Miss distance<strong>{pc?.miss_distance_km == null ? "Unavailable" : `${Number(pc.miss_distance_km).toFixed(6)} km (Vyoma states)`}{assessment.source_reported_miss_distance_km == null ? "" : ` · ${assessment.source_reported_miss_distance_km} km source`}</strong></span>
      <span>Combined HBR<strong>{pc?.hbr_km == null ? "Unavailable" : `${pc.hbr_km} km`}</strong></span>
      <span>Method<strong>{pc?.method || "Unavailable"}</strong></span>
      <span>Vyoma-computed Pc<strong>{isValidProbability(pc?.pc) && pc?.status === "available" ? `${formatProbabilityScientific(pc.pc)} · ${formatProbabilityPercentage(pc.pc)}` : `Unavailable · ${(pc?.reason_codes || []).join(", ") || pc?.status || "no numeric Pc"}`}</strong></span>
      <span>CDM source-reported Pc<strong>{isValidProbability(assessment.source_reported_pc) ? `${formatProbabilityScientific(assessment.source_reported_pc)} · ${formatProbabilityPercentage(assessment.source_reported_pc)} · ${assessment.source_reported_pc_method || "method undeclared"}` : "Not supplied as a valid probability"}</strong></span>
      {!standalone && assessment.reference_case ? <span>Difference from rounded source Pc<strong>{assessment.reference_case.absolute_difference == null ? "Unavailable" : `${Number(assessment.reference_case.absolute_difference).toExponential(3)} (tolerance ${assessment.reference_case.comparison_tolerance}) · ${assessment.reference_case.within_tolerance ? "within rounding tolerance" : "outside rounding tolerance"}`}</strong></span> : null}
    </div> : null}
    {standalone && assessment && assessmentMatchesCurrentAssumption ? <><div className="upload-provenance-chips"><span className="og-prov read">Read · event identity and state</span><span className="og-prov derived">Derived · Foster Pc</span><span className="og-prov assumed">Assumed · independent covariances</span><span className="og-prov">Missing · report missing values explicitly</span></div><div className="report-action-group" aria-label="Upload report downloads"><button type="button" className="og-btn" onClick={() => window.print()}>Print / Save PDF</button><button type="button" className="og-btn" onClick={() => downloadAssessment("csv", assessment)}>Download CSV</button><button type="button" className="og-btn" onClick={() => downloadAssessment("json", assessment)}>Download JSON</button></div></> : null}
    {assessment && !assessmentMatchesCurrentAssumption ? <p className="muted" role="status">The covariance-independence setting changed after this result. Run the assessment again to refresh it.</p> : null}
    {standalone ? <a className="sample-file-link" href="/sample_conjunction_data.cdm" download>Download sample file</a> : null}
    <details className="optional-cdm-upload" open={standalone}><summary>Upload Conjunction Data</summary>
    <p className="muted">Upload a CCSDS XML, KVN, or JSON conjunction message. The calculator uses the file's object IDs, TCA states, covariance, reference frame, and supplied hard-body radius when compatible. Unsupported frames are explained before a probability is returned. Source labels and originators are not authenticated.</p>
    <form className="readout-list" onSubmit={submit}>
      {!standalone ? <label>CDM source label<input required maxLength={200} value={sourceLabel} onChange={(event) => setSourceLabel(event.target.value)} /></label> : null}
      <label className={standalone ? "upload-dropzone" : ""}>{standalone ? <strong>Drop your conjunction file here or choose a file</strong> : "Conjunction data file (XML, KVN, or JSON)"}<input required type="file" accept=".cdm,.xml,.json,application/json,application/xml,text/xml,text/plain" onChange={async (event) => {
        const file = event.target.files?.[0];
        if (!file) { setCdmText(""); return; }
        if (file.size > 1_000_000) { setCdmText(""); setMessage("CDM input exceeds the 1 MB limit."); return; }
        try { setCdmText(await file.text()); setSourceLabel(file.name); setAssessment(null); setMessage(`Ready to validate ${file.name}.`); } catch { setCdmText(""); setMessage("The selected file could not be read. Choose another file."); }
      }} /></label>
      <label className="filter-checkbox"><input type="checkbox" checked={assumeIndependent} onChange={(event) => {
        setAssumeIndependent(event.target.checked);
        if (assessment) setMessage("The independence assumption changed after this assessment. Submit again to calculate with the checked assumption.");
      }} /> Explicitly assume independent object covariances</label>
      <button className="secondary-action" type="submit" disabled={busy || !cdmText || (!standalone && !sourceLabel.trim())}>{busy ? "Validating..." : standalone ? "Calculate Collision Probability" : "Evaluate standalone CDM Pc"}</button>
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
      <span>Vyoma Foster 2D Pc<strong>{isValidProbability(pc?.pc) && pc?.status === "available" ? `COMPUTED · ${formatProbabilityScientific(pc.pc)} · ${formatProbabilityPercentage(pc.pc)} · ${formatProbabilityOdds(pc.pc)}` : `UNAVAILABLE · ${(pc?.reason_codes || []).join(", ") || pc?.status || "no numeric Pc"}`}</strong></span>
      {pc?.probability_classification?.status === "classified" ? <span>Pc reference category<strong>{pc.probability_classification.category} · {pc.probability_classification.explanation}</strong></span> : null}
      <span>CDM-reported Pc (separate source value)<strong>{isValidProbability(assessment.source_reported_pc) ? `SOURCE-REPORTED · ${formatProbabilityScientific(assessment.source_reported_pc)} · ${formatProbabilityPercentage(assessment.source_reported_pc)} · ${formatProbabilityOdds(assessment.source_reported_pc)} · ${assessment.source_reported_pc_method || "method not declared"}` : "Not supplied as a valid probability"}</strong></span>
      <span>Input validation<strong>{pc?.status || "unavailable"} · {pc?.applicability_status || "not assessed"} · covariance {pc?.covariance_status || "unavailable"} · HBR {pc?.hbr_source || "unavailable"}</strong></span>
      {(pc?.assumptions || []).map((assumption, index) => <span key={`assumption-${index}`}>Calculation assumption<strong>{assumption}</strong></span>)}
      {!standalone && assessment.reference_case ? <>
        <span>Reference source<strong>{assessment.reference_case.name} · {assessment.reference_case.source_url}</strong></span>
        <span>Calculated versus source Pc<strong>{assessment.reference_case.computed_pc ?? "unavailable"} vs {assessment.reference_case.expected_pc ?? "unavailable"} · absolute difference {assessment.reference_case.absolute_difference ?? "unavailable"} · tolerance {assessment.reference_case.comparison_tolerance} · {assessment.reference_case.within_tolerance ? "within tolerance" : "outside tolerance"}</strong></span>
        <span>Comparison rule<strong>{assessment.reference_case.tolerance_basis}</strong></span>
        <span>Reference identity<strong>{assessment.event_id} · {assessment.message_id || "message ID unavailable"} · standalone historical case; not a live screening event</strong></span>
      </> : null}
      <span>Input provenance<strong>{assessment.input_sha256 || "Unavailable"} · user-supplied file; source not authenticated</strong></span>
      {(pc?.warnings || []).map((warning, index) => <span key={index}>Warning<strong>{warning}</strong></span>)}
      {!standalone && assessment.reference_case ? <button className="secondary-action" type="button" disabled={pc?.status !== "available" || !assessmentMatchesCurrentAssumption} onClick={() => onUseReferenceEvent(assessment)}>Open this reference event in Maneuver Assessment</button> : null}
    </div></details> : null}
  </section>;
}
