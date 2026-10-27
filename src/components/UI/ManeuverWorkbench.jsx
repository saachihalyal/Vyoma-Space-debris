import React, { useMemo, useState } from "react";
import { selectedManeuverReportPath } from "../../api/ssaClient";
import { maneuverAssessmentForSelection, maneuverPageState } from "../../utils/maneuverSelection";
import { ManeuverUserUpload } from "./ManeuverUserUpload.jsx";
import { ReferenceManeuverAssessment } from "./ReferenceManeuverAssessment.jsx";

const fixed = (value, digits = 6) => Number.isFinite(value) ? value.toFixed(digits) : "No value returned for this candidate";
function pcText(value) {
  if (Number.isFinite(value?.log10_pc)) return value.log10_pc < -30 ? "< 1e-30" : (value.pc_scientific || `1e${value.log10_pc.toFixed(2)}`);
  return value?.pc ?? "No probability returned for this event";
}
function fuelText(fuel) {
  return fuel?.status === "estimated" && Number.isFinite(fuel.propellant_consumption_kg)
    ? `${fixed(fuel.propellant_consumption_kg, 8)} kg · ${fixed(fuel.initial_mass_kg, 1)} kg spacecraft · ${fixed(fuel.specific_impulse_s, 0)} s Isp`
    : "Fuel estimate appears after a maneuver search.";
}
function CandidateTable({ candidates, expanded, setExpanded }) {
  if (!candidates.length) return <p className="og-sub">Candidate maneuvers will appear here after the search.</p>;
  const shown = expanded ? candidates : candidates.slice(0, 5);
  return <><div className="og-table-wrap"><table className="og-table"><thead><tr><th>Candidate</th><th>Δv (m/s)</th><th>New miss (km)</th><th>Pc after</th><th>Fuel</th></tr></thead><tbody>{shown.map((item, index) => <tr key={`${item.direction}-${item.delta_v_m_s}-${index}`}><td>{item.physics_research_pc_rank ? `Physics candidate ${item.physics_research_pc_rank}` : item.direction || `Candidate ${index + 1}`} · {item.direction || "Direction not recorded"}</td><td>{fixed(item.delta_v_m_s)}</td><td>{fixed(item.predicted_miss_distance_km)}</td><td>{pcText(item.research_pc_after)}</td><td>{fuelText(item.fuel)}</td></tr>)}</tbody></table></div>{candidates.length > 5 && <button type="button" className="og-btn" onClick={() => setExpanded(!expanded)}>{expanded ? "Show top 5" : `Show all ${candidates.length}`}</button>}</>;
}

function ManeuverOptionsTable({ candidates, expanded, setExpanded, baselinePc, recommended }) {
  if (!candidates.length) return <p className="og-sub">Candidate maneuvers will appear after the search.</p>;
  const shown = expanded ? candidates : candidates.slice(0, 5);
  const baselineValue = Number.isFinite(baselinePc?.pc) ? baselinePc.pc : null;
  return <><div className="og-table-wrap"><table className="og-table"><thead><tr><th>Burn (direction, size)</th><th>New miss distance</th><th>Collision probability after</th><th>Reduction</th><th>Fuel</th></tr></thead><tbody>{shown.map((item, index) => {
    const afterValue = item.research_pc_after?.pc;
    const reduction = Number.isFinite(item.percentage_research_pc_reduction) ? item.percentage_research_pc_reduction : Number.isFinite(baselineValue) && baselineValue > 0 && Number.isFinite(afterValue) ? (baselineValue - afterValue) / baselineValue * 100 : null;
    const isRecommended = recommended && (recommended === item || (recommended.direction === item.direction && recommended.delta_v_m_s === item.delta_v_m_s));
    return <tr className={isRecommended ? "maneuver-recommended" : ""} key={`${item.direction}-${item.delta_v_m_s}-${index}`}><td><div>{item.direction || "Direction not recorded"}, {fixed(item.delta_v_m_s)} m/s</div>{isRecommended ? <span className="og-chip maneuver-recommended-badge">Recommended</span> : null}<small>{item.physics_research_pc_rank ? `Physics rank ${item.physics_research_pc_rank}` : ""}{Number.isInteger(item.maneuver_ml_rank) ? ` · AI rank ${item.maneuver_ml_rank}` : ""}</small></td><td>{fixed(item.predicted_miss_distance_km)} km</td><td>{pcText(item.research_pc_after)}</td><td>{reduction === null ? "Requires a valid Pc baseline" : `${reduction.toFixed(2)}%`}</td><td>{fuelText(item.fuel)}</td></tr>;
  })}</tbody></table></div>{candidates.length > 5 && <button type="button" className="og-btn" onClick={() => setExpanded(!expanded)}>{expanded ? "Show top 5" : `Show all ${candidates.length}`}</button>}</>;
}

