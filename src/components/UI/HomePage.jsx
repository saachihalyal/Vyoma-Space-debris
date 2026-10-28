import React from "react";
import { Activity, AlertTriangle, BrainCircuit, Filter, Orbit, Radio } from "lucide-react";
import { getPhysicalSmartFilter } from "../../api/ssaClient.js";

const finite = (value) => typeof value === "number" && Number.isFinite(value);
const eventPcLog = (event) => event?.automatic_research_pc_assessment?.log10_pc;
const pairName = (event) => `${event?.primary?.name || event?.primary?.id || "Object"} vs ${event?.secondary?.name || event?.secondary?.id || "Object"}`;
const className = (event) => event?.automatic_research_pc_assessment?.risk_assessment?.final_risk_class || "Unclassified";
const scientificFromLog10 = (value) => {
  if (!finite(value)) return "No Pc data";
  const exponent = Math.floor(value);
  const mantissa = 10 ** (value - exponent);
  return `${mantissa.toFixed(2)}e${exponent >= 0 ? "+" : ""}${exponent}`;
};

function averagePc(events) {
  const logs = events.map(eventPcLog).filter(finite);
  if (!logs.length) return null;
  const max = Math.max(...logs);
  return max + Math.log10(logs.reduce((sum, value) => sum + 10 ** (value - max), 0) / logs.length);
}

function eventPriority(event) {
  const assessment = event?.ai_risk_assessment;
  return {
    rank: finite(assessment?.final_priority_rank) ? assessment.final_priority_rank : null,
    score: finite(assessment?.final_priority_score) ? assessment.final_priority_score : assessment?.score,
  };
}

