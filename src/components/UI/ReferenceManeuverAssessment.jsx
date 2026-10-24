import { useEffect, useState } from "react";
import { calculateReferenceManeuver, referenceManeuverReportPath } from "../../api/ssaClient.js";

const DIRECTIONS = ["radial+", "radial-", "along_track+", "along_track-", "cross_track+", "cross_track-"];

export function ReferenceManeuverAssessment({ referenceEvent, download, onClear = () => {} }) {
  const [objectId, setObjectId] = useState("");
  const [leadSeconds, setLeadSeconds] = useState("300");
  const [direction, setDirection] = useState("along_track+");
  const [deltaVMs, setDeltaVMs] = useState("0.05");
  const [assessment, setAssessment] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const objects = [referenceEvent?.object_1, referenceEvent?.object_2].filter((item) => item?.id);

  useEffect(() => {
    setAssessment(null);
    setMessage("");
    setObjectId(objects[0]?.id || "");
  }, [referenceEvent?.event_id]);

  if (!referenceEvent?.reference_case || !referenceEvent?.event_id || !objects.length) return null;

  async function submit(event) {
    event.preventDefault();
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
      setMessage("Trajectory-only maneuver result ready. Post-maneuver Pc remains unavailable.");
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
    <h3>Standalone Reference CDM Maneuver</h3>
    <p className="muted">This historical EME2000 event is separate from CelesTrak screening. Select the object, burn lead from reference TCA, RTN direction, and impulse magnitude. Results are exploratory two-body geometry only.</p>
    <button className="secondary-action" type="button" onClick={onClear}>Clear selected reference event</button>
    <form className="readout-list" onSubmit={submit}>
      <label>Maneuvering object<select required value={objectId} onChange={(event) => setObjectId(event.target.value)}>{objects.map((object) => <option key={object.id} value={object.id}>{object.name || object.id} · {object.id}</option>)}</select></label>
      <label>Burn lead before reference TCA (seconds)<input required type="number" min="60" max="1800" step="1" value={leadSeconds} onChange={(event) => setLeadSeconds(event.target.value)} /></label>
      <label>Impulse direction in burn-epoch RTN<select value={direction} onChange={(event) => setDirection(event.target.value)}>{DIRECTIONS.map((value) => <option key={value} value={value}>{value.replace("_", " ")}</option>)}</select></label>
      <label>Δv magnitude (m/s)<input required type="number" min="0.000001" max="0.1" step="0.001" value={deltaVMs} onChange={(event) => setDeltaVMs(event.target.value)} /></label>
      <button className="secondary-action" type="submit" disabled={busy || !objectId}>{busy ? "Propagating..." : "Evaluate reference maneuver"}</button>
    </form>
    {message ? <p className="muted" role="status">{message}</p> : null}
    {data ? <div className="readout-list" aria-live="polite">
      <span>Event / source<strong>{data.event_id} · {data.source} · SHA-256 {data.source_input_sha256}</strong></span>
      <span>Frame / state units<strong>{data.reference_frame} · position {data.state_units.position} · velocity {data.state_units.velocity} · TCA {data.tca_utc}</strong></span>
      <span>Covariance / HBR inputs<strong>Covariance {data.covariance.status}, {data.covariance.frame} at {data.covariance.epoch_utc} ({data.covariance.units}); combined HBR {data.hard_body_radius.value} {data.hard_body_radius.units} ({data.hard_body_radius.source_type})</strong></span>
      <span>Burn<strong>{data.maneuver.burn_time_utc} · {data.maneuver.object_id} · {data.maneuver.direction} RTN · {data.maneuver.delta_v_m_s} m/s</strong></span>
      <span>CDM miss distance<strong>{data.original_reference_geometry.miss_distance_km} km at source TCA {data.original_reference_geometry.tca_utc}</strong></span>
      <span>Zero-burn two-body baseline<strong>{data.zero_burn_two_body_baseline.miss_distance_km} km miss distance · {data.zero_burn_two_body_baseline.relative_velocity_km_s} km/s relative speed · TCA {data.zero_burn_two_body_baseline.tca_utc}</strong></span>
      <span>Candidate two-body geometry<strong>{candidate.miss_distance_km} km miss distance · {candidate.relative_velocity_km_s} km/s relative speed · TCA {candidate.tca_utc}</strong></span>
      <span>Geometric miss-distance change<strong>{candidate.change_from_zero_burn_baseline_km} km · {candidate.percentage_change_status === "available" ? `${candidate.change_from_zero_burn_baseline_percent}%` : candidate.percentage_change_status} relative to the zero-burn two-body baseline (positive means increased miss distance)</strong></span>
      <span>Original reference Pc<strong>{data.probability_before.pc ?? "unavailable"} · {data.probability_before.status} · original CDM TCA only; not a post-burn comparison</strong></span>
      <span>Post-maneuver Pc / Pc change<strong>{pcAfter.pc ?? "Unavailable"} · {pcAfter.reason_code} · covariance is not propagated through the burn</strong></span>
      <span>Fuel / feasibility<strong>Unavailable · mass and propulsion data not supplied</strong></span>
      {data.assumptions.map((item, index) => <span key={`assumption-${index}`}>Assumption<strong>{item}</strong></span>)}
      {data.limitations.map((item, index) => <span key={`limit-${index}`}>Limitation<strong>{item}</strong></span>)}
      <button className="secondary-action" type="button" onClick={() => download(referenceManeuverReportPath(assessment.parameters), `${data.event_id}-reference-maneuver-assessment.pdf`)}>Download Reference Maneuver Report</button>
    </div> : null}
  </section>;
}
