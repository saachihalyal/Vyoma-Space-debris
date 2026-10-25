import React from "react";
import { getPhysicalSmartFilter, physicalSmartFilterCsvPath } from "../../api/ssaClient.js";

const fmt = new Intl.NumberFormat("en-US");
const pairName = (row) => (row.object_names || row.object_ids || [row.event_id]).join(" vs ");
const BrowserGlobe = React.lazy(() => import("../Scene/SmartFilterGlobe.jsx").then((m) => ({ default: m.SmartFilterGlobe })));

export function SmartFilterWorkbench({ snapshot, smartSnapshot, platform = {}, download = () => {}, physicalFilterResult = null }) {
  const jobId = platform.conjunctionStatus?.job_id || null;
  const [data, setData] = React.useState(physicalFilterResult);
  const [error, setError] = React.useState("");
  const [tab, setTab] = React.useState("retain");
  const [query, setQuery] = React.useState("");
  const [page, setPage] = React.useState(1);
  React.useEffect(() => {
    if (physicalFilterResult) { setData(physicalFilterResult); setError(""); return undefined; }
    if (!jobId) { setData(null); return undefined; }
    const controller = new AbortController(); setData(null); setError("");
    getPhysicalSmartFilter(jobId, { signal: controller.signal }).then(setData).catch((e) => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [jobId, physicalFilterResult]);
  const decisions = data?.decisions || [];
  const evaluation = data?.evaluation || {};
  const filteredRate = evaluation.before_count ? evaluation.filtered_count / evaluation.before_count * 100 : 0;
  const rows = decisions.filter((r) => tab === "retain" ? r.decision !== "filter" : r.decision === "filter")
    .filter((r) => `${pairName(r)} ${r.event_id} ${r.reason} ${r.reason_code}`.toLowerCase().includes(query.toLowerCase()));
  const pages = Math.max(1, Math.ceil(rows.length / 25));
  const shown = rows.slice((page - 1) * 25, page * 25);
  const model = data?.model || {};
  const metrics = model.metrics?.test || {};
  const splits = model.split_counts || {};
  const pct = (v) => Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : "Not reported";
  const physical = (platform.conjunctions || []).filter((e) => e.result_kind === "physics_assessment");
  const priorityText = (e) => Number.isFinite(e.ai_risk_assessment?.score) ? `Review band · ${(e.ai_risk_assessment.score * 100).toFixed(1)} / 100` : "Review band · retain for review";
  const proxies = platform.screeningProxies || [];
  return <main className="page-stack og-maneuver">
    <header className="og-maneuver-header"><div><span className="og-prov derived">Physics generated decisions</span><h1>Smart Filter</h1><p>Research Pc based physical event screening with an independent safety guard.</p></div></header>
    <section aria-label="Smart Filter event counts" className="og-kpi">
      {[["Before (events)", evaluation.before_count], ["Kept", evaluation.kept_count], ["Filtered out", evaluation.filtered_count]].map(([label, value]) => <article className="og-card og-hero-card" key={label}><span>{label}</span><b>{Number.isFinite(value) ? fmt.format(value) : "—"}</b>{label === "Filtered out" && <small>{filteredRate.toFixed(1)}% of events before filter</small>}</article>)}
    </section>
    {error && <p role="alert" className="og-card">Filter evaluation failed: {error}</p>}
    {!data && !error && <p role="status" className="og-card">{jobId ? "Calculating research-Pc scenarios…" : "Start or restore a physical screening job to load decisions."}</p>}
    {data && <>
      <section className="og-card" aria-label="Smart Filter model status"><div className="og-section-head"><div><span className="og-prov derived">Model status API</span><h2>{model.model_name || "Physics Smart Filter"} {model.model_version ? `v${model.model_version}` : ""}</h2></div><span className="og-chip">{model.status === "available" ? "Trained model" : "Physics fallback"}</span></div>
        <p>Recall on significant events: {pct(metrics.recall_significant)} · Precision: {pct(metrics.precision_significant)} · False negatives: {metrics.false_negative_significant_count ?? "Not reported"} · Test set size: {metrics.sample_count ?? "Not reported"}</p>
        <p>Split by encounter group — train: {splits.train?.encounter_group_count ?? splits.train?.group_count ?? "Not reported"}, validation: {splits.validation?.encounter_group_count ?? splits.validation?.group_count ?? "Not reported"}, test: {splits.test?.encounter_group_count ?? splits.test?.group_count ?? "Not reported"}.</p>
        <p>Trained on physics-generated labels, not on observed collisions</p>
      </section>
      <section className="og-card"><div className="og-section-head"><div><span className="og-prov derived">Event decisions</span><h2>{tab === "retain" ? "Kept" : "Filtered"} pairs</h2></div><button className="og-btn" type="button" disabled={!jobId || !decisions.length} onClick={() => jobId && download(physicalSmartFilterCsvPath(jobId), `${jobId}-smart-filter.csv`)}>Download decisions CSV</button></div>
        <div className="og-section-head"><div role="tablist" aria-label="Decision group"><button role="tab" aria-selected={tab === "retain"} className="og-btn" onClick={() => { setTab("retain"); setPage(1); }}>Kept ({evaluation.kept_count ?? 0})</button> <button role="tab" aria-selected={tab === "filter"} className="og-btn" onClick={() => { setTab("filter"); setPage(1); }}>Filtered ({evaluation.filtered_count ?? 0})</button></div><label className="og-field">Search <input value={query} onChange={(e) => { setQuery(e.target.value); setPage(1); }} /></label></div>
        <p className="og-sub">Model confidence is the maximum random-forest vote fraction across uncertainty scenarios; it is not a calibrated probability.</p>
        <div className="og-table-wrap"><table className="og-table"><thead><tr><th>Object pair</th><th>Miss distance (km)</th><th>Research Pc</th><th>Model confidence</th><th>Reason</th><th>Safety guard</th></tr></thead><tbody>{shown.map((r) => <tr key={r.event_id}><td>{pairName(r)}<small>{r.event_id}</small></td><td>{Number.isFinite(r.miss_distance_km) ? r.miss_distance_km.toFixed(3) : "Not calculable: invalid miss distance"}</td><td>{r.maximum_scenario_pc_scientific || (r.maximum_scenario_log10_pc != null ? `10^${Number(r.maximum_scenario_log10_pc).toFixed(2)}` : `Not calculable: ${r.reason_code || "scenario Pc unavailable"}`)}</td><td title="Maximum forest vote fraction across scenarios; not calibrated probability">{Number.isFinite(r.confidence) ? `${(r.confidence * 100).toFixed(1)}%` : "Not reported"}</td><td><span className="og-chip">{r.reason || r.reason_code || "Reason not reported by API"}</span></td><td><span className="og-chip">{r.safety_guard_retained ? `Retained by guard · ${(r.safety_guard_reasons || []).join(", ")}` : "Not retained by guard"}</span></td></tr>)}</tbody></table></div>
        {!shown.length && <p className="og-sub">No matching decisions.</p>}<div className="og-section-head"><span>Page {page} of {pages}</span><div><button className="og-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button> <button className="og-btn" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button></div></div>
      </section>
    </>}
    <section className="og-card"><h2>Physical events for review</h2>{physical.map((e) => <article className="og-event" key={e.id}><b>{e.primary?.name || e.primary?.id} vs {e.secondary?.name || e.secondary?.id}</b><span>{priorityText(e)}</span></article>)}</section>
    <details className="og-card"><summary>Catalog overview (not the collision filter)</summary><p>{(snapshot?.objects || []).length} catalog objects before · {(smartSnapshot?.objects || []).length} in the heuristic catalog view</p>
      {typeof window === "undefined" ? <p className="og-sub">Catalog globes load in the browser.</p> : <React.Suspense fallback={<p className="og-sub">Loading catalog globes…</p>}><div className="og-before-after"><div className="og-card"><h3>Before catalog heuristic</h3><BrowserGlobe title="Before catalog heuristic" objects={snapshot?.objects || []} /></div><div className="og-card"><h3>After catalog heuristic</h3><BrowserGlobe title="After catalog heuristic" objects={smartSnapshot?.objects || []} /></div></div></React.Suspense>}
      <h3>Heuristic Proxy Pipeline</h3><p>{proxies.length} catalog proxy pairs. These heuristic proxies are separate from physical collision decisions.</p></details>
  </main>;
}
