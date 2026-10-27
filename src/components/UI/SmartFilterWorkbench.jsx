import React from "react";
import { getLatestConjunctionJob, getPhysicalSmartFilter, physicalSmartFilterCsvPath } from "../../api/ssaClient.js";

const BrowserGlobe = React.lazy(() => import("../Scene/SmartFilterGlobe.jsx").then((m) => ({ default: m.SmartFilterGlobe })));
const number = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : "";
const pairName = (row) => (row.object_names || row.object_ids || []).join(" vs ");

export function SmartFilterWorkbench({ download = () => {} }) {
  const [acceptedJob, setAcceptedJob] = React.useState(null);
  const [data, setData] = React.useState(null);
  const [progress, setProgress] = React.useState({ stage: "loading", percent: null, message: "Loading the accepted screening and Smart Filter status." });
  React.useEffect(() => {
    const controller = new AbortController();
    let currentJob = null;
    let timer;
    const poll = async () => {
      if (controller.signal.aborted) return;
      try {
        let job = currentJob;
        if (!job?.job_id) {
          job = await getLatestConjunctionJob({ signal: controller.signal });
          if (controller.signal.aborted) return;
          currentJob = job;
          setAcceptedJob(job);
        }
        if (!job?.job_id) setProgress({ stage: "waiting", percent: null, message: "Waiting for an accepted screening job." });
        else {
          const result = await getPhysicalSmartFilter(job.job_id, { signal: controller.signal });
          if (controller.signal.aborted) return;
          if (result.status === "computing") setProgress(result.progress || { stage: "evaluating_events", percent: null, message: "Smart Filter evaluation is running." });
          else { setData(result); setProgress({ stage: "complete", percent: 100, message: "Smart Filter evaluation complete." }); return; }
        }
      } catch (e) {
        if (e.name === "AbortError" || controller.signal.aborted) return;
        setProgress({ stage: "retrying", percent: null, message: "Checking Smart Filter progress; the next check will retry automatically." });
      }
      timer = setTimeout(poll, 3000);
    };
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);
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
  const globePositions = data?.globe_positions || {};
  const beforeObjects = globePositions.before_objects || [];
  const afterObjects = globePositions.after_objects || [];
  const propagationEpoch = globePositions.propagation_epoch || null;
  const policy = data?.policy || {};
  const physicsDecision = (row) => {
    const miss = row.miss_distance_km;
    const pcLog = row.maximum_scenario_log10_pc;
    const threshold = Number(policy.significant_pc_threshold);
    const guarded = row.safety_guard_retained || !Number.isFinite(miss) || miss <= Number(policy.safety_miss_distance_threshold_km || 1);
    return guarded || !Number.isFinite(pcLog) || !(threshold > 0) || pcLog >= Math.log10(threshold) ? "retain" : "filter";
  };
  const aiDecision = (row) => row.model_status === "available" && row.model_prediction === "insignificant" ? "filter" : "retain";
  const physicsKept = rows.filter((row) => physicsDecision(row) === "retain").length;
  const physicsFiltered = rows.length - physicsKept;
  const aiKept = rows.filter((row) => aiDecision(row) === "retain").length;
  const aiFiltered = rows.length - aiKept;
  const agree = rows.filter((row) => physicsDecision(row) === aiDecision(row)).length;
  const filteredPercent = rows.length ? physicsFiltered / rows.length * 100 : 0;
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
    if (reason.includes("UNCERTAIN_SCENARIOS")) return "Some uncertainty cases could not be calculated, so this pair stays for review.";
    if (reason.includes("MISS_DISTANCE")) return "The miss distance meets the independent safety guard.";
    if (reason.includes("SCENARIO_PC")) return "At least one research probability meets the safety guard.";
    if (reason.includes("PREDICTED_SIGNIFICANT")) return "The research model flagged this pair as potentially significant.";
    if (reason.includes("PREDICTED_INSIGNIFICANT") || reason.includes("BELOW_THRESHOLD")) return "All calculated research scenarios were below the screening threshold.";
    return row.decision_source === "safety_guard" ? "Kept for safety review because required event inputs were incomplete." : "Selected by the research filter.";
  };
  return <main className="og-page og-smart-filter" aria-label="Smart Filter">
    <header className="og-maneuver-header"><div><h1>Smart Filter</h1><p>Compare all screened encounter objects with the objects in pairs kept by the research filter.</p></div></header>
    {!data && <div role="status" className="og-card smart-filter-progress" aria-label="Loading filter decisions"><div className="smart-filter-progress-track"><progress aria-label="Smart Filter progress" max="100" {...(Number.isFinite(progress.percent) ? { value: progress.percent } : {})} /></div><span>{progress.message}</span></div>}
    {data && <>
      <section className="smart-filter-globes" aria-label="Before and after object coverage">
        <article className="og-card smart-filter-globe-panel"><h2>Before <span>all screened objects</span></h2><strong className="smart-filter-object-count">{beforeObjects.length.toLocaleString()}</strong><React.Suspense fallback={<div className="loading-skeleton" aria-label="Loading globe"/>}><BrowserGlobe title="All objects in screened close approaches" objects={beforeObjects} propagationEpoch={propagationEpoch}/></React.Suspense></article>
        <div className="smart-filter-reduction" aria-label="Physics-filtered pairs"><strong>{filteredPercent.toFixed(1)}%</strong><span>filtered</span></div>
        <article className="og-card smart-filter-globe-panel"><h2>After <span>objects in kept pairs</span></h2><strong className="smart-filter-object-count">{afterObjects.length.toLocaleString()}</strong><React.Suspense fallback={<div className="loading-skeleton" aria-label="Loading globe"/>}><BrowserGlobe title="Objects in pairs kept by Smart Filter" objects={afterObjects} propagationEpoch={propagationEpoch}/></React.Suspense></article>
      </section>
      <section className="og-card smart-filter-comparison-card" aria-label="Physics versus AI counts"><h2>Physics vs AI</h2><div className="smart-filter-count-columns"><div><h3>Physics</h3><p><span>In</span><strong>{rows.length.toLocaleString()}</strong></p><p><span>Kept</span><strong>{physicsKept.toLocaleString()}</strong></p><p><span>Filtered</span><strong>{physicsFiltered.toLocaleString()}</strong></p></div><div><h3>AI</h3><p><span>In</span><strong>{rows.length.toLocaleString()}</strong></p><p><span>Kept</span><strong>{aiKept.toLocaleString()}</strong></p><p><span>Filtered</span><strong>{aiFiltered.toLocaleString()}</strong></p></div></div><p className="smart-filter-agreement">Agree on {agree} of {rows.length} pairs</p></section>
      {data.decisions?.some((row) => row.model_status !== "available") && <p className="og-sub">Some event features were incomplete. Those pairs were kept for review by the safety rules.</p>}
      <section className="og-card"><div className="og-section-head"><div><h2>Pair decisions</h2><p>Physics and AI decisions for valid screened pairs.</p></div><button className="og-btn" disabled={!jobId || !decisions.length} onClick={() => jobId && download(physicalSmartFilterCsvPath(jobId), `${jobId}-smart-filter.csv`)}>Download CSV</button></div>
        <div className="og-table-wrap"><table className="og-table"><thead><tr><th>Object pair</th><th>Miss distance</th><th>Pc</th><th>Physics</th><th>AI</th><th>Reason</th></tr></thead><tbody>{[...groups.entries()].map(([key, groupRows]) => <React.Fragment key={key}><tr className="smart-filter-cloud-heading"><th colSpan={6}>{key} · {groupRows.length} pairs</th></tr>{groupRows.map((row) => <tr key={row.event_id}><td>{pairName(row)}</td><td>{Number.isFinite(row.miss_distance_km) ? `${number(row.miss_distance_km, 3)} km` : "No miss-distance value"}</td><td>{row.maximum_scenario_pc_scientific || "No calculated Pc"}</td><td>{physicsDecision(row) === "filter" ? "Filtered" : "Kept"}</td><td>{aiDecision(row) === "filter" ? "Filtered" : row.model_status === "available" ? "Kept" : "Kept by safety guard"}</td><td>{plainReason(row)}</td></tr>)}</React.Fragment>)}</tbody></table></div>
        {!rows.length && <p>No valid event pairs in this screening.</p>}
        {excludedRows.length > 0 && <details className="smart-filter-excluded"><summary>Excluded ({excludedRows.length})</summary><ul>{excludedRows.map((row) => <li key={row.event_id}>{pairName(row)} — {eventById.get(row.event_id)?.physics_result?.reason_codes?.join(", ") || "Invalid or incomplete physical assessment"}</li>)}</ul></details>}
      </section>
    </>}
  </main>;
}
