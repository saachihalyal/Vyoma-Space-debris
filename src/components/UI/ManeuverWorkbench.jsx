import React, { useMemo, useState } from "react";
import { selectedManeuverReportPath } from "../../api/ssaClient";
import { maneuverAssessmentForSelection, maneuverPageState } from "../../utils/maneuverSelection";
import { ManeuverEventContext } from "./ManeuverEventContext.js";
import { ManeuverScreeningContext } from "./ManeuverScreeningContext.js";
import { ManeuverUserUpload } from "./ManeuverUserUpload.jsx";
import { ReferenceManeuverAssessment } from "./ReferenceManeuverAssessment.jsx";

const number = (value, digits = 6) => Number.isFinite(value) ? value.toFixed(digits) : null;
const unavailable = (reason) => `Not calculated: ${reason || "input is unavailable"}`;

function pcValue(record) {
  if (Number.isFinite(record?.log10_pc)) return `${record.log10_pc.toFixed(6)} log10 Pc (${record.pc_scientific || 10 ** record.log10_pc})`;
  return unavailable(record?.reason_code || "research Pc was not calculated");
}

function fuelValue(fuel) {
  if (fuel?.status !== "estimated" || !Number.isFinite(fuel?.propellant_consumption_kg)) return unavailable(fuel?.reason_code || "fuel estimate was not calculated");
  const assumed = fuel.assumption_status === "estimated_from_default_assumptions";
  return `${number(fuel.propellant_consumption_kg, 8)} kg · mass ${number(fuel.initial_mass_kg, 3)} kg · Isp ${number(fuel.specific_impulse_s, 3)} s · ${assumed ? "estimated from default assumptions" : "actual user inputs"}`;
}

function CandidateTable({ candidates, expanded, setExpanded }) {
  if (!candidates.length) return <p className="og-sub">Candidate values will appear after a valid maneuver search.</p>;
  const shown = expanded ? candidates : candidates.slice(0, 5);
  return <>
    <div className="og-table-wrap"><table className="og-table"><thead><tr><th>Scenario</th><th>Δv (m/s)</th><th>New miss (km)</th><th>Pc after</th><th>Reduction</th><th>Fuel</th></tr></thead>
      <tbody>{shown.map((item, index) => <tr key={`${item.direction}-${item.delta_v_m_s}-${index}`}>
        <td>{item.physics_research_pc_rank ? `Physics candidate ${item.physics_research_pc_rank}` : item.direction || `Candidate ${index + 1}`} · {item.direction || "direction unavailable"}</td>
        <td>{number(item.delta_v_m_s, 6) ?? unavailable("delta-v was not calculated")}</td>
        <td>{number(item.predicted_miss_distance_km, 6) ?? unavailable("candidate miss distance was not calculated")}</td>
        <td>{pcValue(item.research_pc_after)}</td>
        <td>{Number.isFinite(item.percentage_research_pc_reduction) ? `${number(item.percentage_research_pc_reduction, 5)}% (${number(item.research_pc_reduction_log10, 6) ?? unavailable("log10 Pc reduction was not calculated")} log10 reduction)` : unavailable(item.research_pc_after?.reason_code || "comparable Pc was not calculated")}</td>
        <td>{fuelValue(item.fuel)}</td>
      </tr>)}</tbody></table></div>
    {candidates.length > 5 ? <button type="button" className="og-btn" onClick={() => setExpanded(!expanded)}>{expanded ? "Show top 5" : `Show all ${candidates.length}`}</button> : null}
  </>;
}

