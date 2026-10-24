import test from "node:test";
import assert from "node:assert/strict";
import { forecastHourLabel, proxyPriorityClassIndex } from "../src/utils/analyticsPresentation.js";

test("forecast labels use actual hour offsets instead of history-like sequence labels", () => {
  assert.equal(forecastHourLabel({ hour: 0 }, 0), "+0h");
  assert.equal(forecastHourLabel({ hour: 168 }, 7), "+168h");
  assert.equal(forecastHourLabel({}, 2), "T3");
});

test("proxy class colors use an explicit ordinal index, not event probability", () => {
  assert.equal(proxyPriorityClassIndex("Low"), 0.05);
  assert.equal(proxyPriorityClassIndex("Medium"), 0.25);
  assert.equal(proxyPriorityClassIndex("High"), 0.7);
  assert.equal(proxyPriorityClassIndex("Critical"), 0.9);
  assert.equal(proxyPriorityClassIndex("Safe"), 0.05);
});
