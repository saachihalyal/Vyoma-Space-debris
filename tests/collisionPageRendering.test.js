import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { CollisionWorkbench } from "../src/components/UI/CollisionWorkbench.jsx";

const capturedEvent = JSON.parse(readFileSync(new URL("./fixtures/capturedRealScreeningEvent.json", import.meta.url), "utf8"));

function renderCollision(events, event = null) {
  return renderToStaticMarkup(React.createElement(CollisionWorkbench, {
    events,
    event,
    uncertaintyScale: 1,
    uncertaintyWhatIf: null,
    uncertaintyWhatIfStatus: "idle",
  }));
}

test("Collision page renders empty, partial, and complete screening data without throwing", () => {
  assert.doesNotThrow(() => renderCollision([]));
  assert.doesNotThrow(() => renderCollision([{ id: "partial-event", result_kind: "physics_assessment", physics_result: {} }]));
  assert.doesNotThrow(() => renderCollision([capturedEvent], capturedEvent));
});

test("App declares what-if state and places an error boundary around the active page", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(app, /const \[uncertaintyScale, setUncertaintyScale\] = useState\(1\)/);
  assert.match(app, /<PageErrorBoundary key=\{activePage\}>/);
  assert.match(app, /This page hit an error/);
  assert.match(app, /window\.location\.reload\(\)/);
});