export function ManeuverWorkbench({ event, events = [], screeningJobId, screeningStatus, screeningAttempt, onSelectEvent = () => {}, onRunManeuver = () => {}, maneuver, download = () => {}, referenceEvent = null, onClearReferenceEvent = () => {} }) {
  const [leadSeconds, setLeadSeconds] = useState("5400");
  const [customLead, setCustomLead] = useState("5400");
  const [maxDeltaVMs, setMaxDeltaVMs] = useState("0.05");
  const [rtnDirection, setRtnDirection] = useState("all");
  const [initialMassKg, setInitialMassKg] = useState("");
  const [specificImpulseS, setSpecificImpulseS] = useState("");
  const [covarianceScale, setCovarianceScale] = useState("1");
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState("");
  const pageState = maneuverPageState(event, events, screeningStatus);
  const selected = pageState.selected_event;
  const result = selected ? maneuverAssessmentForSelection(maneuver, screeningJobId, selected) || { status: "not_run" } : {};
  const baseline = result.zero_burn_baseline || {};
  const best = result.best_candidate || result.best_pc_reduction_candidate || null;
  const after = result.probability_after || best?.research_pc_after;
  const before = result.probability_before;
  const candidates = useMemo(() => (result.physics_candidates?.candidates || result.candidates || [])
    .filter((candidate) => candidate.delta_v_m_s !== 0)
    .slice().sort((a, b) => (a.physics_research_pc_rank ?? 9999) - (b.physics_research_pc_rank ?? 9999)), [result]);
  const changeLog = Number.isFinite(before?.log10_pc) && Number.isFinite(after?.log10_pc) ? after.log10_pc - before.log10_pc : null;
  const reductionPct = Number.isFinite(result.risk_reduction_pct) ? result.risk_reduction_pct : (Number.isFinite(changeLog) ? 100 * (1 - 10 ** changeLog) : null);
  const delta = best?.delta_v_rtn_m_s || [];
  const fuel = result.fuel || best?.fuel;
  const mlStatus = result.ml_result || result.surrogate_rank || {};
  const rankingUsed = mlStatus.ranking_used === true;
  const heldOut = mlStatus.evaluation_summary || {};
  const modelNote = rankingUsed
    ? `AI ranking: used · ${mlStatus.model_name || "maneuver ranker"} ${mlStatus.model_version || ""}`
    : mlStatus.ranking_used === false
      ? `AI ranking: not used - ${mlStatus.reason_code === "HELD_OUT_RANKING_NOT_USEFUL_VS_BASELINE" ? "the ranker did not beat the physics baseline on held-out events" : (mlStatus.reason || mlStatus.score_semantics || "the model status reports physics ranking")}${Number.isFinite(heldOut.model_mean_regret_log10_pc_reduction) && Number.isFinite(heldOut.baseline_mean_regret_log10_pc_reduction) ? ` (${heldOut.model_mean_regret_log10_pc_reduction.toFixed(6)} vs ${heldOut.baseline_mean_regret_log10_pc_reduction.toFixed(6)} log10 regret)` : ""}`
      : "AI ranking status will be reported by the maneuver model response after the search.";

  function submit(e) {
    e.preventDefault();
    if ((initialMassKg === "") !== (specificImpulseS === "")) { setError("Enter both mass and Isp, or leave both empty to use the stated defaults."); return; }
    setError("");
    onRunManeuver({ leadSeconds: Number(leadSeconds), maxDeltaVMs: Number(maxDeltaVMs), rtnDirection,
      initialMassKg: initialMassKg === "" ? null : Number(initialMassKg),
      specificImpulseS: specificImpulseS === "" ? null : Number(specificImpulseS), covarianceScale: Number(covarianceScale) });
  }

  const baselineBelowFloor = Number.isFinite(before?.log10_pc) && before.log10_pc < -30;
  const computedShiftM = Number.isFinite(best?.change_from_zero_burn_km) ? best.change_from_zero_burn_km * 1000 : null;
  const sanityEstimate = best?.along_track_sanity_check?.estimated_displacement_m;

  return <main className="og-page og-maneuver" aria-label="Maneuver Assessment">
    <header className="og-maneuver-header"><div><span className="og-prov derived">Bounded two-body research simulation</span><h1>Maneuver Assessment</h1><p className="og-sub">Compare a bounded impulsive RTN maneuver against the zero-burn baseline. This is not operational maneuver guidance.</p></div>
      <div className="report-action-group" aria-label="Maneuver report downloads">{["pdf", "csv", "json"].map((format) => <button key={format} type="button" className={`og-btn ${format === "pdf" ? "primary" : ""}`} disabled={!selected || !screeningJobId || !["available", "available_with_warning"].includes(result.status)} onClick={() => selected && download(selectedManeuverReportPath(screeningJobId, selected.id, format), `${selected.id}-maneuver-assessment.${format}`)}>Download {format.toUpperCase()}</button>)}</div>
    </header>
    <ManeuverScreeningContext screeningJobId={screeningJobId} screeningStatus={screeningStatus} screeningAttempt={screeningAttempt} />
    <div className="og-work og-maneuver-work">
      <aside className="og-card og-input-card"><span className="og-prov read">Configuration</span><h2>Inputs</h2>
        {pageState.selectable_events.length ? <label className="og-field"><span>Event</span><select value={selected?.id || ""} onChange={(e) => onSelectEvent(e.target.value)}>{pageState.selectable_events.map((item) => <option key={item.id} value={item.id} disabled={item.physics_result?.status !== "valid"}>{item.id} · {item.primary?.name || item.primary?.id} vs {item.secondary?.name || item.secondary?.id} · {item.physics_result?.status || "unknown"}</option>)}</select></label> : <p className="og-sub">{pageState.empty_text}</p>}
        {selected ? <form className="og-inputs" onSubmit={submit}>
          <fieldset className="og-preset"><legend>Burn lead time</legend>{[["300", "5 min"], ["1800", "30 min"], ["5400", "90 min · one orbit"], ["10800", "3 hours"]].map(([seconds, label]) => <button key={seconds} type="button" className={`og-btn ${leadSeconds === seconds ? "primary" : ""}`} onClick={() => { setLeadSeconds(seconds); setCustomLead(seconds); }}>{label}</button>)}</fieldset>
          <label className="og-field"><span>Custom lead time (seconds)</span><input type="number" min="60" max="10800" step="1" value={customLead} onChange={(e) => { setCustomLead(e.target.value); setLeadSeconds(e.target.value); }} required /></label>
          <label className="og-field"><span>Maximum delta-v (m/s)</span><input type="number" min="0.0001" max="0.1" step="any" value={maxDeltaVMs} onChange={(e) => setMaxDeltaVMs(e.target.value)} required /></label>
          <label className="og-field"><span>RTN direction</span><select value={rtnDirection} onChange={(e) => setRtnDirection(e.target.value)}>{[["all", "All six signed axes"], ["radial_plus", "Radial +"], ["radial_minus", "Radial −"], ["along_track_plus", "Along-track +"], ["along_track_minus", "Along-track −"], ["cross_track_plus", "Cross-track +"], ["cross_track_minus", "Cross-track −"]].map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <label className="og-field"><span>Optional spacecraft mass (kg)</span><input type="number" min="0.0001" step="any" value={initialMassKg} onChange={(e) => setInitialMassKg(e.target.value)} /></label>
          <label className="og-field"><span>Optional specific impulse (s)</span><input type="number" min="0.0001" max="2000" step="any" value={specificImpulseS} onChange={(e) => setSpecificImpulseS(e.target.value)} /></label>
          <p className="og-sub">If both fuel inputs are empty, fuel is estimated from default assumptions: 500 kg and 220 s Isp.</p>
          <label className="og-field"><span>Uncertainty-scale what-if</span><select value={covarianceScale} onChange={(e) => setCovarianceScale(e.target.value)}>{[0.5, 1, 2, 3].map((v) => <option key={v} value={v}>{v}×{v === 1 ? " · baseline" : ""}</option>)}</select></label>
          <button type="submit" className="og-btn primary" disabled={!screeningJobId || selected.physics_result?.status !== "valid" || result.status === "running"}>{result.status === "running" ? "Searching…" : "Run maneuver search"}</button>
          {error ? <p role="alert">{error}</p> : null}
        </form> : null}
      </aside>
      <section className="og-results">
        {referenceEvent ? <ReferenceManeuverAssessment referenceEvent={referenceEvent} download={download} onClear={onClearReferenceEvent} /> : null}
        {selected ? <section className="og-card"><h2>Catalog object types</h2><div className="og-kpi">{[selected.primary, selected.secondary].map((object) => <div className="og-tile" key={object.id}><span>{object.name || object.id} · {object.id}</span><b>{object.object_type || "UNKNOWN"} · {object.classification_source || "classification source unavailable"}</b></div>)}</div><p className="og-sub">Catalog classification is separate from collision-risk severity.</p></section> : null}
        {selected ? <ManeuverEventContext event={selected} context={result.event_context} /> : null}
        <section className="og-card" aria-label="Before and after maneuver comparison"><div className="og-section-head"><div><span className="og-prov derived">Physics comparison</span><h2>Before vs After</h2></div><span className={`og-chip ${result.status === "running" ? "Medium" : "Low"}`}>{result.status || "not run"}</span></div>
          {result.status === "running" ? <p role="status" className="og-sub">Calculating trajectory, Pc and fuel values.</p> : null}
          {baselineBelowFloor ? <p className="og-negligible">Baseline already negligible (log10 Pc = {before.log10_pc.toFixed(6)}); no maneuver needed</p> : null}
          <div className="og-before-after"><article className="og-card og-hero-card"><span>Before</span><strong className="og-pc">{pcValue(before)}</strong><small>Research Pc · zero-burn baseline</small><b>{number(baseline.miss_distance_km, 6) ?? number(baseline.candidate?.predicted_miss_distance_km, 6) ?? "Not calculated: baseline miss distance unavailable"} km</b></article>
            <span className="og-arrow" aria-hidden="true">→</span>
            <article className="og-card og-hero-card"><span>After</span><strong className="og-pc">{pcValue(after)}</strong><small>Research Pc · best physics candidate</small><b>{number(best?.predicted_miss_distance_km, 6) ?? "Not calculated: candidate miss distance unavailable"} km</b></article></div>
          <div className="og-change"><span>Pc change</span><strong>{Number.isFinite(reductionPct) ? `${number(reductionPct, 5)}% reduction` : unavailable(result.probability_comparison?.reason_code || "comparable before/after Pc unavailable")}</strong><small>{Number.isFinite(changeLog) ? `${changeLog.toFixed(6)} log10 Pc (after − before)` : unavailable("before and after log10 Pc are required")}</small></div>
        </section>
        <section className="og-card"><h2>Fuel estimate</h2><div className="og-kpi"><div className="og-tile"><span>Propellant mass</span><b>{fuelValue(fuel)}</b></div><div className="og-tile"><span>Input provenance</span><b>{fuel?.assumption_status === "estimated_from_default_assumptions" ? "Estimated from default assumptions" : fuel?.status === "estimated" ? "Actual user inputs" : unavailable(fuel?.reason_code)}</b></div></div></section>
        <div className="og-kpis">{[["New TCA", best?.closest_approach_utc || unavailable("candidate TCA unavailable")], ["Relative velocity", best?.relative_velocity_km_s?.map((v) => Number(v).toFixed(6)).join(", ") ? `${best.relative_velocity_km_s.map((v) => Number(v).toFixed(6)).join(", ")} km/s` : unavailable("candidate velocity unavailable")], ["Delta-v magnitude", Number.isFinite(best?.delta_v_m_s) ? `${number(best.delta_v_m_s, 6)} m/s` : unavailable("no candidate burn")], ["RTN components (R, T, N)", delta.length === 3 ? `${delta.map((v) => Number(v).toFixed(6)).join(", ")} m/s` : unavailable("candidate components unavailable")], ["Burn epoch", best?.maneuver_epoch_utc || unavailable("candidate burn epoch unavailable")]].map(([label, value]) => <div className="og-card og-tile" key={label}><span>{label}</span><b>{value}</b></div>)}</div>
        <section className="og-card"><h2>Physics-ranked candidates</h2><CandidateTable candidates={candidates} expanded={expanded} setExpanded={setExpanded} /><p className="og-sub">{modelNote}</p></section>
        <details className="og-acc"><summary>Assumptions and sanity check</summary><dl className="og-kv"><dt>Shared covariance</dt><dd>The same baseline TEME covariance matrices and HBR are reused for baseline and candidates; only relative mean geometry changes. This is a research what-if, not propagated uncertainty.</dd><dt>Along-track estimate (3 × Δv × Δt)</dt><dd>{Number.isFinite(sanityEstimate) ? `${number(sanityEstimate, 6)} m` : unavailable("selected candidate is not an along-track maneuver")}</dd><dt>Computed miss-distance shift</dt><dd>{Number.isFinite(computedShiftM) ? `${number(computedShiftM, 6)} m` : unavailable("candidate and baseline miss distances are required")}</dd><dt>Comparison</dt><dd>{Number.isFinite(sanityEstimate) && Number.isFinite(computedShiftM) ? `Estimate ${number(sanityEstimate, 6)} m compared with computed shift ${number(computedShiftM, 6)} m; the estimate is first-order only.` : unavailable("both along-track estimate and computed shift are required")}</dd></dl></details>
        {selected ? <ManeuverUserUpload download={download} /> : null}
      </section>
    </div>
  </main>;
}