export function ManeuverWorkbench({ event, events = [], screeningJobId, screeningStatus, screeningAttempt, onSelectEvent = () => {}, onRunManeuver = () => {}, onLoadDemo = () => {}, demoBusy = false, maneuver, download = () => {}, referenceEvent = null, demoAssessment = null, onClearReferenceEvent = () => {} }) {
  const [maxDeltaVMs, setMaxDeltaVMs] = useState("0.05");
  const [rtnDirection, setRtnDirection] = useState("all");
  const [initialMassKg, setInitialMassKg] = useState("500");
  const [specificImpulseS, setSpecificImpulseS] = useState("220");
  const [covarianceScale, setCovarianceScale] = useState("1");
  const [expanded, setExpanded] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState("");
  const pageState = maneuverPageState(event, events, screeningStatus);
  const selected = pageState.selected_event;
  const result = selected ? maneuverAssessmentForSelection(maneuver, screeningJobId, selected) || { status: "not_run" } : {};
  const baseline = result.zero_burn_baseline || {};
  const best = result.best_candidate || result.best_pc_reduction_candidate || null;
  const after = result.probability_after || best?.research_pc_after;
  const before = result.probability_before;
  const pcReduction = Number.isFinite(result.risk_reduction_pct) ? result.risk_reduction_pct : Number.isFinite(best?.percentage_research_pc_reduction) ? best.percentage_research_pc_reduction : null;
  const fuelCostKg = Number.isFinite(result.fuel_cost_kg) ? result.fuel_cost_kg : Number.isFinite((result.fuel || best?.fuel)?.propellant_consumption_kg) ? (result.fuel || best?.fuel).propellant_consumption_kg : null;
  const baselinePc = before || selected?.automatic_research_pc_assessment;
  const allValidEventsBelowFloor = pageState.eligible_events.length > 0 && pageState.eligible_events.every((item) => (
    Number.isFinite(item.automatic_research_pc_assessment?.log10_pc)
    && item.automatic_research_pc_assessment.log10_pc < -30
  ));
  const candidates = useMemo(() => (result.physics_candidates?.candidates || result.candidates || []).filter((candidate) => candidate.delta_v_m_s !== 0).slice().sort((a, b) => (a.physics_research_pc_rank ?? 9999) - (b.physics_research_pc_rank ?? 9999)), [result]);
  const defaultLeadSeconds = 1800;
  const baselineBelowFloor = Number.isFinite(baselinePc?.log10_pc) && baselinePc.log10_pc < -30;
  const objects = [selected?.primary, selected?.secondary].filter(Boolean);
  const sortedEvents = useMemo(() => pageState.selectable_events.slice().sort((a, b) => {
    const ap = a.automatic_research_pc_assessment?.log10_pc;
    const bp = b.automatic_research_pc_assessment?.log10_pc;
    if (Number.isFinite(ap) && Number.isFinite(bp) && ap !== bp) return bp - ap;
    if (Number.isFinite(ap) !== Number.isFinite(bp)) return Number.isFinite(ap) ? -1 : 1;
    return String(a.id).localeCompare(String(b.id));
  }), [pageState.selectable_events]);
  const ranking = result.ml_result || result.surrogate_rank || {};
  const modelReason = ranking.reason_code === "HELD_OUT_RANKING_NOT_USEFUL_VS_BASELINE"
    ? "the ranker did not beat the physics baseline on held-out events"
      : ranking.reason || ranking.score_semantics || "physics ranking used";
  const modelNote = ranking.ranking_used === false
    ? `AI ranking not used: ${modelReason}.`
    : ranking.ranking_used === true ? `AI ranking used: ${ranking.model_name || "maneuver ranker"}.` : "AI ranking status will be reported after the search.";

  function submit(e) {
    e?.preventDefault?.(); setError("");
    onRunManeuver({ leadSeconds: defaultLeadSeconds, maxDeltaVMs: Number(maxDeltaVMs), rtnDirection, initialMassKg: Number(initialMassKg), specificImpulseS: Number(specificImpulseS), covarianceScale: Number(covarianceScale) });
  }

  return <main className="og-page og-maneuver" aria-label="Maneuver Assessment">
    <header className="og-maneuver-header"><div><span className="og-prov derived">Bounded two-body research simulation</span><h1>Avoidance Action Plan</h1><p className="og-sub">Compare candidate burns against the accepted conjunction screening.</p></div>
      {selected && <div className="report-action-group" aria-label="Maneuver report downloads">{["pdf", "csv", "json"].map((format) => <button key={format} type="button" className={`og-btn ${format === "pdf" ? "primary" : ""}`} disabled={!screeningJobId || !["available", "available_with_warning"].includes(result.status)} onClick={() => download(selectedManeuverReportPath(screeningJobId, selected.id, format), `${selected.id}-maneuver-assessment.${format}`)}>Download {format.toUpperCase()}</button>)}</div>}
    </header>
    <div className="og-maneuver-work maneuver-restored-layout">
      <aside className="og-card og-input-card"><span className="og-prov read">Start here</span><h2>Choose an event</h2>
        {sortedEvents.length ? <label className="og-field"><span>Conjunction · from saved screenings · sorted by Pc (highest first)</span><select value={selected?.id || ""} onChange={(e) => onSelectEvent(e.target.value)}>{sortedEvents.map((item) => { const pc = item.automatic_research_pc_assessment; const names = `${item.primary?.name || item.primary?.id} vs ${item.secondary?.name || item.secondary?.id}`; const source = item.screening_library_current ? "Current" : item.screening_run_date ? new Date(item.screening_run_date).toLocaleDateString() : "Saved screening"; return <option key={item.id} value={item.id} disabled={item.physics_result?.status !== "valid"}>{names} · Pc {pcText(pc)} · {source}</option>; })}</select></label> : <p className="og-sub">No valid physical events in saved screenings.</p>}
        <button type="button" className="og-btn" onClick={onLoadDemo} disabled={demoBusy}>{demoBusy ? "Loading NASA example…" : "Try NASA example (Medium risk)"}</button><p className="og-sub">Loads the bundled NASA CARA conjunction case and its reference maneuver assessment.</p>
        <p className="og-sub">Default: one orbit (90 min), 0.05 m/s maximum delta-v, all RTN directions, 500 kg and 220 s Isp.</p>
        <button type="button" className="og-btn primary maneuver-search-button" onClick={submit} disabled={!selected || !screeningJobId || selected.physics_result?.status !== "valid" || baselineBelowFloor || result.status === "running"}>{result.status === "running" ? "Searching for safest maneuver…" : "Find safest maneuver"}</button>
        {selected && <details className="og-acc"><summary>Advanced</summary><div className="og-inputs">
          <label className="og-field"><span>Burn lead time (seconds)</span><input type="number" value={defaultLeadSeconds} disabled /></label>
          <label className="og-field"><span>Maximum delta-v (m/s)</span><input type="number" min="0.0001" max="0.1" step="any" value={maxDeltaVMs} onChange={(e) => setMaxDeltaVMs(e.target.value)} /></label>
          <label className="og-field"><span>Direction</span><select value={rtnDirection} onChange={(e) => setRtnDirection(e.target.value)}>{[["all", "All six signed axes"], ["radial_plus", "Radial +"], ["radial_minus", "Radial −"], ["along_track_plus", "Along-track +"], ["along_track_minus", "Along-track −"], ["cross_track_plus", "Cross-track +"], ["cross_track_minus", "Cross-track −"]].map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <label className="og-field"><span>Spacecraft mass (kg)</span><input type="number" min="0.0001" step="any" value={initialMassKg} onChange={(e) => setInitialMassKg(e.target.value)} /></label>
          <label className="og-field"><span>Specific impulse (s)</span><input type="number" min="0.0001" max="2000" step="any" value={specificImpulseS} onChange={(e) => setSpecificImpulseS(e.target.value)} /></label>
          <label className="og-field"><span>Covariance scale</span><select value={covarianceScale} onChange={(e) => setCovarianceScale(e.target.value)}>{[0.5, 1, 2, 3].map((value) => <option key={value} value={value}>{value}×</option>)}</select></label>
          <ManeuverUserUpload download={download} />
        </div></details>}
      </aside>
      <section className="og-results">
        {allValidEventsBelowFloor ? <p className="og-card og-negligible" role="status">No maneuver needed for screening events below Pc 1e-30. Loading the Sample conjunction (NASA CARA).</p> : null}
        {referenceEvent && <ReferenceManeuverAssessment referenceEvent={referenceEvent} download={download} onClear={onClearReferenceEvent} precomputedAssessment={demoAssessment} />}
        {selected && <><section className="og-card"><h2>Selected event</h2><p>{objects.map((object) => `${object.name || object.id}`).join(" vs ")}</p></section>
          {baselineBelowFloor ? <section className="og-card og-negligible" role="status">No maneuver needed - collision probability is negligible (&lt; 1e-30)</section> : result.status === "running" ? <section className="og-card" role="status">Calculating the baseline and candidate trajectories…</section> : result.status === "unavailable" ? <p className="og-card maneuver-request-error" role="alert">{result.reason || "The maneuver search could not be completed."}</p> : result.status === "not_run" ? <section className="og-card" role="status">Preparing the maneuver search…</section> : <>
            <section className="maneuver-action-kpis" aria-label="Maneuver result summary">{[["Delta-v", Number.isFinite(best?.delta_v_m_s) ? `${fixed(best.delta_v_m_s)} m/s` : "No candidate returned"], ["Burn direction", best?.direction || "No candidate returned"], ["Fuel cost", fuelCostKg === null ? "No estimate returned" : `${fixed(fuelCostKg, 8)} kg`], ["Pc reduction", pcReduction === null ? "No percentage returned" : `${pcReduction.toFixed(2)}%`]].map(([label, value]) => <article className="og-card og-tile" key={label}><span>{label}</span><b>{value}</b></article>)}</section>
            <section className="og-card" aria-label="Before and after maneuver comparison"><div className="og-section-head"><div><span className="og-prov derived">Physics comparison</span><h2>Before and after</h2></div><span className={`og-chip ${result.status === "running" ? "Medium" : "Low"}`}>{["available", "available_with_warning"].includes(result.status) ? "Assessment complete" : result.status || ""}</span></div>
              {pcReduction !== null ? <span className="og-chip maneuver-pc-reduction">Pc reduction {pcReduction.toFixed(2)}%</span> : null}<div className="og-before-after"><article className="og-card og-hero-card"><span>Before</span><strong className="og-pc">{pcText(before)}</strong><small>Research Pc · zero-burn baseline</small><b>{fixed(baseline.miss_distance_km ?? baseline.candidate?.predicted_miss_distance_km)} km</b></article><span className="og-arrow" aria-hidden="true">→</span><article className="og-card og-hero-card"><span>After</span><strong className="og-pc">{pcText(after)}</strong><small>Research Pc · safest physics candidate</small><b>{fixed(best?.predicted_miss_distance_km)} km</b></article></div>
              <p className="og-sub">Pc can fall even if the miss distance shrinks, because uncertainty is larger in one direction.</p>
            </section>
            {result.maneuver?.burn_time_utc ? <section className="og-card"><h2>Burn window</h2><p>Burn time: {result.maneuver.burn_time_utc}</p><p>Pc before: {pcText(before)} · Pc after: {pcText(after)}</p></section> : null}
            <section className="og-card"><h2>Fuel estimate</h2><div className="og-kpi"><div className="og-tile"><span>Propellant</span><b>{fuelText(result.fuel || best?.fuel)}</b></div><div className="og-tile"><span>Assumptions</span><b>500 kg spacecraft · 220 s Isp defaults</b></div></div></section>
            <section className="og-card"><h2>Maneuver options</h2><p>Candidate burns ranked by physics, with AI rank shown when returned.</p><ManeuverOptionsTable candidates={candidates} expanded={showAll} setExpanded={setShowAll} baselinePc={before} recommended={best} /><p className="og-sub">{modelNote}</p></section>
          </>}
        </>}
      </section>
    </div>
  </main>;
}
