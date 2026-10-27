import React from "react";
import { researchPcCatalogSummary } from "../../utils/researchPcAnalytics.js";

const numeric = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
const display = (value, formatter = (item) => Number(item).toLocaleString()) => value == null ? "" : formatter(value);

export function HomePage({ snapshot, platform, eventLibrary, maneuver, navigate, loading = false, uncertaintyScale = 1, scenarioClassCounts }) {
  const events = eventLibrary?.events || platform?.conjunctions || [];
  const stats = researchPcCatalogSummary(events);
  const libraryCounts = eventLibrary?.counts || stats.classCounts;
  const objects = numeric(snapshot?.objects?.length ?? snapshot?.stats?.tracked_objects);
  const debris = numeric(snapshot?.stats?.debris_count ?? snapshot?.stats?.debris_objects);
  const actionable = (stats.classCounts.Medium || 0) + (stats.classCounts.High || 0);
  const candidates = numeric(maneuver?.result?.physics_candidates?.candidates?.length ?? maneuver?.physics_candidates?.candidates?.length);
  const congestion = numeric(snapshot?.stats?.global_heuristic_risk_score ?? platform?.analytics?.global_heuristic_risk_score);
  const topEvents = events.slice().sort((a, b) => (b.automatic_research_pc_assessment?.log10_pc ?? -Infinity) - (a.automatic_research_pc_assessment?.log10_pc ?? -Infinity)).slice(0, 5);
  const kpis = [["Objects tracked", objects], ["Debris count", debris], ["Close approaches screened", numeric(stats.total)], ["Medium/High events", actionable], ["Mean congestion score", congestion], ["Maneuver candidates", candidates]];
  return <main className="og-page og-home page-stack" aria-label="Home">
    <section className="home-command-hero">
      <div className="home-command-copy"><p className="eyebrow">Vyoma SSA Research</p><h1>Space traffic, clearly in view.</h1>
        <p>{loading && !snapshot ? "Loading the accepted catalog and screening result." : objects == null ? "Accepted catalog and screening summary." : objects.toLocaleString() + " tracked objects across " + stats.total.toLocaleString() + " screened close approaches, with " + actionable.toLocaleString() + " Medium or High Pc events."}</p>
        <div className="hero-actions"><button className="og-btn primary" onClick={() => navigate("collision")}>Collision analysis</button><button className="og-btn" onClick={() => navigate("maneuver")}>Maneuver planning</button><button className="og-btn" onClick={() => navigate("smart")}>Smart Filter</button></div>
      </div>
      <aside className="og-card research-briefing"><p className="eyebrow">Research briefing</p><h2>Accepted screening snapshot</h2><p>Current catalog and conjunction evidence, summarized from the loaded application state.</p><div><span>Screened events</span><strong>{display(stats.total)}</strong></div><div><span>Medium and High</span><strong>{display(actionable)}</strong></div><div><span>Accepted run date</span><strong>{platform?.conjunctionStatus?.run_date ? new Date(platform.conjunctionStatus.run_date).toLocaleDateString() : ""}</strong></div></aside>
    </section>
    <section className="home-kpi-grid" aria-label="Research overview">{kpis.map(([label, value]) => <article className="og-card og-kpi" key={label}><span>{label}</span>{loading && !snapshot ? <div className="loading-skeleton" role="status" aria-label={"Loading " + label} /> : <b>{display(value, (item) => item.toLocaleString(undefined, { maximumFractionDigits: 3 }))}</b>}</article>)}</section>
    <section className="home-lower-grid">
      <article className="og-card"><h2>Top close approaches <small className="og-sub">{eventLibrary?.label || "Current screening"}</small></h2>{loading && !platform ? <div className="loading-skeleton" role="status" aria-label="Loading close approaches" /> : <ol className="home-priority-list">{topEvents.map((event, index) => { const pc = event.automatic_research_pc_assessment; const pair = (event.primary?.name || event.primary?.id || "") + " vs " + (event.secondary?.name || event.secondary?.id || ""); const classifier = event.collision_ai_assessment?.risk_classifier; return <li key={`${event.screening_job_id || "current"}:${event.id}`}><span className="home-rank">{index + 1}</span><div><strong>{pair}</strong><span>Pc {pc?.pc_scientific || pc?.pc || ""} · {event.screening_library_current ? "Current" : event.screening_run_date || "Saved screening"}</span></div><span className="og-chip">{pc?.risk_assessment?.final_risk_class || ""}</span><span className="home-ai-class">{classifier?.ai_risk_class || ""}</span></li>; })}{(eventLibrary?.references || []).map((reference) => <li className="home-reference-entry" key={reference.id}><span className="home-rank">R</span><div><strong>{reference.reference_label}: {reference.reference_case?.name || "NASA CARA case"}</strong><span>{reference.primary?.name || reference.primary?.id} / {reference.secondary?.name || reference.secondary?.id} · Pc {Number.isFinite(reference.collision_probability?.pc) ? reference.collision_probability.pc.toExponential(3) : ""}</span></div></li>)}</ol>}</article>
      <article className="og-card"><h2>Class distribution <small className="og-sub">{eventLibrary?.label || "Current screening"}</small></h2><div className="home-class-bars">{["High", "Medium", "Low"].map((name) => { const count = libraryCounts[name] || 0; const total = (libraryCounts.High || 0) + (libraryCounts.Medium || 0) + (libraryCounts.Low || 0); const width = total ? (count / total) * 100 : 0; return <div className="home-class-row" key={name}><span>{name}</span><div><i style={{ width: width + "%" }} /></div><strong>{display(count)}</strong></div>; })}</div><p className="og-sub">{eventLibrary?.total ?? stats.total} unique object pairs</p></article>
    </section>
    <section className="og-card" aria-label="Scenario class counts"><h2>Scenario class counts · {uncertaintyScale}×</h2>{scenarioClassCounts?.status === "loading" ? <p role="status">Recalculating {scenarioClassCounts.evaluated} of {scenarioClassCounts.total} valid events.</p> : null}{scenarioClassCounts?.counts ? <div className="home-class-bars">{["High", "Medium", "Low", "Unclassified"].map((name) => <div className="home-class-row" key={name}><span>{name}</span><div><i style={{ width: (scenarioClassCounts.evaluated ? scenarioClassCounts.counts[name] / scenarioClassCounts.evaluated * 100 : 0) + "%" }} /></div><strong>{scenarioClassCounts.counts[name]}</strong></div>)}</div> : null}</section>
  </main>;
}
