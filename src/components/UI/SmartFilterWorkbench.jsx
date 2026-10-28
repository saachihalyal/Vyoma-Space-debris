import React from "react";
import { getPhysicalSmartFilter, physicalSmartFilterCsvPath } from "../../api/ssaClient.js";

const BrowserGlobe = React.lazy(() => import("../Scene/SmartFilterGlobe.jsx").then((m) => ({ default: m.SmartFilterGlobe })));
const number = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : "";
const pairName = (row) => (row.object_names || row.object_ids || []).join(" vs ");

export function SmartFilterWorkbench({ acceptedJob: initialAcceptedJob = null, download = () => {} }) {
  const acceptedJob = initialAcceptedJob;
  const [data, setData] = React.useState(null);
  const [progress, setProgress] = React.useState({ stage: "loading", percent: null, message: "Loading the accepted screening and Smart Filter status." });
  React.useEffect(() => {
    const controller = new AbortController();
    if (!initialAcceptedJob?.job_id) { setProgress({ stage: "waiting", percent: null, message: "Waiting for the accepted screening job." }); return undefined; }
    let timer;
    const poll = async () => {
      if (controller.signal.aborted) return;
      try {
      const result = await getPhysicalSmartFilter(initialAcceptedJob.job_id, { signal: controller.signal });
        if (controller.signal.aborted) return;
      if (result.status === "computing") setProgress(result.progress || { stage: "evaluating_events", percent: null, message: "Smart Filter evaluation is running." });
      else { setData(result); setProgress({ stage: "complete", percent: 100, message: "Smart Filter evaluation complete." }); return; }
      } catch (e) {
        if (e.name === "AbortError" || controller.signal.aborted) return;
        setProgress({ stage: "retrying", percent: null, message: "Checking Smart Filter progress; the next check will retry automatically." });
      }
      timer = setTimeout(poll, 3000);
    };
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [initialAcceptedJob?.job_id]);
  const jobId = acceptedJob?.job_id || null;
  const decisions = data?.decisions || [];
  const events = (acceptedJob?.result?.data || []).filter((event) => event.result_kind === "physics_assessment");
  const eventById = new Map(events.map((event) => [event.id, event]));
  const objects = new Map(events.flatMap((event) => [[event.primary?.id, event.primary], [event.secondary?.id, event.secondary]]).filter(([id, object]) => id && object));
  const isExcluded = (row) => {
    const event = eventById.get(row.event_id);
    const physics = event?.physics_result || {};
    const reasons = [...(physics.reason_codes || []), ...(event?.provenance?.reason_codes || [])].join(" ").toLowerCase();
    return !event || physics.status !== "valid" || ["invalid", "unavailable"].includes(physics.tca_status) || /docked|identical_propagation_parameters|duplicate_tle_state/.test(reasons);
  };
  const excludedRows = decisions.filter(isExcluded);
  const rows = decisions.filter((row) => !isExcluded(row));
  const globePositions = data?.globe_positions && typeof data.globe_positions === "object" ? data.globe_positions : {};
  const beforeObjects = globePositions.before_objects || [];
  const afterObjects = globePositions.after_objects || [];
  const propagationEpoch = globePositions.propagation_epoch || null;
  const policy = data?.policy || {};
  const physicsDecision = (row) => {
    const miss = row.miss_distance_km;
    const pcLog = row.maximum_scenario_log10_pc;
    const threshold = Number(policy.physics_keep_pc_threshold ?? policy.significant_pc_threshold);
    const guarded = row.safety_guard_retained || !Number.isFinite(miss) || miss <= Number(policy.safety_miss_distance_threshold_km || 1);
    return guarded || !Number.isFinite(pcLog) || !(threshold > 0) || pcLog >= Math.log10(threshold) ? "retain" : "filter";
  };
  const aiDecision = (row) => !String(row.model_status || "").startsWith("available") ? "unavailable" : row.model_prediction === "significant" ? "retain" : "filter";
  const physicsKept = rows.filter((row) => physicsDecision(row) === "retain").length;
  const physicsFiltered = rows.length - physicsKept;
  const aiKept = rows.filter((row) => aiDecision(row) === "retain").length;
  const aiAvailable = rows.filter((row) => aiDecision(row) !== "unavailable").length;
  const finalKept = rows.filter((row) => physicsDecision(row) === "retain" || aiDecision(row) === "retain").length;
  const agree = rows.filter((row) => aiDecision(row) !== "unavailable" && physicsDecision(row) === aiDecision(row)).length;
  const filteredPercent = rows.length ? (rows.length - finalKept) / rows.length * 100 : 0;
  const objectReduction = beforeObjects.length ? (1 - afterObjects.length / beforeObjects.length) * 100 : 0;
  const cloudName = (row) => {
    const ids = row.object_ids || [], names = row.object_names || [];
    const index = ids.findIndex((id, i) => objects.get(id)?.category === "debris" || /\bDEB(?:RIS)?\b/i.test(names[i] || ""));
    return index >= 0 ? names[index] || objects.get(ids[index])?.name || "Debris cloud" : "Other pairs";
  };
  const groups = new Map();
  rows.forEach((row) => {
    const key = cloudName(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  const plainReason = (row) => {
    const reason = `${row.reason_code || ""} ${row.reason || ""}`.toUpperCase();
    if (!String(row.model_status || "").startsWith("available")) return "AI unavailable; this pair follows the physics threshold and safety guard.";
    if (reason.includes("UNCERTAIN_SCENARIOS")) return "Some uncertainty cases could not be calculated, so this pair stays for review.";
    if (reason.includes("MISS_DISTANCE")) return "The miss distance meets the independent safety guard.";
    if (reason.includes("SCENARIO_PC")) return "At least one research probability meets the safety guard.";
    if (reason.includes("PREDICTED_SIGNIFICANT")) return "The research model flagged this pair as potentially significant.";
    if (reason.includes("PREDICTED_INSIGNIFICANT") || reason.includes("BELOW_THRESHOLD")) return "All calculated research scenarios were below the screening threshold.";
    return row.decision_source === "safety_guard" ? "Kept for safety review because required event inputs were incomplete." : "Selected by the research filter.";
  };
  const examples = rows.slice(0, 5);
  return <main className="og-page og-smart-filter" aria-label="Smart Filter">
    <header className="og-maneuver-header"><div><h1>Smart Filter</h1><p>Compare all screened encounter objects with the objects in pairs kept by the research filter.</p></div></header>
    {!data && <div role="status" className="og-card smart-filter-progress" aria-label="Loading filter decisions"><div className="smart-filter-progress-track"><progress aria-label="Smart Filter progress" max="100" {...(Number.isFinite(progress.percent) ? { value: progress.percent } : {})} /></div><span>{progress.message}</span></div>}
    {data && <>
      <section className="smart-filter-globes" aria-label="Before and after object coverage">
        <article className="og-card smart-filter-globe-panel"><h2>Before <span>objects in screened pairs</span></h2><strong className="smart-filter-object-count">{beforeObjects.length.toLocaleString()}</strong><React.Suspense fallback={<div className="loading-skeleton" aria-label="Loading globe"/>}><BrowserGlobe title="Objects in screened close-approach pairs" objects={beforeObjects} propagationEpoch={propagationEpoch}/></React.Suspense></article>
        <div className="smart-filter-reduction" aria-label="Distinct object reduction"><strong>{objectReduction.toFixed(1)}%</strong><span>fewer objects</span></div>
        <article className="og-card smart-filter-globe-panel"><h2>After <span>objects in kept pairs</span></h2><strong className="smart-filter-object-count">{afterObjects.length.toLocaleString()}</strong><React.Suspense fallback={<div className="loading-skeleton" aria-label="Loading globe"/>}><BrowserGlobe title="Objects in pairs kept by Smart Filter" objects={afterObjects} propagationEpoch={propagationEpoch}/></React.Suspense></article>
      </section>
      <section className="og-card smart-filter-comparison-card" aria-label="Physics versus AI pair counts"><h2>Physics vs AI</h2><div className="smart-filter-count-columns"><div><h3>Physics</h3><p><span>Pairs in</span><strong>{rows.length.toLocaleString()}</strong></p><p><span>Pairs kept (Pc ≥ 1e-7)</span><strong>{physicsKept.toLocaleString()}</strong></p><p><span>Pairs filtered</span><strong>{physicsFiltered.toLocaleString()}</strong></p></div><div><h3>AI classifier</h3><p><span>Pairs in / kept</span><strong>{rows.length.toLocaleString()} / {aiKept.toLocaleString()}</strong></p><p><span>AI available</span><strong>{aiAvailable.toLocaleString()}</strong></p><p><span>AI insignificant</span><strong>{aiAvailable - aiKept}</strong></p></div></div><p className="smart-filter-agreement">Agree on {agree} of {aiAvailable} available AI pairs · final valid pairs kept {finalKept} · invalid/uncertain safety-retained {excludedRows.length} · filtered {filteredPercent.toFixed(1)}% of valid pairs</p></section>
      <section className="og-card" aria-label="Five pair examples"><h2>Decision examples</h2><p className="muted">Physics log10 Pc is the maximum numeric scenario value. The classifier vote fraction and regression estimate come from separate validated artifacts. The classifier training significance label uses Pc ≥ 1e-4.</p><div className="og-table-wrap"><table className="og-table"><thead><tr><th>Pair</th><th>Physics log10 Pc</th><th>AI log10 Pc</th><th>AI result / vote fraction</th><th>Combined decision</th><th>Keep reason</th></tr></thead><tbody>{examples.map((row) => <tr key={row.event_id}><td>{pairName(row)}</td><td>{Number.isFinite(row.maximum_scenario_log10_pc) ? row.maximum_scenario_log10_pc.toFixed(3) : "Unavailable"}</td><td>{row.ai_pc_status === "available" && Number.isFinite(row.ai_predicted_log10_pc) ? row.ai_predicted_log10_pc <= -30 ? "≤ -30" : row.ai_predicted_log10_pc.toFixed(3) : "Unavailable"}</td><td>{aiDecision(row) === "unavailable" ? "AI unavailable" : `${row.model_prediction} · ${Number.isFinite(row.confidence) ? row.confidence.toFixed(3) : "vote unavailable"}`}</td><td>{physicsDecision(row) === "retain" || aiDecision(row) === "retain" ? "Kept" : "Filtered"}</td><td>{plainReason(row)}</td></tr>)}</tbody></table></div></section>
      {data.decisions?.some((row) => !String(row.model_status || "").startsWith("available")) && <p className="og-sub">Some event features were incomplete. Those pairs were kept for review by the safety rules.</p>}
      <section className="og-card"><div className="og-section-head"><div><h2>Pair decisions</h2><p>Physics and AI decisions for valid screened pairs.</p></div><button className="og-btn" disabled={!jobId || !decisions.length} onClick={() => jobId && download(physicalSmartFilterCsvPath(jobId), `${jobId}-smart-filter.csv`)}>Download CSV</button></div>
        <div className="og-table-wrap"><table className="og-table"><thead><tr><th>Object pair</th><th>Miss distance</th><th>Pc</th><th>Physics</th><th>AI</th><th>Reason</th></tr></thead><tbody>{[...groups.entries()].map(([key, groupRows]) => <React.Fragment key={key}><tr className="smart-filter-cloud-heading"><th colSpan={6}>{key} · {groupRows.length} pairs</th></tr>{groupRows.map((row) => <tr key={row.event_id}><td>{pairName(row)}</td><td>{Number.isFinite(row.miss_distance_km) ? `${number(row.miss_distance_km, 3)} km` : "No miss-distance value"}</td><td>{row.maximum_scenario_pc_scientific || "No calculated Pc"}</td><td>{physicsDecision(row) === "filter" ? "Filtered" : "Kept"}</td><td>{row.model_status !== "available" ? "AI unavailable · Physics fallback" : aiDecision(row) === "filter" ? "Filtered" : "Kept"}</td><td>{plainReason(row)}</td></tr>)}</React.Fragment>)}</tbody></table></div>
        {!rows.length && <p>No valid event pairs in this screening.</p>}
        {excludedRows.length > 0 && <details className="smart-filter-excluded"><summary>Excluded ({excludedRows.length})</summary><ul>{excludedRows.map((row) => <li key={row.event_id}>{pairName(row)} — {eventById.get(row.event_id)?.physics_result?.reason_codes?.join(", ") || "Invalid or incomplete physical assessment"}</li>)}</ul></details>}
      </section>
    </>}
  </main>;
}
