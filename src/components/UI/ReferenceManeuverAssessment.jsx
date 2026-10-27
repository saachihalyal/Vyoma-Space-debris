import { useEffect, useState } from "react";
import { calculateReferenceManeuver, referenceManeuverReportPath } from "../../api/ssaClient.js";

const DIRECTIONS = ["radial+", "radial-", "along_track+", "along_track-", "cross_track+", "cross_track-"];
const formatPc = (value) => Number.isFinite(Number(value)) ? Number(value).toExponential(4) : "Unavailable";

export function ReferenceManeuverAssessment({ referenceEvent, download, onClear = () => {}, precomputedAssessment = null }) {
  const [objectId, setObjectId] = useState("");
  const [leadSeconds, setLeadSeconds] = useState("1800");
  const [direction, setDirection] = useState("along_track+");
  const [deltaVMs, setDeltaVMs] = useState("0.05");
  const [assessment, setAssessment] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const objects = [referenceEvent?.object_1, referenceEvent?.object_2].filter((item) => item?.id);

  useEffect(() => {
    setAssessment(precomputedAssessment?.data ? precomputedAssessment : null);
    setMessage(precomputedAssessment?.error || (precomputedAssessment?.data ? "Before/after demo assessment complete using the CDM covariance held fixed at both encounter times." : ""));
    setObjectId(objects[0]?.id || "");
  }, [referenceEvent?.event_id, precomputedAssessment]);

  if (!referenceEvent?.event_id || !objects.length) return null;

  async function submit(event) {
    event?.preventDefault();
    setBusy(true);
    setAssessment(null);
    setMessage("Propagating the specified impulse with the bounded two-body research model...");
    try {
      const response = await calculateReferenceManeuver({
        eventId: referenceEvent.event_id,
        maneuveringObjectId: objectId,
        burnLeadSeconds: leadSeconds,
        direction,
        deltaVMs,
      });
      setAssessment({ data: response.data, parameters: { eventId: referenceEvent.event_id, maneuveringObjectId: objectId, burnLeadSeconds: leadSeconds, direction, deltaVMs } });
      setMessage("Before/after Pc comparison ready using the CDM covariance held fixed at both encounter times.");
    } catch (error) {
      setMessage(error?.message || "Reference maneuver assessment failed validation.");
    } finally {
      setBusy(false);
    }
  }

  const data = assessment?.data;
  const candidate = data?.candidate_two_body_geometry;
  const pcAfter = data?.probability_after;
  return <section className="panel reference-maneuver-assessment">
    <h3>DEMO · public sample conjunction</h3>
    <p className="muted">The bundled NASA CARA CDM is assessed with a 1,800-second lead time, 0.05 m/s along-track burn, and the bounded two-body research model.</p>
    <p className="muted">AI ranking not used: this standalone CDM comparison evaluates one specified burn, not a candidate-ranking search.</p>
    <button className="secondary-action" type="button" onClick={onClear}>Clear selected reference event</button>
    <form className="readout-list" onSubmit={submit}>
      <details><summary>Advanced demo settings</summary><label>Maneuvering object<select required value={objectId} onChange={(event) => setObjectId(event.target.value)}>{objects.map((object) => <option key={object.id} value={object.id}>{object.name || object.id} · {object.id}</option>)}</select></label><label>Burn lead before reference TCA (seconds)<input required type="number" min="60" max="10800" step="1" value={leadSeconds} onChange={(event) => setLeadSeconds(event.target.value)} /></label><label>Impulse direction in burn-epoch RTN<select value={direction} onChange={(event) => setDirection(event.target.value)}>{DIRECTIONS.map((value) => <option key={value} value={value}>{value.replace("_", " ")}</option>)}</select></label><label>Δv magnitude (m/s)<input required type="number" min="0.000001" max="0.1" step="0.001" value={deltaVMs} onChange={(event) => setDeltaVMs(event.target.value)} /></label></details>
      {!precomputedAssessment?.data && <button className="secondary-action" type="submit" disabled={busy || !objectId}>{busy ? "Finding safest maneuver…" : "Find safest maneuver"}</button>}
    </form>
    {message ? <p className="muted" role={precomputedAssessment?.error ? "alert" : "status"}>{message}</p> : null}
    {data ? <div className="readout-list" aria-live="polite">
      <span>Event / source<strong>{data.event_id} · {data.source} · SHA-256 {data.source_input_sha256}</strong></span>
      <span>Frame / state units<strong>{data.reference_frame} · position {data.state_units.position} · velocity {data.state_units.velocity} · TCA {data.tca_utc}</strong></span>
      <span>Covariance / HBR inputs<strong>Covariance {data.covariance.status}, {data.covariance.frame} at {data.covariance.epoch_utc} ({data.covariance.units}); combined HBR {data.hard_body_radius.value} {data.hard_body_radius.units} ({data.hard_body_radius.source_type})</strong></span>
      <span>Burn<strong>{data.maneuver.burn_time_utc} · {data.maneuver.object_id} · {data.maneuver.direction} RTN · {data.maneuver.delta_v_m_s} m/s</strong></span>
      <span>CDM miss distance<strong>{data.original_reference_geometry.miss_distance_km} km at source TCA {data.original_reference_geometry.tca_utc}</strong></span>
      <span>Zero-burn two-body baseline<strong>{data.zero_burn_two_body_baseline.miss_distance_km} km miss distance · {data.zero_burn_two_body_baseline.relative_velocity_km_s} km/s relative speed · TCA {data.zero_burn_two_body_baseline.tca_utc}</strong></span>
      <span>Candidate two-body geometry<strong>{candidate.miss_distance_km} km miss distance · {candidate.relative_velocity_km_s} km/s relative speed · TCA {candidate.tca_utc}</strong></span>
      <span>Geometric miss-distance change<strong>{candidate.change_from_zero_burn_baseline_km} km relative to the zero-burn two-body baseline</strong></span>
      <span>Before Pc<strong>{formatPc(data.probability_before.pc)} · {data.probability_before.status} · zero-burn two-body baseline</strong></span>
      <span>After Pc<strong>{formatPc(pcAfter.pc)} · {pcAfter.status} · candidate encounter</strong></span>
      <span>Pc reduction<strong>{data.probability_change?.percentage_reduction == null ? "Unavailable" : `${data.probability_change.percentage_reduction.toFixed(2)}%`} · {data.probability_change?.status} · same CDM covariance held fixed</strong></span>
      {data.assumptions.map((item, index) => <span key={`assumption-${index}`}>Assumption<strong>{item}</strong></span>)}
      {data.limitations.map((item, index) => <span key={`limit-${index}`}>Limitation<strong>{item}</strong></span>)}
      <button className="secondary-action" type="button" onClick={() => download(referenceManeuverReportPath(assessment.parameters), `${data.event_id}-reference-maneuver-assessment.pdf`)}>Download Reference Maneuver Report</button>
    </div> : null}
  </section>;
}
