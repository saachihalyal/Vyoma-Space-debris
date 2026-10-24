import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const clientSource = readFileSync(new URL("../src/api/ssaClient.js", import.meta.url), "utf8");

async function loadClientWithViteEnv(env) {
  // Model Vite's import.meta.env substitution while keeping this a Node test.
  const source = clientSource.replaceAll("import.meta.env", JSON.stringify(env));
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
  return import(moduleUrl);
}

async function requestCatalogUrl(client) {
  const originalFetch = globalThis.fetch;
  let requestedUrl;
  globalThis.fetch = async (url) => {
    requestedUrl = String(url);
    return new Response(JSON.stringify({ objects: [], risk_cells: [], stats: {} }), { status: 200 });
  };
  try {
    await client.getCatalog({ limit: 25 });
    return requestedUrl;
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test("catalog requests default to the intended backend port 8001", async () => {
  const client = await loadClientWithViteEnv({});
  const requestedUrl = await requestCatalogUrl(client);
  assert.equal(requestedUrl, "http://127.0.0.1:8001/api/catalog?limit=25&forecast_hours=0");
});

test("catalog requests respect an explicit VITE_API_BASE override", async () => {
  const client = await loadClientWithViteEnv({ VITE_API_BASE: "http://127.0.0.1:9000" });
  const requestedUrl = await requestCatalogUrl(client);
  assert.equal(requestedUrl, "http://127.0.0.1:9000/api/catalog?limit=25&forecast_hours=0");
});

test("standalone CDM assessment posts the submitted file to the isolated reference route", async () => {
  const client = await loadClientWithViteEnv({ VITE_API_BASE: "http://127.0.0.1:9100" });
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url: String(url), options };
    return new Response(JSON.stringify({ success: true, data: { event_id: "CDM-test" } }), { status: 200 });
  };
  try {
    const response = await client.calculateReferenceCdmPc({
      cdmText: "reference CDM bytes",
      sourceLabel: "NASA CARA reference",
      assumeIndependentCovariances: true,
    });
    assert.equal(request.url, "http://127.0.0.1:9100/api/collision-probability/cdm");
    assert.equal(request.options.method, "POST");
    assert.deepEqual(JSON.parse(request.options.body), {
      cdm_xml: "reference CDM bytes",
      source_label: "NASA CARA reference",
      assume_independent_covariances: true,
    });
    assert.equal(response.data.event_id, "CDM-test");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
