import { chromium } from "playwright";
import fs from "node:fs/promises";
const browser = await chromium.launch({ headless: true, executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe" });
const page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
page.setDefaultTimeout(30000);
await page.goto("http://127.0.0.1:5173", { waitUntil: "domcontentloaded" });
await page.getByRole("button", { name: "Maneuver", exact: true }).click();
await page.getByRole("heading", { name: "Maneuver" }).waitFor();
await page.getByRole("button", { name: "Try sample conjunction" }).click();
await page.waitForTimeout(10000);
await page.screenshot({ path: "screenshots/maneuver-demo-result.png", fullPage: true });
const result = await page.locator(".og-maneuver").innerText();
await fs.writeFile("screenshots/maneuver-demo-browser.txt", result);
const pdfButton = page.getByRole("button", { name: "Download Reference Maneuver Report" });
if (await pdfButton.count()) {
  const downloadPromise = page.waitForEvent("download");
  await pdfButton.click();
  const download = await downloadPromise;
  await download.saveAs("output/pdf/vyoma-maneuver-demo-report.pdf");
}
await browser.close();
