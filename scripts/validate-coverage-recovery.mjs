import assert from "node:assert/strict";
import { chromium, expect as baseExpect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

const origin = "http://127.0.0.1:5173";
const catalog = await (await fetch(origin + "/api/workbench/collective")).json();
const candidates = catalog.items.filter((item) =>
  item.name === "SND - Supply and demand / phase6" && item.symbol === "MNQ",
);
assert.ok(candidates.length, "Expected the reported MNQ Phase 6 evidence");
const folder = `reports/coverage-recovery-${Date.now()}`;
await mkdir(folder, { recursive: true });
const browser = await chromium.launch({ channel: "msedge" });
const expect = baseExpect.configure({ timeout: 30000 });
const results = [];
try {
  for (const item of candidates) {
    for (const [device, viewport] of [
      ["desktop", { width: 1440, height: 900 }],
      ["mobile", { width: 390, height: 844 }],
    ]) {
      const page = await browser.newPage({ viewport });
      page.setDefaultTimeout(30000);
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      // Isolate selection without changing production evidence or user settings.
      // Histories still come from the real, checksum-verified API.
      await page.route("**/api/workbench/collective", (route) => route.fulfill({
        json: { ...catalog, items: [{ ...item, working: true }] },
      }));
      await page.goto(origin + "/#/portfolio");
      await expect(page.getByRole("heading", { name: "Combined book unavailable" })).toBeVisible();
      await expect(page.getByRole("alert")).toContainText(`tested: ${item.start} to ${item.end}`);
      await page.screenshot({ path: `${folder}/${item.id}-${device}-before.png`, animations: "disabled" });
      await page.getByRole("button", { name: "Apply common tested window", exact: true }).click();
      await expect(page.getByTestId("portfolio-metrics")).toBeVisible();
      await expect(page.getByRole("heading", { name: "Combined book unavailable" })).toHaveCount(0);
      if (device === "desktop") {
        await expect(page.getByLabel("P&L start", { exact: true })).toHaveValue(item.start);
        await expect(page.getByLabel("P&L end", { exact: true })).toHaveValue(item.end);
      }
      await page.reload();
      await expect(page.getByTestId("portfolio-metrics")).toBeVisible();
      await page.screenshot({ path: `${folder}/${item.id}-${device}-after.png`, animations: "disabled" });
      assert.deepEqual(errors, []);
      results.push({ id: item.id, device, start: item.start, end: item.end, status: "PASS" });
      await page.close();
    }
  }
  await writeFile(folder + "/validation.json", JSON.stringify(results, null, 2));
  console.log(`PASS: real MNQ Phase 6 coverage recovery and reload on desktop/mobile. ${folder}`);
} finally {
  await browser.close();
}
