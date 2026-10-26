import { chromium } from "playwright";
import fs from "node:fs/promises";
const browser = await chromium.launch({ headless: true, executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe" });
const page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
page.setDefaultTimeout(30000);
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.goto("http://127.0.0.1:5173", { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => Number(document.querySelector(".og-home")?.innerText.match(/(\d+) objects tracked/)?.[1] || 0) > 0, null, { timeout: 60000 });
await page.waitForTimeout(500);
await page.screenshot({ path: "screenshots/home.png", fullPage: true });
await page.getByRole("button", { name: "Visualization", exact: true }).click();
await page.getByRole("heading", { name: "Visualization" }).waitFor();
await page.waitForFunction(() => Number(document.querySelector(".visualization-page")?.getAttribute("data-object-count")) > 0 || document.querySelectorAll("canvas").length > 0, null, { timeout: 60000 });
await page.waitForTimeout(1500);
let tooltipFound = false;
for (const canvas of await page.locator("canvas").all()) {
  const box = await canvas.boundingBox(); if (!box) continue;
  for (let y = 0.1; y < 0.95 && !tooltipFound; y += 0.025) for (let x = 0.05; x < 0.95 && !tooltipFound; x += 0.025) {
    await page.mouse.move(box.x + box.width * x, box.y + box.height * y); await page.waitForTimeout(20);
    tooltipFound = await page.locator(".globe-hover-tooltip").count() > 0;
  }
  if (tooltipFound) break;
}
await page.screenshot({ path: "screenshots/visualization-hover.png", fullPage: true });
await page.getByRole("button", { name: "Smart Filter", exact: true }).click();
await page.getByRole("heading", { name: "Smart Filter" }).waitFor(); await page.waitForTimeout(1000);
await page.screenshot({ path: "screenshots/smart-filter.png", fullPage: true });
await page.getByRole("button", { name: "Collision Analysis", exact: true }).click();
await page.getByRole("heading", { name: "Collision Analysis" }).waitFor(); await page.waitForTimeout(800);
await page.screenshot({ path: "screenshots/collision-analysis-demo.png", fullPage: true });
await page.getByRole("button", { name: "Maneuver", exact: true }).click();
await page.getByRole("heading", { name: "Maneuver" }).waitFor();
await page.getByRole("button", { name: "Try sample conjunction" }).click();
await page.waitForTimeout(10000);
await page.screenshot({ path: "screenshots/maneuver-demo-result.png", fullPage: true });
await fs.writeFile("screenshots/maneuver-demo-browser.txt", await page.locator(".og-maneuver").innerText());
await page.getByRole("button", { name: "Catalog Analytics", exact: true }).click();
await page.getByRole("heading", { name: "Catalog Heuristic Analysis" }).waitFor(); await page.waitForTimeout(2500);
await page.screenshot({ path: "screenshots/catalog-analytics.png", fullPage: true });
await fs.writeFile("screenshots/stable-final-pass-browser.json", JSON.stringify({ tooltipFound, pageErrors: errors }, null, 2));
await browser.close();
