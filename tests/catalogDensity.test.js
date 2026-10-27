import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildCatalogDensityBins, buildCloseApproachMarkers, commonCatalogEpoch } from "../src/utils/catalogDensity.js";

const epoch = "2026-01-01T00:00:00Z";
const objects = [
  { id: "1", category: "active", position: [7000, 0, 0], provenance: { reference_frame: "TEME", propagation_epoch: epoch } },
  { id: "2", category: "debris", position: [0, 7000, 0], provenance: { reference_frame: "TEME", propagation_epoch: epoch } },
];

test("catalog density requires a shared propagated TEME epoch", () => {
  assert.equal(commonCatalogEpoch(objects), epoch);
  assert.equal(commonCatalogEpoch([objects[0], { ...objects[1], provenance: { ...objects[1].provenance, propagation_epoch: "2026-01-02T00:00:00Z" } }]), null);
  assert.equal(commonCatalogEpoch([{ ...objects[0], provenance: { ...objects[0].provenance, reference_frame: "ITRF" } }]), null);
});

test("catalog density bins apply satellite, debris, and combined filters", () => {
  assert.equal(buildCatalogDensityBins(objects, epoch, "satellites").reduce((sum, bin) => sum + bin.count, 0), 1);
  assert.equal(buildCatalogDensityBins(objects, epoch, "debris").reduce((sum, bin) => sum + bin.count, 0), 1);
  assert.equal(buildCatalogDensityBins(objects, epoch, "both").reduce((sum, bin) => sum + bin.count, 0), 2);
});

test("saved event markers use the common-epoch positions of both pair members", () => {
  const markers = buildCloseApproachMarkers(objects, [{ id: "pair-1", primary: { id: "1", name: "Sat A" }, secondary: { id: "2", name: "Debris B" } }], epoch);
  assert.equal(markers.length, 1);
  assert.equal(markers[0].id, "pair-1");
  assert.match(markers[0].label, /Sat A/);
  assert.ok(Number.isFinite(markers[0].latitude));
  assert.ok(Number.isFinite(markers[0].longitude));
  assert.equal(buildCloseApproachMarkers(objects, [{ primary: { id: "missing" }, secondary: { id: "2" } }], epoch).length, 0);
});

test("Catalog Analytics keeps the orbit band and matrix, with no forecast or scatter panel", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const start = source.indexOf("function AnalyticsPage(");
  const end = source.indexOf("function ReportsPage(", start);
  const page = source.slice(start, end);
  assert.match(page, /Current Catalog by Orbit Band/);
  assert.match(page, /Current Screening Proxy Matrix/);
  assert.match(page, /CatalogDensityGlobe objects=\{objects\} events=\{catalogEvents\}/);
  assert.doesNotMatch(page, /168-Hour|Forecast|Scatter|Screening Proxy Scatter/);
  assert.match(source, /catalogEvents=\{eventLibrary\?\.events \|\| \[\]\}/);
});
