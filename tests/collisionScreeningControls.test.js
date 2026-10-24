import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const apiSource = readFileSync(new URL("../src/api/ssaClient.js", import.meta.url), "utf8");
const styleSource = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const satelliteFieldSource = readFileSync(new URL("../src/components/Scene/SatelliteField.jsx", import.meta.url), "utf8");

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
  assert.match(appSource, /<details className="advanced-screening-details">/);
});

test("selected event summary exposes geometry, separate Pc sources, ranking basis, and a maneuver entry", () => {
  assert.match(appSource, /aria-label="Selected event summary"/);
  assert.match(appSource, /Event-specific Foster Pc/);
  assert.match(appSource, /Source-reported Pc/);
  assert.match(appSource, /Final ranking basis/);
  assert.match(appSource, /operationalFosterStatus\(event, false\)/);
  assert.match(appSource, /researchPcPresentation/);
  assert.match(appSource, /CollisionAnalysisSummary/);
  assert.match(appSource, /filterCollisionEvents\(events/);
  assert.match(appSource, /Open Maneuver Assessment/);
  assert.match(appSource, /Advanced selected-event details and diagnostics/);
});

test("Collision Analysis defaults to the shared selected physical event and never substitutes a hidden stale detail", () => {
  const collisionBranch = appSource.slice(appSource.indexOf('{activePage === "collision"'), appSource.indexOf('{activePage === "maneuver"'));
  assert.match(collisionBranch, /platform\.conjunctions\.find\(\(item\) => item\.id === selectedEvent\?\.id\) \|\| null/);
  assert.doesNotMatch(collisionBranch, /platform\.conjunctions\[0\]/);
  assert.match(collisionBranch, /selectionNotice=\{eventSelection\.notice\}/);
  assert.match(collisionBranch, /selectEvent=\{selectEvent\}/);
  assert.match(appSource, /selectEvent\(selectManeuverEvent\(platform\.conjunctions, eventId\), "maneuver"\)/);
  assert.match(appSource, /accepted run has no valid interior-TCA event[\s\S]*invalid duplicate or unassessable trajectories are kept in screening diagnostics and receive no risk rank/i);
});

test("conjunction cards preserve Show in Globe pair context and Maneuver Assessment handoff", () => {
  assert.match(appSource, /onShowInGlobe=\{onShowInGlobe\}/);
  assert.match(appSource, /onAssessManeuver=\{\(item\) => selectEvent\(item, "maneuver"\)\}/);
  assert.match(appSource, /setPendingGlobeSelection\(captureGlobeEventSelection\(event, screeningJobId\)\)/);
  assert.match(appSource, /highlightedObjectIds=\{resolvedGlobeSelection\.event \? \[resolvedGlobeSelection\.event\.primary\?\.id, resolvedGlobeSelection\.event\.secondary\?\.id\]/);
  assert.match(appSource, /selectedEvent\.physics_result\.miss_distance/);
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
