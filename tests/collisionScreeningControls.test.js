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

test("Collision Analysis exposes backend states and keeps detailed screening diagnostics collapsed", () => {
  assert.match(appSource, /Screening: \{stateLabel\}/);
  assert.match(appSource, /Retry Screening/);
  assert.match(appSource, /Backend-reported screening progress/);
  assert.match(appSource, /<details className="og-acc"><summary>Screening diagnostics<\/summary>/);
  assert.match(collisionWorkbenchSource, /Run full screening/);
});

test("Collision restores prioritized events and separate physics and AI assessment panels", () => {
  assert.match(collisionWorkbenchSource, /Prioritized Events/);
  assert.match(collisionWorkbenchSource, /collision-assessment-grid/);
  assert.match(collisionWorkbenchSource, /Physics Assessment/);
  assert.match(collisionWorkbenchSource, /AI Assessment/);
  assert.match(collisionWorkbenchSource, /collision-kpis/);
  assert.match(collisionWorkbenchSource, /What-if uncertainty/);
  assert.match(collisionWorkbenchSource, /Class thresholds follow the configured research Pc cutoffs/);
  assert.match(collisionWorkbenchSource, /Research Pc/);
  assert.match(collisionWorkbenchSource, /const classAgreement =/);
  assert.match(collisionWorkbenchSource, /Physics class: \{getResearch\(item\)\?\.risk_assessment\?\.final_risk_class \|\| ""\}.*AI class:/);
  assert.match(collisionWorkbenchSource, /physicsClass === aiClass \? "agrees" : "differs"/);
  assert.match(collisionWorkbenchSource, /Ranking details/);
  assert.match(collisionWorkbenchSource, /onAssessManeuver\(chosen\)/);
  assert.match(appSource, /CollisionAnalysisSummary/);
});

test("Collision Analysis defaults to the shared selected physical event and never substitutes a hidden stale detail", () => {
  const collisionBranch = appSource.slice(appSource.indexOf('{activePage === "collision"'), appSource.indexOf('{activePage === "maneuver"'));
  assert.match(collisionBranch, /savedEvents\.find\(\(item\) => item\.id === selectedEvent\?\.id\) \|\| null/);
  assert.doesNotMatch(collisionBranch, /platform\.conjunctions\[0\]/);
  assert.match(collisionBranch, /selectionNotice=\{eventSelection\.notice\}/);
  assert.match(collisionBranch, /selectEvent=\{selectEvent\}/);
  assert.match(appSource, /selectEvent\(selectManeuverEvent\(savedEvents, eventId\), "maneuver"\)/);
  assert.match(collisionWorkbenchSource, /Invalid events/);
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
