import { useMemo, useState } from "react";
import { buildCanonicalIdentity, getPairType } from "../../utils/identityModel.js";
import { collisionEventPriority, explainPhysicsReason, searchAndSortCollisionEvents } from "../../utils/collisionEventDisplay.js";
import { groupCoLocatedEvents } from "../../utils/researchPcAnalytics.js";
import { researchPcPresentation, physicsPcRiskPresentation, compactPcText } from "../../utils/collisionPcPresentation.js";
import { formatProbabilityScientific, formatProbabilityPercentage, formatProbabilityOdds, isUsablePc } from "./CollisionPcSummary.js";
import { CdmReferenceAssessment } from "./CdmReferenceAssessment.jsx";

const getResearch = (event) => event?.automatic_research_pc_assessment;
const getClass = (event) => getResearch(event)?.risk_assessment?.final_risk_class || "Unclassified";
const classAgreement = (event) => {
  const physicsClass = getClass(event);
  const aiClass = event?.collision_ai_assessment?.risk_classifier?.ai_risk_class;
  if (!aiClass) return "AI class not returned";
  return `AI class ${aiClass} (${physicsClass === aiClass ? "agrees" : "differs"})`;
};
const getLogPc = (event) => getResearch(event)?.log10_pc;
const getPhysics = (event) => event?.physics_result || {};
const getGroupKey = (event) => `${getPhysics(event)?.tca?.value}|${getPhysics(event)?.miss_distance?.value}|${getPhysics(event)?.relative_speed_at_tca?.value}`;
const reviewBand = (category) => ({ CRITICAL: "Band 1", HIGH: "Band 2", MEDIUM: "Band 3", LOW: "Band 4", REVIEW_REQUIRED: "Review required", UNCLASSIFIED: "Unclassified" }[category] || "Not classified");

function encounterGroups(events) {
  const collected = new Map();
  const grouped = groupCoLocatedEvents(events);
  const byId = new Map(events.map((event) => [event.id, event]));
  for (const group of grouped) {
    for (const member of group.members) collected.set(member.id, group);
  }
  const result = [];
  const consumed = new Set();
  for (const event of events) {
    if (consumed.has(event.id)) continue;
    const group = collected.get(event.id);
    const members = group?.members || [event];
    members.forEach((item) => consumed.add(item.id));
    const available = members.map((item) => byId.get(item.id)).filter(Boolean);
    const representative = [...available].sort((a, b) => (getLogPc(b) ?? -Infinity) - (getLogPc(a) ?? -Infinity))[0] || event;
    const objects = new Set(available.flatMap((item) => [item.primary?.id, item.secondary?.id]).filter(Boolean));
    result.push({ representative, members: available, extraObjects: Math.max(0, objects.size - 2), key: getGroupKey(representative) });
  }
  return result;
}

const objectInfo = (object) => buildCanonicalIdentity(object || {});
const shortNumber = (value, digits = 3) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "No value in event data";
const tcaText = (event) => getPhysics(event)?.tca?.status === "available" ? getPhysics(event).tca.value : "No TCA in event data";