export function HomePage({ snapshot, eventLibrary, navigate, loading = false }) {
  const events = eventLibrary?.events || [];
  const libraryCounts = eventLibrary?.counts || null;
  const catalogLoaded = Boolean(snapshot) && snapshot.source_state?.status !== "unavailable";
  const tracked = catalogLoaded ? finite(snapshot?.stats?.tracked_objects) ? snapshot.stats.tracked_objects : Array.isArray(snapshot?.objects) ? snapshot.objects.length : null : null;
  const debris = catalogLoaded ? finite(snapshot?.stats?.debris_count) ? snapshot.stats.debris_count : finite(snapshot?.stats?.debris_objects) ? snapshot.stats.debris_objects : null : null;
  const mediumHigh = libraryCounts ? (libraryCounts.Medium || 0) + (libraryCounts.High || 0) : null;
  const averageLogPc = averagePc(events);
  const comparisons = events.map((event) => ({ physics: className(event), ai: event?.collision_ai_assessment?.risk_classifier?.ai_risk_class }))
    .filter(({ physics, ai }) => ai && physics !== "Unclassified");
  const agreement = comparisons.length ? comparisons.filter(({ physics, ai }) => physics === ai).length / comparisons.length * 100 : null;
  const topEvents = [...events].sort((left, right) => {
    const a = eventPriority(left), b = eventPriority(right);
    if (finite(a.rank) && finite(b.rank) && a.rank !== b.rank) return a.rank - b.rank;
    if (finite(a.score) && finite(b.score) && a.score !== b.score) return b.score - a.score;
    return (eventPcLog(right) ?? -Infinity) - (eventPcLog(left) ?? -Infinity);
  }).slice(0, 5);
  const highestPriority = topEvents[0] || null;
  const [smartFilter, setSmartFilter] = React.useState({ status: "loading", result: null });

  React.useEffect(() => {
    const jobId = eventLibrary?.current_job_id;
    if (!jobId) {
      setSmartFilter({ status: eventLibrary ? "unavailable" : "loading", result: null });
      return undefined;
    }
    const controller = new AbortController();
    let timer;
    const poll = async () => {
      if (controller.signal.aborted) return;
      try {
        const result = await getPhysicalSmartFilter(jobId, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (result.status === "computing") {
          setSmartFilter({ status: "computing", result: null });
          timer = setTimeout(poll, 3000);
        } else if (result.evaluation && finite(result.evaluation.before_count) && finite(result.evaluation.filtered_count)) {
          setSmartFilter({ status: "available", result });
        } else {
          setSmartFilter({ status: "unavailable", result: null });
        }
      } catch (error) {
        if (error?.name === "AbortError" || controller.signal.aborted) return;
        setSmartFilter({ status: "retrying", result: null });
        timer = setTimeout(poll, 3000);
      }
    };
    setSmartFilter({ status: "loading", result: null });
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [eventLibrary?.current_job_id, Boolean(eventLibrary)]);

  const evaluation = smartFilter.result?.evaluation;
  const reduction = evaluation && evaluation.before_count > 0 ? evaluation.filtered_count / evaluation.before_count * 100 : null;
  const reductionDisplay = finite(reduction) ? `${reduction.toFixed(1)}%` : smartFilter.status === "loading" || smartFilter.status === "computing" || smartFilter.status === "retrying" ? "Calculating" : "No result";
  const kpis = [
    [Orbit, "Objects tracked", tracked == null ? null : tracked.toLocaleString()],
    [Radio, "Debris count", debris == null ? null : debris.toLocaleString()],
    [AlertTriangle, "Medium/High events", mediumHigh == null ? "Loading" : mediumHigh.toLocaleString()],
    [Activity, "Average Pc", averageLogPc == null ? "No Pc data" : scientificFromLog10(averageLogPc)],
    [BrainCircuit, "AI agreement %", agreement == null ? "No comparisons" : `${agreement.toFixed(1)}%`],
    [Filter, "Smart Filter reduction %", reductionDisplay],
  ];
  const distribution = ["High", "Medium", "Low"];
  const distributionTotal = distribution.reduce((sum, name) => sum + (libraryCounts?.[name] || 0), 0);
  const libraryLoading = !eventLibrary;

  return <main className="og-page og-home page-stack home-nebula" aria-label="Home">
    <section className="home-command-hero">
      <div className="home-command-copy">
        <p className="eyebrow">AI-POWERED ORBITAL RISK INTELLIGENCE PLATFORM</p>
        <h1>Identifying the event that needs attention, explaining why and moving to action.</h1>
        <p>{libraryLoading ? "Loading saved screening data." : `${(eventLibrary.total ?? events.length).toLocaleString()} saved conjunction pairs, including ${mediumHigh == null ? "an unreported number of" : mediumHigh.toLocaleString()} Medium or High events.`}</p>
        <div className="hero-actions"><button className="og-btn primary" onClick={() => navigate("visualization")}>Open Visualization</button><button className="og-btn" onClick={() => navigate("smart")}>Explore AI</button></div>
      </div>
      <aside className="og-card research-briefing"><p className="eyebrow">AI mission briefing</p>
        <div><span>Objects analysed</span><strong>{tracked == null ? <div className="loading-skeleton home-count-skeleton" role="status" aria-label="Loading objects analysed" /> : tracked.toLocaleString()}</strong></div>
        <div><span>Events needing attention</span><strong>{mediumHigh == null ? "Loading" : mediumHigh.toLocaleString()}</strong></div>
      </aside>
    </section>
    <section className="home-kpi-grid" aria-label="Research overview">{kpis.map(([Icon, label, value]) => <article className="og-card og-kpi" key={label}><Icon size={21} strokeWidth={1.8} aria-hidden="true"/><span>{label}</span>{((label === "Objects tracked" && tracked == null) || (label === "Debris count" && debris == null) || (libraryLoading && ["Medium/High events", "Average Pc", "AI agreement %"].includes(label))) ? <div className="loading-skeleton" role="status" aria-label={`Loading ${label}`} /> : <b>{value}</b>}</article>)}</section>
    <section className="home-lower-grid">
      <article className="og-card"><h2>Live Alerts <small className="og-sub">{eventLibrary?.label || "Loading saved screenings"}</small></h2>{libraryLoading ? <div className="loading-skeleton" role="status" aria-label="Loading live alerts"/> : topEvents.length ? <ol className="home-priority-list">{topEvents.map((event, index) => { const priority = eventPriority(event); return <li key={`${event.screening_job_id || "saved"}:${event.id}`}><span className="home-rank">{index + 1}</span><div><strong>{pairName(event)}</strong><span>Pc {event.automatic_research_pc_assessment?.estimated_pc_scientific || "No Pc reported"}</span></div><span className={`og-chip home-class-badge ${className(event).toLowerCase()}`}>{className(event)}</span><span className="home-alert-priority">{finite(priority.score) ? `Priority ${priority.score.toFixed(2)}` : "Priority not recorded"}</span></li>; })}</ol> : <p className="home-empty">No saved close approaches in the event library.</p>}</article>
      <article className="og-card"><h2>Risk Distribution <small className="og-sub">{eventLibrary?.label || "Loading saved screenings"}</small></h2>{libraryLoading ? <div className="loading-skeleton" role="status" aria-label="Loading risk distribution"/> : <div className="home-class-bars">{distribution.map((name) => { const count = libraryCounts?.[name] || 0; const width = distributionTotal ? count / distributionTotal * 100 : 0; return <div className="home-class-row" key={name}><span>{name}</span><div><i style={{ width: `${width}%` }}/></div><strong>{count.toLocaleString()}</strong></div>; })}</div>}<p className="og-sub">{libraryLoading ? "Loading library totals" : `${(eventLibrary?.total ?? events.length).toLocaleString()} unique saved object pairs`}</p></article>
    </section>
  </main>;
}
