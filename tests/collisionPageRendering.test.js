import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";

const capturedEvent = JSON.parse(readFileSync(new URL("./fixtures/capturedRealScreeningEvent.json", import.meta.url), "utf8"));

async function renderCollision(CollisionWorkbench, events, event = null) {
  return renderToStaticMarkup(React.createElement(CollisionWorkbench, {
    events,
    event,
    uncertaintyScale: 1,
    uncertaintyWhatIf: null,
    uncertaintyWhatIfStatus: "idle",
  }));
}

test("Collision page renders empty, partial, and complete screening data without throwing", async () => {
  const { createServer } = await import("vite");
  const { default: react } = await import("@vitejs/plugin-react");
  const server = await createServer({ configFile: false, plugins: [react()], server: { middlewareMode: true }, appType: "custom" });
  try {
    const { CollisionWorkbench } = await server.ssrLoadModule("/src/components/UI/CollisionWorkbench.jsx");
    await assert.doesNotReject(renderCollision(CollisionWorkbench, []));
    await assert.doesNotReject(renderCollision(CollisionWorkbench, [{ id: "partial-event", result_kind: "physics_assessment", physics_result: {} }]));
    await assert.doesNotReject(renderCollision(CollisionWorkbench, [capturedEvent], capturedEvent));
  } finally {
    await server.close();
  }
});

test("App declares what-if state and places an error boundary around the active page", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(app, /const \[uncertaintyScale, setUncertaintyScale\] = useState\(1\)/);
  assert.match(app, /<PageErrorBoundary key=\{activePage\}>/);
  assert.match(app, /This page hit an error/);
  assert.match(app, /window\.location\.reload\(\)/);
  assert.match(app, /componentDidCatch\(error, info\)/);
  assert.match(app, /<details><summary>Details<\/summary>/);
  assert.match(app, /this\.state\.error\?\.message/);
  assert.match(app, /this\.state\.componentStack/);
  const collisionPage = app.slice(app.indexOf("export function CollisionPage"), app.indexOf("export function ManeuverPage"));
  assert.doesNotMatch(collisionPage, /calculateResearchPcWhatIf/);
  assert.match(app, /if \(Number\(uncertaintyScale\) === 1\)/);
  assert.match(app, /scenarioClassCacheRef\.current\.set\(scenarioKey, result\)/);
  assert.match(app, /await calculateResearchPcWhatIf\(/);
  assert.match(app, /await calculateResearchPcWhatIf\(\{ screeningJobId: jobId, eventId: event\.id, covarianceScale: Number\(uncertaintyScale\), signal: controller\.signal \}\)/);
});
