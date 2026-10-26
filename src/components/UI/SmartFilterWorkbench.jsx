import React from "react";
import { getPhysicalSmartFilter, physicalSmartFilterCsvPath } from "../../api/ssaClient.js";

const BrowserGlobe = React.lazy(() => import("../Scene/SmartFilterGlobe.jsx").then((m) => ({ default: m.SmartFilterGlobe })));
const number = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : "No numeric miss distance in this event";
const pairName = (row) => (row.object_names || row.object_ids || []).join(" vs ");

export function SmartFilterWorkbench({ platform = {}, download = () => {}, physicalFilterResult = null }) {
  const jobId = platform.conjunctionStatus?.job_id || null;
  const [data, setData] = React.useState(physicalFilterResult);
  const [error, setError] = React.useState("");
  const [tab, setTab] = React.useState("retain");
  React.useEffect(() => {
    if (physicalFilterResult) { setData(physicalFilterResult); setError(""); return undefined; }
    if (!jobId) { setData(null); return undefined; }
    const controller = new AbortController(); setData(null); setError("");
    getPhysicalSmartFilter(jobId, { signal: controller.signal }).then(setData).catch((e) => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [jobId, physicalFilterResult]);
  const decisions = data?.decisions || [];
  const evaluation = data?.evaluation || {};
  const isKept = tab === "retain";
  const rows = decisions.filter((r) => (r.decision !== "filter") === isKept);
  const events = (platform.conjunctions || []).filter((e) => e.result_kind === "physics_assessment");
  const objects = new Map(events.flatMap((event) => [[event.primary?.id, event.primary], [event.secondary?.id, event.secondary]]).filter(([id, object]) => id && object));
  const selectedIds = new Set(rows.flatMap((row) => row.object_ids || []));
  const afterObjects = Array.from(selectedIds).map((id) => objects.get(id)).filter(Boolean);
  const allIds = new Set(decisions.flatMap((row) => row.object_ids || []));
  const beforeObjects = Array.from(allIds).map((id) => objects.get(id)).filter(Boolean);
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
    {!data && !error && <p role="status" className="og-card">{jobId ? "Calculating research probability scenarios…" : "Run screening to calculate filter decisions."}</p>}
    {data && <>
      <section className="smart-filter-globes" aria-label="Before and after object coverage">
        <article className="og-card"><h2>Before · {beforeObjects.length} objects</h2><React.Suspense fallback={<div className="loading-skeleton" aria-label="Loading globe"/>}><BrowserGlobe title="All objects in screened close approaches" objects={beforeObjects} /></React.Suspense></article>
        <article className="og-card"><h2>After · {afterObjects.length} objects</h2><React.Suspense fallback={<div className="loading-skeleton" aria-label="Loading globe"/>}><BrowserGlobe title="Objects in pairs kept by Smart Filter" objects={afterObjects} /></React.Suspense></article>
      </section>
      <section className="smart-filter-funnel" aria-label="Smart Filter event counts">
        {["Events in", "Kept", "Filtered"].map((label, index) => <React.Fragment key={label}>{index > 0 && <span className="smart-filter-funnel-arrow" aria-hidden="true">→</span>}<article className="og-card"><span>{label}</span><b>{Number(evaluation[["before_count", "kept_count", "filtered_count"][index]] || 0).toLocaleString()}</b></article></React.Fragment>)}
      </section>
      {data.decisions?.some((row) => row.model_status !== "available") && <p className="og-sub">Some event features were incomplete. Those pairs were kept for review by the safety rules.</p>}
      <section className="og-card"><div className="og-section-head"><div><h2>{isKept ? "Kept" : "Filtered"} event pairs</h2><p>Model decision is shown for each event.</p></div><button className="og-btn" disabled={!jobId || !decisions.length} onClick={() => jobId && download(physicalSmartFilterCsvPath(jobId), `${jobId}-smart-filter.csv`)}>Download CSV</button></div>
        <div role="tablist" aria-label="Filter decision"><button role="tab" aria-selected={isKept} className="og-btn" onClick={() => setTab("retain")}>Kept ({evaluation.kept_count || 0})</button> <button role="tab" aria-selected={!isKept} className="og-btn" onClick={() => setTab("filter")}>Filtered ({evaluation.filtered_count || 0})</button></div>
        <div className="og-table-wrap"><table className="og-table"><thead><tr><th>Object pair</th><th>Miss distance</th><th>Pc</th><th>Reason</th></tr></thead><tbody>{grouped.map((group) => <React.Fragment key={group.key}><tr className="smart-filter-cloud-heading"><th colSpan={4}>{group.key} · {group.rows.length} pairs</th></tr>{group.rows.map((row) => <tr key={row.event_id}><td>{pairName(row)}<small>Model: {row.model_status === "available" ? (row.model_prediction === "significant" ? "kept" : "filtered") : "safety review"}</small></td><td>{Number.isFinite(row.miss_distance_km) ? `${number(row.miss_distance_km, 3)} km` : "No miss distance in event record"}</td><td>{row.maximum_scenario_pc_scientific || "No probability returned for this event"}</td><td>{plainReason(row)}</td></tr>)}</React.Fragment>)}</tbody></table></div>
        {!rows.length && <p>No event pairs in this group.</p>}
      </section>
    </>}
  </main>;
}
