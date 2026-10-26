import { chromium } from "playwright";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";

const base = "http://127.0.0.1:5173";
const out = fileURLToPath(new URL("../screenshots/", import.meta.url));
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe" });
const page = await browser.newPage({ viewport: { width: 1600, height: 1050 }, deviceScaleFactor: 1 });
page.setDefaultTimeout(30000);
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const t0 = Date.now();
await page.goto(base, { waitUntil: "domcontentloaded" });
await page.locator(".og-home").waitFor();
await page.waitForFunction(() => document.querySelector(".og-home")?.innerText.match(/\d+ objects tracked/), null, { timeout: 120000 });
await page.waitForTimeout(1000);
const homeReadyMs = Date.now() - t0;
await page.screenshot({ path: `${out}/home.png`, fullPage: true });

async function nav(label) {
  await page.getByRole("button", { name: label, exact: true }).first().click();
  await page.waitForTimeout(1200);
}
await nav("Visualization");
await page.getByRole("heading", { name: "Visualization" }).waitFor({ timeout: 30000 });
await page.waitForTimeout(3000);
const canvases = await page.locator("canvas").all();
let tooltipFound = false;
for (const canvas of canvases) {
  const box = await canvas.boundingBox();
  if (!box) continue;
  for (let y = 0.15; y < 0.9 && !tooltipFound; y += 0.035) {
    for (let x = 0.12; x < 0.92 && !tooltipFound; x += 0.035) {
      await page.mouse.move(box.x + box.width * x, box.y + box.height * y);
      await page.waitForTimeout(30);
      tooltipFound = await page.locator(".globe-hover-tooltip").count() > 0;
    }
  }
  if (tooltipFound) break;
}
await page.screenshot({ path: `${out}/visualization-hover.png`, fullPage: true });

await nav("Smart Filter");
await page.getByRole("heading", { name: "Smart Filter" }).waitFor({ timeout: 30000 });
await page.waitForTimeout(1500);
await page.screenshot({ path: `${out}/smart-filter.png`, fullPage: true });

await nav("Collision Analysis");
await page.getByRole("heading", { name: "Collision Analysis" }).waitFor({ timeout: 30000 });
let screeningStartedAt = null;
if (await page.getByRole("button", { name: "Run full screening" }).count()) {
  screeningStartedAt = Date.now();
  await page.getByRole("button", { name: "Run full screening" }).first().click();
}
await page.waitForTimeout(1500);
await page.screenshot({ path: `${out}/collision-analysis-demo.png`, fullPage: true });
let screeningStatus = "not started";
if (screeningStartedAt) {
  for (let i = 0; i < 360; i++) {
    await page.waitForTimeout(5000);
    screeningStatus = await page.locator(".collision-screening-controls").innerText().catch(() => "status unavailable");
    if (/Screening: Completed|Screening: Failed/.test(screeningStatus)) break;
  }
  await page.screenshot({ path: `${out}/collision-analysis-demo.png`, fullPage: true });
}

await nav("Maneuver");
await page.getByRole("heading", { name: "Maneuver" }).waitFor({ timeout: 30000 });
await page.getByRole("button", { name: "Try sample conjunction" }).click();
await page.waitForFunction(() => /Before and after|No maneuver needed/.test(document.querySelector(".og-maneuver")?.innerText || ""), null, { timeout: 120000 });
await page.waitForTimeout(2000);
const maneuverText = await page.locator(".og-maneuver").innerText();
await page.screenshot({ path: `${out}/maneuver-demo-result.png`, fullPage: true });

await nav("Catalog Analytics");
await page.getByRole("heading", { name: "Catalog Heuristic Analysis" }).waitFor({ timeout: 30000 });
await page.waitForTimeout(2000);
await page.screenshot({ path: `${out}/catalog-analytics.png`, fullPage: true });

await fs.writeFile(`${out}/final-pass-browser.json`, JSON.stringify({ homeReadyMs, tooltipFound, screeningStartedAt: screeningStartedAt ? new Date(screeningStartedAt).toISOString() : null, screeningStatus, maneuverText, pageErrors: errors }, null, 2));
await browser.close();
