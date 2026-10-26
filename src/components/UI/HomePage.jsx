import React, { lazy, Suspense, useEffect, useRef, useState } from "react";
import { researchPcCatalogSummary } from "../../utils/researchPcAnalytics.js";

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
  return <main className="og-page og-home page-stack" aria-label="Home">
    <header className="og-card home-hero">
      <p className="eyebrow">Vyoma SSA Research</p>
      <h1>{objects.toLocaleString()} objects tracked, {stats.total.toLocaleString()} close approaches screened, {actionable.toLocaleString()} Medium/High Pc events.</h1>
      <p>Current counts come from the accepted catalog and screening result.</p>
      <div className="hero-actions">
        <button className="og-btn primary" onClick={() => navigate("collision")}>Open Collision Analysis</button>
        <button className="og-btn" onClick={() => navigate("maneuver")}>Assess a Maneuver</button>
        <button className="og-btn" onClick={() => navigate("smart")}>Open Smart Filter</button>
      </div>
    </header>
    <section className="og-kpis" aria-label="Research overview">
      {[["Objects tracked", objects, "Objects in the accepted catalog"], ["Close approaches screened", stats.total, "Assessment records in the current result"], ["Medium/High-Pc events", actionable, "Events in these research Pc classes"], ["Maneuver candidates evaluated", maneuverCandidates, "Candidate burns in the selected result"]].map(([label, value, meaning]) => <article className="og-card og-kpi" key={label}><span>{label}</span><b>{loading && !snapshot ? "…" : Number(value).toLocaleString()}</b><small>{meaning}</small></article>)}
    </section>
    <section ref={chartHost} className="og-card" aria-label="Research Pc class chart">
      <h2>Research Pc class counts</h2>
      <p>Vyoma classifies close approaches by collision probability.</p>
      {stats.total > 0 && chartVisible ? <Suspense fallback={<div className="home-chart loading-skeleton" role="status" aria-label="Loading research Pc chart" />}><ResearchPcChart counts={stats.classCounts} /></Suspense> : stats.total > 0 ? <div className="home-chart loading-skeleton" role="status" aria-label="Research Pc chart loads when visible" /> : <p>Run a screening to see class counts.</p>}
    </section>
  </main>;
}
