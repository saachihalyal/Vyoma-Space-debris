import React from "react";
import { getLatestConjunctionJob, getPhysicalSmartFilter, physicalSmartFilterCsvPath } from "../../api/ssaClient.js";

const BrowserGlobe = React.lazy(() => import("../Scene/SmartFilterGlobe.jsx").then((m) => ({ default: m.SmartFilterGlobe })));
const number = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : "";
const pairName = (row) => (row.object_names || row.object_ids || []).join(" vs ");

export function SmartFilterWorkbench({ platform = {}, download = () => {} }) {
  const [acceptedJob, setAcceptedJob] = React.useState(null);
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState("");
  const [tab, setTab] = React.useState("retain");
  React.useEffect(() => {
    const controller = new AbortController();
    setAcceptedJob(null); setData(null); setError("");
    getLatestConjunctionJob({ signal: controller.signal })
      .then((job) => {
        if (controller.signal.aborted) return;
        setAcceptedJob(job);
        if (!job?.job_id) { setError("No accepted screening job is available."); return; }
        return getPhysicalSmartFilter(job.job_id, { signal: controller.signal }).then((result) => {
          if (!controller.signal.aborted) setData(result);
        });
      })
      .catch((e) => { if (e.name !== "AbortError" && !controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, []);
  const jobId = acceptedJob?.job_id || null;
  const decisions = data?.decisions || [];
  const evaluation = data?.evaluation || {};
  const isKept = tab === "retain";
  const keptDecisions = decisions.filter((row) => row.decision !== "filter");
  const rows = decisions.filter((r) => (r.decision !== "filter") === isKept);
  const events = (acceptedJob?.result?.data || []).filter((e) => e.result_kind === "physics_assessment");
  const objects = new Map(events.flatMap((event) => [[event.primary?.id, event.primary], [event.secondary?.id, event.secondary]]).filter(([id, object]) => id && object));
  const selectedIds = new Set(keptDecisions.flatMap((row) => row.object_ids || []));
  const afterObjects = Array.from(selectedIds).map((id) => objects.get(id)).filter(Boolean);
  const allIds = new Set(decisions.flatMap((row) => row.object_ids || []));
  const beforeObjects = Array.from(allIds).map((id) => objects.get(id)).filter(Boolean);
  const filteredPercent = decisions.length ? ((decisions.length - keptDecisions.length) / decisions.length) * 100 : 0;
  const cloudName = (row) => {
    const ids = row.object_ids || [], names = row.object_names || [];
    const index = ids.findIndex((id, i) => objects.get(id)?.category === "debris" || /\bDEB(?:RIS)?\b/i.test(names[i] || ""));
    return index >= 0 ? names[index] || objects.get(ids[index])?.name || "Debris cloud" : "Other pairs";
  };
  const groupMap = new Map();
  rows.forEach((row) => {
    const key = cloudName(row);
    if (!groupMap.has(key)) groupMap.set(key, { key, rows: [] });
    groupMap.get(key).rows.push(row);
  });
  const grouped = [...groupMap.values()];
  const physicsKept = decisions.filter((row) => row.decision === "retain").length;
  const physicsFiltered = decisions.length - physicsKept;
  const aiKept = decisions.filter((row) => row.model_status !== "available" || row.model_prediction === "significant").length;
  const aiFiltered = decisions.length - aiKept;
  const policy = data?.policy || {};
  const physicsDecision = (row) => {
    const miss = row.miss_distance_km;
    const pcLog = row.maximum_scenario_log10_pc;
    const threshold = Number(policy.significant_pc_threshold);
    const guarded = row.safety_guard_retained || !Number.isFinite(miss) || miss <= Number(policy.safety_miss_distance_threshold_km || 1);
    const keep = guarded || !Number.isFinite(pcLog) || !(threshold > 0) || pcLog >= Math.log10(threshold);
    return keep ? "retain" : "filter";
  };
  const physicsFunnelKept = decisions.filter((row) => physicsDecision(row) === "retain").length;
  const physicsFunnelFiltered = decisions.length - physicsFunnelKept;
  const differs = decisions.filter((row) => physicsDecision(row) !== (row.model_status === "available" && row.model_prediction === "insignificant" ? "filter" : "retain")).length;
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
    {error && <p role="alert" className="og-card">Filter evaluation failed: {error}</p>}
    {!data && !error && <p role="status" className="og-card loading-skeleton" aria-label="Loading filter decisions"><span /><span /><span /></p>}
    {data && <>
      <section className="smart-filter-globes" aria-label="Before and after object coverage">
        <article className="og-card smart-filter-globe-panel"><h2>Before <span>all screened objects</span></h2><strong className="smart-filter-object-count">{beforeObjects.length.toLocaleString()}</strong><React.Suspense fallback={<div className="loading-skeleton" aria-label="Loading globe"/>}><BrowserGlobe title="All objects in screened close approaches" objects={beforeObjects} /></React.Suspense></article>
        <div className="smart-filter-reduction" aria-label="Pairs filtered"><strong>{filteredPercent.toFixed(1)}%</strong><span>pairs filtered</span></div>
        <article className="og-card smart-filter-globe-panel"><h2>After <span>objects in kept pairs</span></h2><strong className="smart-filter-object-count">{afterObjects.length.toLocaleString()}</strong><React.Suspense fallback={<div className="loading-skeleton" aria-label="Loading globe"/>}><BrowserGlobe title="Objects in pairs kept by Smart Filter" objects={afterObjects} /></React.Suspense></article>
      </section>      <section className="smart-filter-funnel" aria-label="Physics and AI decisions">
        {[["Physics in", decisions.length], ["Physics kept", physicsFunnelKept], ["Physics filtered", physicsFunnelFiltered], ["AI in", decisions.length], ["AI kept", aiKept], ["AI filtered", aiFiltered]].map(([label, count]) => <article className="og-card" key={label}><span>{label}</span><b>{count.toLocaleString()}</b></article>)}
      </section>
      <p className="og-sub smart-filter-comparison">Both keep {decisions.filter((row) => physicsDecision(row) === "retain" && !(row.model_status === "available" && row.model_prediction === "insignificant")).length} pairs · both filter {decisions.filter((row) => physicsDecision(row) === "filter" && row.model_status === "available" && row.model_prediction === "insignificant").length} pairs · differ on {differs} pairs</p>
      {data.decisions?.some((row) => row.model_status !== "available") && <p className="og-sub">Some event features were incomplete. Those pairs were kept for review by the safety rules.</p>}
      <section className="og-card"><div className="og-section-head"><div><h2>{isKept ? "Kept" : "Filtered"} event pairs</h2><p>Model decision is shown for each event.</p></div><button className="og-btn" disabled={!jobId || !decisions.length} onClick={() => jobId && download(physicalSmartFilterCsvPath(jobId), `${jobId}-smart-filter.csv`)}>Download CSV</button></div>
        <div role="tablist" aria-label="Filter decision"><button role="tab" aria-selected={isKept} className="og-btn" onClick={() => setTab("retain")}>Kept ({evaluation.kept_count || 0})</button> <button role="tab" aria-selected={!isKept} className="og-btn" onClick={() => setTab("filter")}>Filtered ({evaluation.filtered_count || 0})</button></div>
        <div className="og-table-wrap"><table className="og-table"><thead><tr><th>Object pair</th><th>Miss distance</th><th>Pc</th><th>Physics decision</th><th>AI decision</th><th>Reason</th></tr></thead><tbody>{grouped.map((group) => <React.Fragment key={group.key}><tr className="smart-filter-cloud-heading"><th colSpan={6}>{group.key} · {group.rows.length} pairs</th></tr>{group.rows.map((row) => { const physics = physicsDecision(row); const ai = row.model_status === "available" && row.model_prediction === "insignificant" ? "filter" : "retain"; return <tr key={row.event_id}><td>{pairName(row)}</td><td>{Number.isFinite(row.miss_distance_km) ? `${number(row.miss_distance_km, 3)} km` : ""}</td><td>{row.maximum_scenario_pc_scientific || ""}</td><td>{physics === "filter" ? "Filtered" : "Kept"}</td><td>{ai === "filter" ? "Filtered" : row.model_status === "available" ? "Kept" : "Kept by safety guard"}</td><td>{plainReason(row)}</td></tr>; })}</React.Fragment>)}</tbody></table></div>
        {!rows.length && <p>No event pairs in this group.</p>}
      </section>
    </>}
  </main>;
}
