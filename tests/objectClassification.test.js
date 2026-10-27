import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { validateAndFilterEvents, validateEvent } from "../src/utils/objectClassification.js";
import { getObjectTypeLabel, getVisualizationCategory } from "../src/utils/objectClassification.js";
import { resolveObjectType, OBJECT_TYPE } from "../src/utils/identityModel.js";
import { createFallbackSnapshot } from "../src/data/fallbackData.js";

test("same-type debris proxy pairs remain valid identities and are not logged as conjunctions", () => {
  const proxy = {
    id: "SP-debris-pair",
    primary: { id: "34046", name: "COSMOS 2251 DEB", object_type: "SPACE_DEBRIS" },
    secondary: { id: "33982", name: "COSMOS 2251 DEB FRAGMENT", object_type: "SPACE_DEBRIS" },
  };
  const originalInfo = console.info;
  const messages = [];
  console.info = (...args) => messages.push(args.join(" "));
  try {
    assert.equal(validateEvent(proxy), null);
    assert.deepEqual(validateAndFilterEvents([proxy]), [proxy]);
  } finally {
    console.info = originalInfo;
  }
  assert.match(messages.join("\n"), /Matching object types do not invalidate a distinct-object pair\./);
  assert.doesNotMatch(messages.join("\n"), /conjunction/i);
});

test("frontend labels only explicit metadata and agrees across Collision and Maneuver identity paths", () => {
  const cases = [
    [{ object_type: "ACTIVE_SATELLITE", category: "active" }, "ACTIVE SATELLITE", "ACTIVE_SATELLITE"],
    [{ object_type: "SPACE_DEBRIS", category: "debris" }, "SPACE DEBRIS", "SPACE_DEBRIS"],
    [{ object_type: "ROCKET_BODY", category: "rocket_body" }, "ROCKET BODY", "ROCKET_BODY"],
    [{ object_type: "UNKNOWN", category: "unknown", name: "ISS DEBRIS ROCKET" }, "UNKNOWN / OTHER", "UNKNOWN"],
    [{ name: "COSMOS 2251 DEB" }, "SPACE DEBRIS", "SPACE_DEBRIS"],
    [{ name: "SL-3 R/B" }, "ROCKET BODY", "ROCKET_BODY"],
    [{ name: "DEB 33757" }, "SPACE DEBRIS", "SPACE_DEBRIS"],
    [{ name: "PAYLOAD 12345" }, "ACTIVE SATELLITE", "ACTIVE_SATELLITE"],
    [{ object_type: "SPACE_DEBRIS", category: "active" }, "SPACE DEBRIS", "SPACE_DEBRIS"],
  ];
  for (const [object, expectedLabel, expectedCode] of cases) {
    assert.equal(getObjectTypeLabel(object), expectedLabel);
    assert.equal(resolveObjectType(object), expectedCode);
  }
  assert.equal(getObjectTypeLabel({ name: "unclassified" }), "UNKNOWN / OTHER");
  assert.equal(getObjectTypeLabel({ category: "debris", name: "SL-3 R/B" }), "ROCKET BODY", "name inference precedes group fallback");
  assert.equal(getObjectTypeLabel({ object_type: "UNKNOWN", name: "ISS DEBRIS ROCKET" }), "UNKNOWN / OTHER", "explicit catalog unknown is preserved");
});

test("Visualization classifies by authoritative object type before group category", () => {
  assert.equal(getVisualizationCategory({ object_type: "ACTIVE SATELLITE", category: "debris" }), "active");
  assert.equal(getVisualizationCategory({ object_type: "SPACE_DEBRIS", category: "active" }), "debris");
  assert.equal(getVisualizationCategory({ object_type: "ROCKET_BODY", category: "debris" }), "rocket_body");
  assert.equal(getVisualizationCategory({ object_type: "UNKNOWN", category: "unknown" }), "other");

  const field = readFileSync(new URL("../src/components/Scene/SatelliteField.jsx", import.meta.url), "utf8");
  assert.match(field, /import \{ getVisualizationCategory \} from "\.\.\/\.\.\/utils\/objectClassification\.js"/);
  assert.match(field, /category === "active" \? "#ffffff"/);
  assert.match(field, /category === "debris" \? "#070a10" : category === "rocket_body" \? "#ffd166"/);
  assert.match(field, /new THREE\.Color\("#cbd5e1"\)/);
  assert.match(field, /meshBasicMaterial[\s\S]*?toneMapped=\{false\}/);
});

test("Visualization contains no Method and availability block", () => {
  const visualization = readFileSync(new URL("../src/components/UI/VisualizationPage.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(visualization, /Method and availability/i);
});

test("bundled synthetic browser fallback does not present generated labels as catalog classifications", () => {
  const snapshot = createFallbackSnapshot();
  assert.equal(snapshot.source_summary.status, "synthetic_demo");
  assert.equal(snapshot.stats.unknown_objects, snapshot.objects.length);
  assert.ok(snapshot.objects.every((object) => object.category === "unknown" && object.object_type === "UNKNOWN"));
  assert.equal(Object.keys(snapshot.objects[0]).includes("_simulatedCategory"), false);
});
