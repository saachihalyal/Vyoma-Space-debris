import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { RiskBadge } from "../src/components/UI/RiskBadge.js";

function render(risk, label = risk) {
  return renderToStaticMarkup(React.createElement(RiskBadge, { risk, label }));
}

test("invalid assessment badge uses neutral diagnostic styling and keeps its status label", () => {
  const markup = render("invalid", "invalid");
  assert.match(markup, /class="risk-badge invalid"/);
  assert.doesNotMatch(markup, /risk-badge critical/);
  assert.match(markup, />invalid<\/span>/);
});

test("valid critical-risk and unavailable badges retain their existing classes", () => {
  assert.match(render("valid", "valid"), /class="risk-badge low"/);
  assert.match(render("Critical", "Critical"), /class="risk-badge critical"/);
  assert.match(render("unavailable", "unavailable"), /class="risk-badge safe"/);
});
