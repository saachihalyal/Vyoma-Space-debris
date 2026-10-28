import { useMemo, useState } from "react";
import { buildCanonicalIdentity, getPairType } from "../../utils/identityModel.js";
import { collisionEventPriority, explainPhysicsReason, searchAndSortCollisionEvents } from "../../utils/collisionEventDisplay.js";
import { groupCoLocatedEvents } from "../../utils/researchPcAnalytics.js";
import { researchPcPresentation, physicsPcRiskPresentation, compactPcText } from "../../utils/collisionPcPresentation.js";
import { formatProbabilityScientific, formatProbabilityPercentage, formatProbabilityOdds, isUsablePc } from "./CollisionPcSummary.js";

const getResearch = (event) => event?.automatic_research_pc_assessment;
const getClass = (event) => getResearch(event)?.risk_assessment?.final_risk_class || "Unclassified";
const getAiLogPc = (event) => event?.collision_ai_assessment?.pc_surrogate?.ai_predicted_log10_pc;
const getAiPcReason = (event) => event?.collision_ai_assessment?.pc_surrogate?.reason_code;
function getAiClass(event) {
  const prediction = getAiLogPc(event);
  const thresholds = getResearch(event)?.risk_assessment?.thresholds;
  const medium = thresholds?.medium_pc_inclusive;
  const high = thresholds?.high_pc_inclusive;
  if (!Number.isFinite(prediction) || !Number.isFinite(medium) || !Number.isFinite(high) || medium <= 0 || high <= 0) return null;
  if (prediction >= Math.log10(high)) return "High";
  if (prediction >= Math.log10(medium)) return "Medium";
  return "Low";
}
const classAgreement = (event) => {
  const physicsClass = getClass(event);
  const aiClass = getAiClass(event);
  const aiLogPc = getAiLogPc(event);
  const physicsLogPc = getResearch(event)?.log10_pc;
  if (!aiClass) return getAiPcReason(event) ? `AI estimate unavailable · ${getAiPcReason(event)}` : "AI class not returned";
  if (physicsClass === aiClass) return `AI: ${aiClass} - agrees`;
  if (Number.isFinite(aiLogPc) && Number.isFinite(physicsLogPc)) return `Near threshold · AI log10 Pc ${aiLogPc.toFixed(3)} · Physics log10 Pc ${physicsLogPc.toFixed(3)}`;
  return `AI: ${aiClass} · Physics: ${physicsClass}`;
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
function isExcludedEvent(event) {
  const physics = getPhysics(event);
  const validation = physics.validation_status || physics.validation?.status || event?.validation?.status;
  return physics.status === "invalid" || physics.status === "failed" || ["failed", "invalid", "error"].includes(String(validation || "").toLowerCase()) || (physics.reason_codes || []).some((code) => /identical_propagation_parameters|duplicate_tle_state/i.test(code));
}
function exclusionReason(event) {
  const reasons = getPhysics(event).reason_codes || [];
  return reasons.length ? reasons.map(explainPhysicsReason).join(" ") : explainPhysicsReason("ASSESSMENT_REASON_UNAVAILABLE");
}
function EncounterPlanePlot({ event }) {
  const assessment = getResearch(event);
  const sigmaMin = assessment?.encounter_plane_sigma_min_km;
  const sigmaMax = assessment?.encounter_plane_sigma_max_km;
  const hbr = event?.collision_probability?.hbr_km ?? assessment?.hbr_km;
  const miss = getPhysics(event)?.miss_distance?.value;
  if (![sigmaMin, sigmaMax, hbr, miss].every(Number.isFinite) || sigmaMin <= 0 || sigmaMax <= 0 || hbr <= 0 || miss < 0) return null;
  const extent = Math.max(sigmaMax * 3, miss * 1.12, hbr * 2);
  const center = 180;
  const scale = center / extent;
  const markerX = center + miss * scale;
  return <figure className="collision-plane-plot">
    <svg viewBox="0 0 360 310" role="img" aria-label={`Encounter-plane 1 sigma ellipse; HBR ${shortNumber(hbr, 6)} km; miss-distance magnitude ${shortNumber(miss, 6)} km`}>
      <line x1="20" y1={center} x2="340" y2={center} className="collision-plane-axis"/><line x1={center} y1="15" x2={center} y2="285" className="collision-plane-axis"/>
      <ellipse cx={center} cy={center} rx={sigmaMax * scale} ry={sigmaMin * scale} className="collision-plane-sigma"/>
      <circle cx={center} cy={center} r={hbr * scale} className="collision-plane-hbr"/><circle cx={markerX} cy={center} r="5" className="collision-plane-miss"/>
      <text x="185" y="300">X (km) · sigmamax {shortNumber(sigmaMax, 3)}</text><text x="12" y="17">Y (km) · sigmamin {shortNumber(sigmaMin, 3)}</text>
      <text x={Math.min(markerX + 7, 270)} y={center - 9}>Miss {shortNumber(miss, 3)} km</text><text x="186" y={center + 16}>0</text>
    </svg>
    <figcaption>Miss-distance magnitude is plotted on X; its encounter-plane direction is not included in the event data.</figcaption>
  </figure>;
}

export function CollisionWorkbench({ events = [], event, screeningStatus = {}, eventStatus = {}, screeningAttempt = null, currentEvents = [], references = [], sensitivityPcByEvent = {}, screeningHorizonHours = 72, setScreeningHorizonHours = () => {}, selectEvent = () => {}, onShowInGlobe = () => {}, onAssessManeuver = () => {}, download = () => {}, screeningJobId, eventReportPath, eventReportCsvPath, eventReportJsonPath, onImportCdm = async () => {}, onStartScreening = () => {} }) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("research_pc");
  const [classFilter, setClassFilter] = useState("All");
  const [tab, setTab] = useState("Overview");
  const [cdmXml, setCdmXml] = useState("");
  const [uploadStatus, setUploadStatus] = useState("");
  const physical = events.filter((item) => item?.result_kind === "physics_assessment");
  const excludedEvents = physical.filter(isExcludedEvent);
  const excludedPairs = new Map();
  for (const item of excludedEvents) {
    const pair = [item.primary?.id || item.primary?.name, item.secondary?.id || item.secondary?.name].map(String).sort().join("|");
    if (!excludedPairs.has(pair)) excludedPairs.set(pair, { event: item, reason: exclusionReason(item) });
  }
  const visiblePhysical = physical.filter((item) => !isExcludedEvent(item));
  const groups = useMemo(() => encounterGroups(visiblePhysical), [events]);
  const searched = searchAndSortCollisionEvents(groups.map((group) => group.representative), query, sort);
  const groupByRep = new Map(groups.map((group) => [group.representative.id, group]));
  const matchingGroups = searched.map((item) => groupByRep.get(item.id)).filter(Boolean)
    .filter((group) => classFilter === "All" || getClass(group.representative) === classFilter);
  const chosen = event && !isExcludedEvent(event) ? event : matchingGroups[0]?.representative || groups[0]?.representative || null;
  const chosenGroup = chosen ? groups.find((group) => group.members.some((item) => item.id === chosen.id)) : null;
  const pcAssessment = chosen ? getResearch(chosen) : null;
  const pcView = researchPcPresentation(pcAssessment);
  const risk = physicsPcRiskPresentation(pcAssessment?.risk_assessment);
  const physics = chosen ? getPhysics(chosen) : {};
  const primary = chosen ? objectInfo(chosen.primary) : null;
  const secondary = chosen ? objectInfo(chosen.secondary) : null;
  const researchPcCount = groups.filter((group) => group.members.some((item) => getPhysics(item).status === "valid" && Number.isFinite(getLogPc(item)))).length;
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
  const excludedList = [...excludedPairs.values()];
  const validCurrentEvents = currentEvents.filter((item) => item?.result_kind === "physics_assessment" && !isExcludedEvent(item));
  const currentClassCounts = { Low: 0, Medium: 0, High: 0 };
  for (const item of validCurrentEvents) {
    const riskClass = getResearch(item)?.risk_assessment?.final_risk_class;
    if (Object.hasOwn(currentClassCounts, riskClass)) currentClassCounts[riskClass] += 1;
  }
  const highestCurrentEvent = validCurrentEvents.filter((item) => Number.isFinite(getLogPc(item)))
    .sort((left, right) => getLogPc(right) - getLogPc(left))[0];
  const highestCurrentPc = highestCurrentEvent
    ? getResearch(highestCurrentEvent)?.estimated_pc_scientific || `10^${getLogPc(highestCurrentEvent).toFixed(3)}`
    : null;
  const acceptedHorizon = eventStatus?.screening?.horizon_hours ?? eventStatus?.horizon_hours;
  const acceptedRunComplete = ["complete", "partial"].includes(eventStatus?.completion_status) && Number.isFinite(acceptedHorizon);
  const progressActive = ["pending", "queued", "starting", "running"].includes(screeningAttempt?.result_status);
  return <main className="og-page og-collision" aria-label="Collision Analysis workbench">
    <header className="og-workbench-head"><h1>Collision Analysis</h1><div className="screening-launch-controls"><label className="og-field">Horizon<select aria-label="Screening horizon" value={screeningHorizonHours} onChange={(change) => setScreeningHorizonHours(Number(change.target.value))}><option value={24}>24 h</option><option value={72}>72 h</option><option value={168}>7 days</option></select></label><button className="og-btn primary" onClick={onStartScreening} type="button" disabled={progressActive}>Run full screening</button></div></header>
    {progressActive ? <section className="screening-progress-strip" role="status"><span>{screeningAttempt?.progress?.message || "Screening job is running."}</span><progress aria-label="Screening progress" {...(Number.isFinite(screeningAttempt?.progress?.percent) ? { value: screeningAttempt.progress.percent, max: 100 } : {})} /></section> : null}
    <section className="og-work collision-full-width">
      <aside className="og-card og-list collision-event-list" aria-label="Prioritized Events"><h2>Prioritized Events</h2>
        <label className="og-field">Search encounters<input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Name, object ID, or event ID" /></label>
        <label className="og-field">Sort<select value={sort} onChange={(e) => setSort(e.target.value)}><option value="research_pc">Exact log10 Pc, descending</option><option value="tca_soonest">TCA, soonest</option><option value="miss_nearest">Miss distance, nearest</option></select></label>
        <div className="og-filter-chips" aria-label="Filter by Pc class">{["All", "High", "Medium", "Low", "Unclassified"].map((value) => <button key={value} type="button" className={`og-btn ${classFilter === value ? "primary" : ""}`} onClick={() => setClassFilter(value)}>{value}</button>)}</div>
        {matchingGroups.map((group) => {
          const item = group.representative;
          const p = objectInfo(item.primary); const s = objectInfo(item.secondary); const shownPc = researchPcPresentation(getResearch(item));
          const sensitivity = sensitivityPcByEvent[`${item.screening_job_id}|${item.id}|2`];
          const sensitivityPc = sensitivity?.status === "available"
            ? researchPcPresentation(sensitivity.assessment).value
            : sensitivity?.status === "not_available" ? "Not returned" : "Calculating";
          return <button type="button" key={item.id} className={`og-event ${chosen?.id === item.id ? "on" : ""}`} data-c={getClass(item)} onClick={() => selectEvent(item, "collision")}>
            <b>{p.name} / {s.name}</b><span className={`og-chip ${getClass(item)}`}>{getClass(item)}</span>
            <small>{item.screening_library_current ? "Current" : `Saved screening · ${item.screening_run_date ? new Date(item.screening_run_date).toLocaleDateString() : "run date not recorded"}`}</small><small>Pc {compactPcText(shownPc.value)} · TCA {tcaText(item)}</small><small>Physics: {getClass(item)} · {classAgreement(item)}</small>
            <small className="collision-sensitivity-cell"><span>Sensitivity · Pc at 2x uncertainty</span><b>{sensitivityPc}</b></small>
            <small>Priority (heuristic): {reviewBand(item.review_priority?.category)} · {Number.isFinite(item.review_priority?.score) ? item.review_priority.score : ""}</small>
            {group.extraObjects > 0 ? <small>+{group.extraObjects} co-located objects</small> : null}
          </button>;
        })}
        {!matchingGroups.length ? <p>No encounter groups match these filters.</p> : null}
        {references.map((reference) => {
          const probability = reference.collision_probability?.pc;
          const pair = [reference.primary?.name || reference.primary?.id, reference.secondary?.name || reference.secondary?.id].filter(Boolean).join(" / ");
          return <div className="og-event reference-library-entry" key={reference.id} aria-label="NASA CARA reference event"><b>{pair || reference.reference_case?.name || "NASA CARA reference event"}</b><span className="og-chip">Reference</span><small>{reference.reference_case?.name}</small>{Number.isFinite(probability) ? <small>Pc {probability.toExponential(3)}</small> : null}</div>;
        })}
      </aside>
      <div className="og-detail collision-event-detail">
        {acceptedRunComplete ? <section className="collision-screening-counts" aria-label={`${acceptedHorizon} hour screening results`}><b>{acceptedHorizon === 168 ? "7 days" : `${acceptedHorizon} h`} screening results</b><span>Low {currentClassCounts.Low}</span><span>Medium {currentClassCounts.Medium}</span><span>High {currentClassCounts.High}</span></section> : null}
        {acceptedRunComplete && currentClassCounts.High === 0 && highestCurrentPc ? <p className="collision-no-high" role="status">No High-probability events found (highest Pc {highestCurrentPc})</p> : null}
        {chosen ? <>
          <section className="og-card og-hero"><div><span className="og-sub">{primary.displayType} · {primary.id} vs {secondary.displayType} · {secondary.id}</span><h2>{primary.name} · {secondary.name}</h2><div className="og-pc collision-primary-pc">{pcView.value}</div><div className="og-pcsub">Research Pc · {pcView.percentage}</div><span className="og-chip">Physics: {getClass(chosen)}</span> <span className="og-chip">{classAgreement(chosen)}</span><span className="og-chip">Priority (heuristic): {reviewBand(chosen.review_priority?.category)}</span></div></section>
          <section className="og-tiles collision-kpis">{[["Miss distance", numericCells[0][1]], ["Relative velocity", numericCells[1][1]]].map(([label,value]) => <article className="og-tile" key={label}><small>{label}</small><b>{value}</b></article>)}</section>
          <div className="og-action-row"><button className="og-btn" onClick={() => onShowInGlobe(primary.id, chosen, chosen.screening_job_id || screeningJobId)} type="button">Show in Globe</button><button className="og-btn primary" onClick={() => onAssessManeuver(chosen)} type="button">Assess Maneuver</button></div>
          <section className="collision-assessment-grid">
            <article className="og-card"><h3>Physics Assessment</h3><p>Physics class: <b>{getClass(chosen)}</b></p><EncounterPlanePlot event={chosen}/></article>
            <article className="og-card"><h3>AI Assessment</h3><p><b>{classAgreement(chosen)}</b></p><p>AI predicted log10 research Pc: {Number.isFinite(getAiLogPc(chosen)) ? getAiLogPc(chosen).toFixed(4) : "Not returned"} · Physics log10 research Pc: {Number.isFinite(getLogPc(chosen)) ? getLogPc(chosen).toFixed(4) : "Not returned"}</p></article>
          </section>
          <nav className="og-tabs" aria-label="Encounter details">{["Overview", "AI", "Report"].map((name) => <button className={`og-tab ${tab === name ? "on" : ""}`} type="button" key={name} onClick={() => setTab(name)}>{name}</button>)}</nav>
          <section className="og-card og-tab-content">
            {tab === "Overview" ? <><h3>Overview</h3><p>Research Pc ranks this group using the encounter geometry and the selected assumed covariance and HBR inputs. The score scales exact log10 Pc across the configured project window.</p><p>Review priority (rule-based): <b>{reviewBand(chosen.review_priority?.category)}</b>. This geometry band is separate from the Pc-based class.</p><details className="og-acc"><summary>Ranking details</summary><p>{collisionEventPriority(chosen).basis}</p></details></> : null}
            {tab === "AI" ? <><h3>AI model outputs</h3><dl className="og-kv"><dt>AI predicted log10 research Pc</dt><dd>{Number.isFinite(getAiLogPc(chosen)) ? getAiLogPc(chosen).toFixed(4) : "Not returned"}</dd><dt>AI prediction status</dt><dd>{getAiPcReason(chosen) || chosen.collision_ai_assessment?.pc_surrogate?.status || "Unavailable"}</dd><dt>AI class</dt><dd>{getAiClass(chosen) || "Not returned"} · {classAgreement(chosen)}</dd><dt>Physics log10 research Pc</dt><dd>{Number.isFinite(getLogPc(chosen)) ? getLogPc(chosen).toFixed(4) : "Not returned"} · physics class {getClass(chosen)}</dd></dl></> : null}
            {tab === "Report" ? <><h3>Report preview</h3><dl className="og-kv">{reports.map(([label, value]) => <div className="og-report-row" key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><button className="og-btn" disabled={!eventReportPath} onClick={() => eventReportPath && download(eventReportPath, `${chosen.id}-report.pdf`)} type="button">PDF</button><button className="og-btn" disabled={!eventReportCsvPath} onClick={() => eventReportCsvPath && download(eventReportCsvPath, `${chosen.id}-report.csv`)} type="button">CSV</button><button className="og-btn" disabled={!eventReportJsonPath} onClick={() => eventReportJsonPath && download(eventReportJsonPath, `${chosen.id}-report.json`)} type="button">JSON</button></> : null}
          </section>
          <details className="og-acc"><summary>Upload Conjunction Data / Foster assessment</summary><label className="og-field"><strong>Upload Conjunction Data</strong><input type="file" accept=".xml,.cdm,.kvn,.txt,.json,application/xml,text/xml,application/json,text/plain" onChange={async (e) => { const file = e.target.files?.[0]; if (file) setCdmXml(await file.text()); }} /></label><label className="og-field">CDM message<textarea value={cdmXml} onChange={(e) => setCdmXml(e.target.value)} rows={6} placeholder="Paste a conjunction data message" /></label><p className="og-sub">The uploaded file must match both object IDs, exact TCA, and the event frame shown here. Unsupported terrestrial frames are rejected because no validated Earth-orientation transform is applied.</p><button className="og-btn" type="button" disabled={!cdmXml.trim()} onClick={async () => { try { await onImportCdm({ eventId: chosen.id, cdmXml, sourceLabel: "User uploaded CDM", assumeIndependentCovariances: false }); setUploadStatus("CDM assessment imported."); } catch (error) { setUploadStatus(error?.message || "CDM assessment failed."); } }}>Match CDM to event and calculate imported Pc</button>{uploadStatus ? <p role="status">{uploadStatus}</p> : null}</details>
        </> : <section className="og-card"><h2>No selected encounter</h2><p>Run screening to populate physical encounter groups.</p></section>}
      </div>
    </section><details className="og-acc excluded-pairs"><summary>Excluded pairs ({excludedList.length})</summary><ul>{excludedList.map(({ event: item, reason }) => <li key={item.id}>{item.primary?.name || item.primary?.id} / {item.secondary?.name || item.secondary?.id}: {reason}</li>)}</ul></details>
  </main>;
}
