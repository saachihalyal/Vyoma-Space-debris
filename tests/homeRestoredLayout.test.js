import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/components/UI/HomePage.jsx", import.meta.url), "utf8");

test("Home restores the library-backed AI mission briefing, six KPIs, live alerts, and risk bars", () => {
  for (const label of ["AI-POWERED ORBITAL RISK INTELLIGENCE PLATFORM", "Identifying the event that needs attention, explaining why and moving to action.", "Open Visualization", "Explore AI", "AI mission briefing", "Objects analysed", "Events needing attention", "Highest-priority pair", "Recommended action", "Objects tracked", "Debris count", "Medium/High events", "Average Pc", "AI agreement %", "Smart Filter reduction %", "Live Alerts", "Risk Distribution"]) assert.ok(source.includes(label));
  assert.match(source, /const events = eventLibrary\?\.events \|\| \[\]/);
  assert.match(source, /eventLibrary\?\.current_job_id/);
  assert.match(source, /getPhysicalSmartFilter\(jobId/);
  assert.match(source, /evaluation\.filtered_count \/ evaluation\.before_count/);
  assert.match(source, /automatic_research_pc_assessment/);
  assert.match(source, /collision_ai_assessment/);
  assert.match(source, /ai_risk_assessment/);
  assert.match(source, /const libraryLoading = !eventLibrary/);
  assert.match(source, /Loading objects analysed/);
  assert.match(source, /Review \$\{pairName\(highestPriority\)\} \(Pc/);
  assert.doesNotMatch(source, /review_priority\?\.explanation/);
  assert.doesNotMatch(source, /Catalog object count not reported/);
  assert.doesNotMatch(source, /BarChart|LineChart|ResearchPcChart|histogram/);
  assert.doesNotMatch(source, /Close approaches screened|Mean congestion score|Maneuver candidates/);
  const theme = readFileSync(new URL("../src/og-theme.css", import.meta.url), "utf8");
  assert.match(theme, /\.og-home\.home-nebula:before/);
  assert.match(theme, /rgba\(59,29,110/);
  assert.match(theme, /rgba\(11,79,108/);
  assert.match(theme, /rgba\(107,42,122,\.2\)/);
  assert.match(theme, /font-size:56px/);
  assert.match(theme, /font-size:40px/);
  assert.match(theme, /\.platform-shell>\.sidebar\{position:relative;z-index:100\}/);
  assert.match(theme, /\.platform-shell>\.platform-main>\.topbar\{z-index:100\}/);
  assert.doesNotMatch(theme, /\.og-home \.home-command-copy h1\{font-size:(48|44|36)px\}/);
  assert.doesNotMatch(theme, /\.og-home \.home-kpi-grid \.og-kpi b\{font-size:(34|28)px\}/);
});
