import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const apiSource = readFileSync(new URL("../src/api/ssaClient.js", import.meta.url), "utf8");
const styleSource = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const satelliteFieldSource = readFileSync(new URL("../src/components/Scene/SatelliteField.jsx", import.meta.url), "utf8");
const maneuverWorkbenchSource = readFileSync(new URL("../src/components/UI/ManeuverWorkbench.jsx", import.meta.url), "utf8");
const visualizationSource = readFileSync(new URL("../src/components/UI/VisualizationPage.jsx", import.meta.url), "utf8");
const collisionWorkbenchSource = readFileSync(new URL("../src/components/UI/CollisionWorkbench.jsx", import.meta.url), "utf8");

test("Collision Analysis Start Screening is wired to the existing explicit screening callback", () => {
  assert.match(appSource, /onStartScreening=\{startScreening\}/);
  assert.match(appSource, /refresh=\{startScreening\}/);
  assert.match(appSource, /explicitScreeningRefreshRef\.current/);
  assert.match(appSource, /getConjunctions\(/);
  assert.match(apiSource, /\/api\/conjunction-jobs/);
});

test("Collision Analysis begins with title and events without diagnostic charts or tiles", () => {
  assert.match(collisionWorkbenchSource, /<h1>Collision Analysis<\/h1>/);
  assert.match(collisionWorkbenchSource, /Prioritized Events/);
  assert.doesNotMatch(collisionWorkbenchSource, /Screening diagnostics|What-if uncertainty|Scenario class counts|CollisionAnalysisSummary/);
  assert.doesNotMatch(collisionWorkbenchSource, /screening-result-summary/);
  assert.match(collisionWorkbenchSource, /No High-probability events found \(highest Pc/);
  assert.match(collisionWorkbenchSource, /Excluded pairs/);
  assert.match(collisionWorkbenchSource, /const visiblePhysical = physical\.filter\(\(item\) => !isExcludedEvent\(item\)\)/);
  assert.match(collisionWorkbenchSource, /const excludedEvents = physical\.filter\(isExcludedEvent\)/);
  assert.match(collisionWorkbenchSource, /Run full screening/);
  assert.match(collisionWorkbenchSource, /Horizon/);
  assert.match(collisionWorkbenchSource, /value=\{24\}>24 h/);
  assert.match(collisionWorkbenchSource, /value=\{72\}>72 h/);
  assert.match(collisionWorkbenchSource, /value=\{168\}>7 days/);
  assert.match(collisionWorkbenchSource, /No High-probability events found \(highest Pc/);
  assert.match(collisionWorkbenchSource, /screening-progress-strip/);
});

test("Collision Analysis reports 72-hour class counts and shows event-bound 2x Pc sensitivity without changing the main class", () => {
  assert.match(appSource, /useState\(72\)/);
  assert.match(appSource, /getConjunctions\(\{ limit: 400, horizonHours/);
  assert.match(appSource, /sensitivityPcCacheRef = useRef\(new Map\(\)\)/);
  assert.match(appSource, /covarianceScale: 2/);
  assert.match(appSource, /const key = `\$\{item\.screening_job_id\}\|\$\{item\.id\}\|2`/);
  assert.match(collisionWorkbenchSource, /Low \{currentClassCounts\.Low\}.*Medium \{currentClassCounts\.Medium\}.*High \{currentClassCounts\.High\}/);
  assert.match(collisionWorkbenchSource, /Sensitivity · Pc at 2x uncertainty/);
  assert.match(collisionWorkbenchSource, /const sensitivityPc = sensitivity\?\.status/);
  assert.match(collisionWorkbenchSource, /data-c=\{getClass\(item\)\}/);
});

test("Collision restores prioritized events and separate physics and AI assessment panels", () => {
  assert.match(collisionWorkbenchSource, /Prioritized Events/);
  assert.match(collisionWorkbenchSource, /collision-assessment-grid/);
  assert.match(collisionWorkbenchSource, /Physics Assessment/);
  assert.match(collisionWorkbenchSource, /AI Assessment/);
  assert.match(collisionWorkbenchSource, /collision-kpis/);
  assert.match(collisionWorkbenchSource, /Research Pc/);
  assert.match(collisionWorkbenchSource, /const classAgreement =/);
  assert.match(collisionWorkbenchSource, /function getAiClass/);
  assert.match(collisionWorkbenchSource, /Math\.log10\(high\)/);
  assert.match(collisionWorkbenchSource, /Near threshold/);
  assert.match(collisionWorkbenchSource, /encounter_plane_sigma_min_km/);
  assert.match(collisionWorkbenchSource, /encounter_plane_sigma_max_km/);
  assert.match(collisionWorkbenchSource, /collision-plane-hbr/);
  assert.match(collisionWorkbenchSource, /collision-plane-miss/);
  assert.match(collisionWorkbenchSource, /if \(\!\[sigmaMin, sigmaMax, hbr, miss\]\.every\(Number\.isFinite\)/);
  assert.match(collisionWorkbenchSource, /identical_propagation_parameters\|duplicate_tle_state/);
  assert.doesNotMatch(collisionWorkbenchSource, /Top drivers/);
  assert.match(collisionWorkbenchSource, /Ranking details/);
  assert.match(collisionWorkbenchSource, /onAssessManeuver\(chosen\)/);
  assert.doesNotMatch(appSource, /CollisionAnalysisSummary/);
});

test("Collision Analysis defaults to the shared selected physical event and never substitutes a hidden stale detail", () => {
  const collisionBranch = appSource.slice(appSource.indexOf('{activePage === "collision"'), appSource.indexOf('{activePage === "maneuver"'));
  assert.match(collisionBranch, /savedEvents\.find\(\(item\) => item\.id === selectedEvent\?\.id\) \|\| null/);
  assert.doesNotMatch(collisionBranch, /platform\.conjunctions\[0\]/);
  assert.match(collisionBranch, /selectionNotice=\{eventSelection\.notice\}/);
  assert.match(collisionBranch, /selectEvent=\{selectEvent\}/);
  assert.match(appSource, /selectEvent\(selectManeuverEvent\(savedEvents, eventId\), "maneuver"\)/);
  assert.match(collisionWorkbenchSource, /Excluded pairs/);
  assert.match(collisionWorkbenchSource, /Run screening to populate physical encounter groups/);
});

test("conjunction cards preserve Show in Globe pair context and Maneuver Assessment handoff", () => {
  assert.match(appSource, /onShowInGlobe=\{onShowInGlobe\}/);
  assert.match(appSource, /onAssessManeuver=\{\(item\) => selectEvent\(item, "maneuver"\)\}/);
  assert.match(appSource, /setPendingGlobeSelection\(captureGlobeEventSelection\(event, screeningJobId\)\)/);
  assert.match(visualizationSource, /highlightedObjectIds=\{resolvedGlobeSelection\.event \? \[resolvedGlobeSelection\.event\.primary\?\.id, resolvedGlobeSelection\.event\.secondary\?\.id\]/);
  assert.match(maneuverWorkbenchSource, /selected\.physics_result/);
  assert.match(satelliteFieldSource, /const selected = activeObjects\.filter\(\(object\) => highlightedIds\.has\(object\.id\)\)/);
  assert.match(satelliteFieldSource, /const selected = debrisObjects\.filter\(\(object\) => highlightedIds\.has\(object\.id\)\)/);
});

test("conjunction dashboard cards collapse cleanly at mobile widths without a horizontal event table", () => {
  const cardsSource = readFileSync(new URL("../src/components/UI/CollisionPriorityTable.js", import.meta.url), "utf8");
  assert.match(cardsSource, /conjunction-card-list/);
  assert.doesNotMatch(cardsSource, /React\.createElement\("table"/);
  assert.match(styleSource, /@media \(max-width: 720px\)/);
  assert.match(styleSource, /\.conjunction-card-channels \{ grid-template-columns: 1fr;/);
  assert.match(styleSource, /\.conjunction-card-metrics \{ grid-template-columns: 1fr;/);
});
