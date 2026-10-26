import React, { useState } from "react";
import { uploadManeuverEvent } from "../../api/ssaClient";
import { selectedManeuverReportPath } from "../../api/ssaClient";
import { ManeuverBaselineComparison } from "./ManeuverBaselineComparison.js";

export function ManeuverUserUpload({ download = () => {} }) {
  const [file, setFile] = useState(null);
  const [leadSeconds, setLeadSeconds] = useState("5400");
  const [burnMagnitudeMs, setBurnMagnitudeMs] = useState("0.01");
  const [rtnDirection, setRtnDirection] = useState("all");
  const [initialMassKg, setInitialMassKg] = useState("");
  const [specificImpulseS, setSpecificImpulseS] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setError(""); setResult(null); setBusy(true);
    try { setResult(await uploadManeuverEvent(file, { leadSeconds: Number(leadSeconds), burnMagnitudeMs: Number(burnMagnitudeMs), rtnDirection, initialMassKg: initialMassKg === "" ? null : Number(initialMassKg), specificImpulseS: specificImpulseS === "" ? null : Number(specificImpulseS) })); }
    catch (reason) { setError(`${reason.message}${reason.reasonCode ? ` (${reason.reasonCode})` : ""}`); }
    finally { setBusy(false); }
  }
  const data = result?.data;
  return <section className="panel" aria-labelledby="maneuver-user-upload-title">
    <div className="panel-heading"><h2 id="maneuver-user-upload-title">Upload conjunction data for maneuver</h2></div>
    <p className="muted">Upload one canonical Vyoma event as JSON, or one CSV row with an <code>event_json</code> column containing that event. Required: user_supplied provenance, valid UTC TCA, matching TEME Cartesian states in km and km/s, and both TLE element epochs. No states are inferred.</p>
    <form className="maneuver-search-form" onSubmit={submit}>
      <label>Conjunction file<input type="file" accept=".json,.csv,application/json,text/csv" onChange={(event) => setFile(event.target.files?.[0] || null)} /></label>
      <label>Burn lead before TCA (s)<input type="number" min="60" max="10800" value={leadSeconds} onChange={(event) => setLeadSeconds(event.target.value)} required /></label>
      <label>Delta-v magnitude (m/s)<input type="number" min="0.0001" max="0.1" step="any" value={burnMagnitudeMs} onChange={(event) => setBurnMagnitudeMs(event.target.value)} required /></label>
      <label>RTN direction<select value={rtnDirection} onChange={(event) => setRtnDirection(event.target.value)}><option value="all">All signed axes</option><option value="radial_plus">Radial +</option><option value="radial_minus">Radial −</option><option value="along_track_plus">Along-track +</option><option value="along_track_minus">Along-track −</option><option value="cross_track_plus">Cross-track +</option><option value="cross_track_minus">Cross-track −</option></select></label>
      <label>Initial mass (kg), optional<input type="number" min="0.0001" step="any" value={initialMassKg} onChange={(event) => setInitialMassKg(event.target.value)} /></label>
      <label>Specific impulse (s), optional<input type="number" min="0.0001" max="2000" step="any" value={specificImpulseS} onChange={(event) => setSpecificImpulseS(event.target.value)} /></label>
      <button className="secondary-action" type="submit" disabled={!file || busy}>{busy ? "Calculating…" : "Validate and Assess Uploaded Event"}</button>
    </form>
    {error ? <p role="alert" className="muted">{error}</p> : null}
    {data ? <>
      <p role="status" className="muted">Validated event {data.event_id}; job {result.screening_job_id}; input provenance: user supplied. Research propagation and Pc limitations are shown below.</p>
      <div className="report-action-group" aria-label="Uploaded maneuver report downloads">
        {(["pdf", "csv", "json"]).map((format) => <button className="secondary-action" type="button" key={format} onClick={() => download(selectedManeuverReportPath(result.screening_job_id, data.event_id, format), `${data.event_id}-maneuver-report.${format}`)}>Download {format.toUpperCase()}</button>)}
      </div>
      <ManeuverBaselineComparison comparison={data.baseline_reference_comparison} stage2aReference={data.stage2a_reference} zeroBurnBaseline={data.zero_burn_baseline} candidates={data.physics_candidates?.candidates || data.candidates || []} stage2aPhysics={data.stage2a_reference} probabilityBefore={data.probability_before} probabilityAfter={data.probability_after} probabilityComparison={data.probability_comparison} />
    </> : null}
  </section>;
}
