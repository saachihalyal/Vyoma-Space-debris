import React, { lazy, Suspense, useEffect, useRef, useState } from "react";
import { researchPcCatalogSummary } from "../../utils/researchPcAnalytics.js";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "./ChartPrimitives.jsx";

const ResearchPcChart = lazy(() => import("./ResearchPcClassChart.jsx"));

export function HomePage({ snapshot, platform, maneuver, navigate, loading = false }) {
  const chartHost = useRef(null);
  const [chartVisible, setChartVisible] = useState(false);
  useEffect(() => {
    const node = chartHost.current;
    if (!node || chartVisible) return undefined;
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) setChartVisible(true); }, { rootMargin: "120px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [chartVisible]);
  const events = platform?.conjunctions || [];
  const stats = researchPcCatalogSummary(events);
  const objects = snapshot?.objects?.length || snapshot?.stats?.tracked_objects || 0;
  const actionable = (stats.classCounts.Medium || 0) + (stats.classCounts.High || 0);
  const maneuverCandidates = maneuver?.physics_candidates?.candidates?.length || 0;
  const topEvents = events.slice().sort((a, b) => (b.automatic_research_pc_assessment?.log10_pc ?? -Infinity) - (a.automatic_research_pc_assessment?.log10_pc ?? -Infinity)).slice(0, 5);
  const bands = ["LEO", "MEO", "GEO"].map((band) => ({ band, count: snapshot?.objects?.filter((item) => item.band === band).length || 0 }));
  const types = Object.entries((snapshot?.objects || []).reduce((acc, item) => { const type = item.object_type || item.category || "other"; acc[type] = (acc[type] || 0) + 1; return acc; }, {}));
  const timeline = platform?.analytics?.risk_timeline || [];
  return <main className="og-page og-home page-stack" aria-label="Home">
    <header className="og-card home-hero">
      <p className="eyebrow">Vyoma SSA Research</p>
      <h1>{loading && !snapshot ? "Loading the accepted catalog and screening result…" : `${objects.toLocaleString()} objects tracked, ${stats.total.toLocaleString()} close approaches screened, ${actionable.toLocaleString()} Medium/High Pc events.`}</h1>
      <p>Current counts come from the accepted catalog and screening result.</p>
      <div className="hero-actions">
        <button className="og-btn primary" onClick={() => navigate("collision")}>Open Collision Analysis</button>
        <button className="og-btn" onClick={() => navigate("maneuver")}>Assess a Maneuver</button>
        <button className="og-btn" onClick={() => navigate("smart")}>Open Smart Filter</button>
      </div>
    </header>
    <section className="og-kpis" aria-label="Research overview">
      {[["Objects tracked", objects, "Objects in the accepted catalog"], ["Close approaches screened", stats.total, "Assessment records in the current result"], ["Medium/High-Pc events", actionable, "Events in these research Pc classes"], ["Maneuver candidates evaluated", maneuverCandidates, "Candidate burns in the selected result"]].map(([label, value, meaning]) => <article className="og-card og-kpi" key={label}><span>{label}</span><b>{loading && !snapshot ? "â€¦" : Number(value).toLocaleString()}</b><small>{meaning}</small></article>)}
    </section>
    <section ref={chartHost} className="og-card" aria-label="Research Pc class chart">
      <h2>Research Pc class counts</h2>
      <p>Vyoma classifies close approaches by collision probability.</p>
      {loading && !snapshot ? <div className="home-chart loading-skeleton" role="status" aria-label="Loading research Pc chart" /> : stats.total > 0 && chartVisible ? <Suspense fallback={<div className="home-chart loading-skeleton" role="status" aria-label="Loading research Pc chart" />}><ResearchPcChart counts={stats.classCounts} /></Suspense> : <div className="home-chart loading-skeleton" aria-label="Research Pc chart" />}
    </section>
    <section className="og-card"><h2>Research log10 Pc distribution</h2><div className="home-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={stats.histogram}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="label"/><YAxis allowDecimals={false}/><Tooltip/><Bar dataKey="count" fill="#58d6e8"/></BarChart></ResponsiveContainer></div></section>
    <section className="og-card"><h2>Top close approaches</h2><div className="og-table-wrap"><table className="og-table"><thead><tr><th>Object pair</th><th>Pc</th><th>Physics class</th><th>AI class</th></tr></thead><tbody>{topEvents.map((event) => <tr key={event.id}><td>{event.primary?.name || event.primary?.id} vs {event.secondary?.name || event.secondary?.id}</td><td>{event.automatic_research_pc_assessment?.pc_scientific || event.automatic_research_pc_assessment?.pc || ""}</td><td>{event.automatic_research_pc_assessment?.risk_assessment?.final_risk_class || ""}</td><td>{event.collision_ai_assessment?.risk_classifier?.ai_risk_class || ""}</td></tr>)}</tbody></table></div></section>
    <section className="og-card"><h2>Objects by orbit band</h2><div className="home-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={bands}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="band"/><YAxis allowDecimals={false}/><Tooltip/><Bar dataKey="count" fill="#8bd5ff"/></BarChart></ResponsiveContainer></div></section>
    <section className="og-card"><h2>Orbital congestion (not collision probability)</h2>{loading && !snapshot ? <div className="home-chart loading-skeleton" aria-label="Loading orbital congestion"/> : <div className="home-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={timeline}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="hour"/><YAxis/><Tooltip/><Line type="monotone" dataKey="global_heuristic_risk_score" stroke="#f5c76a"/></LineChart></ResponsiveContainer></div>}</section>
    <section className="og-card"><h2>Object types</h2><div className="og-kpis">{types.map(([type, count]) => <article className="og-tile" key={type}><span>{type}</span><b>{count.toLocaleString()}</b></article>)}</div></section>
  </main>;
}