export function CollisionWorkbench({ events = [], event, eventStatus = {}, screeningStatus = {}, screeningControls, diagnostics, selectEvent = () => {}, onShowInGlobe = () => {}, onAssessManeuver = () => {}, download = () => {}, screeningJobId, eventReportPath, eventReportCsvPath, eventReportJsonPath, onUseReferenceEvent = () => {}, onImportCdm = async () => {}, onScenarioPc = async () => {}, uncertaintyScale = "1", setUncertaintyScale = () => {}, uncertaintyWhatIf, uncertaintyWhatIfStatus = "idle", onStartScreening = () => {} }) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("research_pc");
  const [classFilter, setClassFilter] = useState("All");
  const [tab, setTab] = useState("Overview");
  const [cdmXml, setCdmXml] = useState("");
  const [uploadStatus, setUploadStatus] = useState("");
  const physical = events.filter((item) => item?.result_kind === "physics_assessment");
  const groups = useMemo(() => encounterGroups(physical), [events]);
  const displayGroups = groups.filter((group) => group.members.some((item) => getPhysics(item).status !== "invalid"));
  const searched = searchAndSortCollisionEvents(displayGroups.map((group) => group.representative), query, sort);
  const groupByRep = new Map(groups.map((group) => [group.representative.id, group]));
  const matchingGroups = searched.map((item) => groupByRep.get(item.id)).filter(Boolean)
    .filter((group) => classFilter === "All" || getClass(group.representative) === classFilter);
  const chosen = event || matchingGroups[0]?.representative || groups[0]?.representative || null;
  const chosenGroup = chosen ? groups.find((group) => group.members.some((item) => item.id === chosen.id)) : null;
  const pcAssessment = chosen ? getResearch(chosen) : null;
  const pcView = researchPcPresentation(pcAssessment);
  const risk = physicsPcRiskPresentation(pcAssessment?.risk_assessment);
  const physics = chosen ? getPhysics(chosen) : {};
  const primary = chosen ? objectInfo(chosen.primary) : null;
  const secondary = chosen ? objectInfo(chosen.secondary) : null;
  const researchPcCount = groups.filter((group) => group.members.some((item) => getPhysics(item).status === "valid" && Number.isFinite(getLogPc(item)))).length;
  const validCount = groups.filter((group) => group.members.some((item) => getPhysics(item).status === "valid" && getPhysics(item).tca_status === "valid")).length;
  const mediumHigh = groups.filter((group) => group.members.some((item) => getPhysics(item).status === "valid" && ["Medium", "High"].includes(getClass(item)))).length;
  const numericCells = [
    ["Miss distance", physics.miss_distance?.status === "available" ? `${shortNumber(physics.miss_distance.value)} km` : "No miss distance in event data"],
    ["Relative speed", physics.relative_speed_at_tca?.status === "available" ? `${shortNumber(physics.relative_speed_at_tca.value, 4)} km/s` : "No relative speed in event data"],
    ["TCA (UTC)", tcaText(chosen)],
  ];
  const reports = chosen ? [
    ["Event ID", chosen.id], ["Object pair", `${primary.name} (${primary.id}) / ${secondary.name} (${secondary.id})`],
    ["Object types", `${primary.displayType} / ${secondary.displayType}`], ["Miss distance", numericCells[0][1]], ["Relative speed", numericCells[1][1]],
    ["TCA (UTC)", numericCells[2][1]], ["Research Pc", pcView.value], ["Research Pc percentage", pcView.percentage],
    ["Physics Pc class", pcAssessment?.risk_assessment?.final_risk_class || "Not classified"], ["Score", risk.value],
  ] : [];
  const foster = chosen?.collision_probability;
  const fosterAvailable = isUsablePc(foster) && foster?.event_id === chosen?.id;
  const sourcePc = foster?.source_reported_event_id === chosen?.id ? foster?.source_reported_pc : null;
  return <main className="og-page og-collision" aria-label="Collision Analysis workbench">
    <header className="og-workbench-head"><div><p className="og-sub">Vyoma · Collision Analysis</p><h1>Collision Analysis</h1><p className="og-sub">Research Pc classes use the exact values from each physical event.</p></div><div className="og-workbench-status"><span className="og-prov">Data · {screeningStatus?.source_summary?.primary_source || "Current screening"}</span><span className="og-chip">Collision model · {event?.collision_ai_assessment?.status || events.find((item) => item.collision_ai_assessment?.status)?.collision_ai_assessment?.status || "No model result for this screening"}</span><button className="og-btn primary" onClick={onStartScreening} type="button">Run full screening</button></div></header>
    {screeningControls}
    <section className="og-kpis" aria-label="Encounter group counts">
      {[["Encounter groups", groups.length], ["Valid groups", validCount], ["Groups with research Pc", researchPcCount], ["Medium+High groups", mediumHigh]].map(([label, value]) => <article className="og-card og-kpi" key={label}><b>{value}</b><span>{label}</span></article>)}
    </section>
    <section className="og-work">
      <aside className="og-card og-list" aria-label="Encounter group list">
        <label className="og-field">Search encounters<input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Name, object ID, or event ID" /></label>
        <label className="og-field">Sort<select value={sort} onChange={(e) => setSort(e.target.value)}><option value="research_pc">Exact log10 Pc, descending</option><option value="tca_soonest">TCA, soonest</option><option value="miss_nearest">Miss distance, nearest</option></select></label>
        <div className="og-filter-chips" aria-label="Filter by Pc class">{["All", "High", "Medium", "Low", "Unclassified"].map((value) => <button key={value} type="button" className={`og-btn ${classFilter === value ? "primary" : ""}`} onClick={() => setClassFilter(value)}>{value}</button>)}</div>
        {matchingGroups.map((group) => {
          const item = group.representative;
          const p = objectInfo(item.primary); const s = objectInfo(item.secondary); const shownPc = researchPcPresentation(getResearch(item));
          return <button type="button" key={item.id} className={`og-event ${chosen?.id === item.id ? "on" : ""}`} data-c={getClass(item)} onClick={() => selectEvent(item, "collision")}>
            <b>{p.name} / {s.name}</b><span className={`og-chip ${getClass(item)}`}>{getClass(item)}</span>
            <small>Pc {compactPcText(shownPc.value)} · TCA {tcaText(item)}</small><small>Physics class: {getClass(item)} · {classAgreement(item)}</small>
            {group.extraObjects > 0 ? <small>+{group.extraObjects} co-located objects</small> : null}
          </button>;
        })}
        {!matchingGroups.length ? <p>No encounter groups match these filters.</p> : null}
      </aside>
      <div className="og-detail">
        {chosen ? <>
          <section className="og-card og-hero"><div><span className="og-sub">{primary.displayType} · {primary.id} vs {secondary.displayType} · {secondary.id}</span><h2>{primary.name} <span>×</span> {secondary.name}</h2><div className="og-pc">{pcView.value}</div><div className="og-pcsub">Research Pc · {pcView.percentage}{Number.isFinite(getLogPc(chosen)) && getLogPc(chosen) >= -12 ? ` · about ${formatProbabilityOdds(Number(pcAssessment?.estimated_pc))}` : ""}</div><span className="og-chip">Research Pc · Assumed Inputs</span> <span className={`og-chip ${getClass(chosen)}`}>{getClass(chosen)}</span></div><div className="og-ring" style={{ "--p": pcAssessment?.risk_assessment?.risk_score || 0, "--c": "var(--og-cyan)" }}><span>{shortNumber(pcAssessment?.risk_assessment?.risk_score, 1)}<small>/100</small></span></div></section>
          <section className="og-tiles">{numericCells.map(([label, value]) => <article className="og-tile" key={label}><small>{label}</small><b>{value}</b></article>)}</section>
          <div className="og-action-row"><button className="og-btn" onClick={() => onShowInGlobe(primary.id, chosen, screeningJobId)} type="button">Show in Globe</button><button className="og-btn primary" onClick={() => onAssessManeuver(chosen)} type="button">Assess Maneuver</button></div>
          <nav className="og-tabs" aria-label="Encounter details">{["Overview", "Uncertainty", "AI", "Report"].map((name) => <button className={`og-tab ${tab === name ? "on" : ""}`} type="button" key={name} onClick={() => setTab(name)}>{name}</button>)}</nav>
          <section className="og-card og-tab-content">
            {tab === "Overview" ? <><h3>Overview</h3><p>Research Pc ranks this group using the encounter geometry and the selected assumed covariance and HBR inputs. The score scales exact log10 Pc across the configured project window.</p><p>Review priority (rule-based): <b>{reviewBand(chosen.review_priority?.category)}</b>. This geometry band is separate from the Pc-based class.</p><details className="og-acc"><summary>Ranking details</summary><p>{collisionEventPriority(chosen).basis}</p></details></> : null}
            {tab === "Uncertainty" ? <><h3>Uncertainty</h3><dl className="og-kv"><dt>Covariance policy</dt><dd>{pcAssessment?.covariance_policy_name || pcAssessment?.covariance_policy_id || "Policy not recorded"}</dd><dt>Encounter-plane sigmas</dt><dd>{pcAssessment?.encounter_plane_sigma_min_km ?? "No sigma value"} / {pcAssessment?.encounter_plane_sigma_max_km ?? "No sigma value"} km</dd><dt>Miss / sigma</dt><dd>{pcAssessment?.miss_sigma_ratio ?? "No ratio value"}</dd><dt>HBR and source</dt><dd>{pcAssessment?.hbr_km ?? "No HBR value in event data"} km · {pcAssessment?.hbr_source || "Source not recorded"}</dd><dt>Sensitivity range</dt><dd>{pcView.sensitivity}</dd><dt>What-if result</dt><dd>{uncertaintyWhatIfStatus === "available" ? uncertaintyWhatIf?.log10_pc ?? "No result returned" : uncertaintyWhatIfStatus === "loading" ? "Calculating" : "Select a scale to calculate"}</dd></dl><label className="og-field">Covariance scale what-if<select value={uncertaintyScale} onChange={(e) => setUncertaintyScale(e.target.value)}>{["0.5", "1", "2", "3"].map((scale) => <option key={scale} value={scale}>{scale}×</option>)}</select></label><details className="og-acc"><summary>Other Pc channels</summary><p>Foster Pc: {fosterAvailable ? formatProbabilityScientific(foster.pc) : "No compatible covariance and HBR in screening data"}</p><p>Source-reported Pc: {Number.isFinite(sourcePc) ? formatProbabilityScientific(sourcePc) : "No source-reported Pc in event data"}</p></details></> : null}
            {tab === "AI" ? <><h3>AI model outputs</h3><dl className="og-kv"><dt>AI predicted log10 Pc</dt><dd>{chosen.collision_ai_assessment?.pc_surrogate?.ai_predicted_log10_pc ?? "Model did not return a Pc estimate"} · physics log10 Pc {getLogPc(chosen) ?? "No Pc log value in event data"}</dd><dt>AI class</dt><dd>{chosen.collision_ai_assessment?.risk_classifier?.ai_risk_class || "Classifier did not return a class"} · physics class {getClass(chosen)}</dd><dt>Model status</dt><dd>{chosen.collision_ai_assessment?.status || "No model status returned"}</dd></dl></> : null}
            {tab === "Report" ? <><h3>Report preview</h3><dl className="og-kv">{reports.map(([label, value]) => <div className="og-report-row" key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><button className="og-btn" disabled={!eventReportPath} onClick={() => eventReportPath && download(eventReportPath, `${chosen.id}-report.pdf`)} type="button">PDF</button><button className="og-btn" disabled={!eventReportCsvPath} onClick={() => eventReportCsvPath && download(eventReportCsvPath, `${chosen.id}-report.csv`)} type="button">CSV</button><button className="og-btn" disabled={!eventReportJsonPath} onClick={() => eventReportJsonPath && download(eventReportJsonPath, `${chosen.id}-report.json`)} type="button">JSON</button></> : null}
          </section>
          <details className="og-acc"><summary>Upload Conjunction Data / Foster assessment</summary><label className="og-field"><strong>Upload Conjunction Data</strong><input type="file" accept=".xml,.cdm,.kvn,.txt,.json,application/xml,text/xml,application/json,text/plain" onChange={async (e) => { const file = e.target.files?.[0]; if (file) setCdmXml(await file.text()); }} /></label><label className="og-field">CDM message<textarea value={cdmXml} onChange={(e) => setCdmXml(e.target.value)} rows={6} placeholder="Paste a conjunction data message" /></label><p className="og-sub">The uploaded file must match both object IDs, exact TCA, and the event frame shown here. Unsupported terrestrial frames are rejected because no validated Earth-orientation transform is applied.</p><button className="og-btn" type="button" disabled={!cdmXml.trim()} onClick={async () => { try { await onImportCdm({ eventId: chosen.id, cdmXml, sourceLabel: "User uploaded CDM", assumeIndependentCovariances: false }); setUploadStatus("CDM assessment imported."); } catch (error) { setUploadStatus(error?.message || "CDM assessment failed."); } }}>Match CDM to event and calculate imported Pc</button>{uploadStatus ? <p role="status">{uploadStatus}</p> : null}<CdmReferenceAssessment onUseReferenceEvent={onUseReferenceEvent} /></details>
        </> : <section className="og-card"><h2>No selected encounter</h2><p>Run screening to populate physical encounter groups.</p></section>}
      </div>
    </section>
    {diagnostics}
    <details className="og-acc"><summary>Invalid events ({physical.filter((item) => getPhysics(item).status === "invalid").length})</summary><ul>{physical.filter((item) => getPhysics(item).status === "invalid").map((item) => <li key={item.id}>{item.primary?.name || item.primary?.id} / {item.secondary?.name || item.secondary?.id}: {(getPhysics(item).reason_codes || ["ASSESSMENT_REASON_UNAVAILABLE"]).map(explainPhysicsReason).join(" ")}</li>)}</ul></details>
    <div hidden aria-hidden="true">Physics class {risk.value}</div>
  </main>;
}
