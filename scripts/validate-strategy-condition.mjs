import { chromium, expect as baseExpect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
const expect = baseExpect.configure({ timeout: 60000 });
const folder = `reports/condition-ui-${new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-")}`;
mkdirSync(folder, { recursive: true });
const browser = await chromium.launch({ channel: "msedge" });
const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
page.setDefaultTimeout(60000);
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await page.goto("http://127.0.0.1:5173/#/portfolio/pause");
  const panel = page.getByTestId("strategy-condition");
  await expect(panel).toBeVisible();
  await expect(panel.locator("article")).toHaveCount(7);
  await expect(panel).toContainText("Current status unavailable");
  await expect(panel).toContainText("Historical snapshot: 2026-08-31");
  await expect(panel).toContainText("Watch — recent losses");
  await expect(panel).toContainText(
    "Entry permission at 2026-08-31: Replay off",
  );
  await expect(panel).toContainText("bootstrap family alarm target");
  await expect(panel).toContainText("Volatility sensitivity");
  const exportStatus = async (name) => {
    const promise = page.waitForEvent("download");
    await panel.getByRole("button", { name: "Export condition" }).click();
    await (await promise).saveAs(`${folder}/${name}.json`);
    return JSON.parse(readFileSync(`${folder}/${name}.json`, "utf8"));
  };
  const before = await exportStatus("latest");
  assert.equal(before.assessments.length, 7);
  assert(before.assessments.every((s) => !s.available));
  assert(before.assessments.every((s) => s.checksum && s.last20.count === 20));
  await panel.getByText("Selected date", { exact: true }).click();
  await expect(
    panel.getByText("Current status unavailable", { exact: true }),
  ).toHaveCount(0);
  const selected = await exportStatus("selected");
  assert(selected.assessments.every((s) => s.available));
  await page
    .getByRole("switch", { name: "Enable pause/resume replay" })
    .check();
  await page.getByRole("textbox", { name: "Replay mode", exact: true }).click();
  await page
    .getByRole("option", {
      name: "Manual pause / resume schedule",
      exact: true,
    })
    .click();
  const after = await exportStatus("manual");
  assert.deepEqual(
    after.assessments,
    selected.assessments,
    "Controller must not alter condition",
  );
  await expect(panel).toContainText("Entry permission at 2026-08-31: Enabled");
  await panel.locator("summary").first().click();
  await expect(panel).toContainText("Terminal marks are excluded");
  await page.screenshot({ path: `${folder}/desktop.png`, fullPage: true });
  await panel
    .locator("article")
    .first()
    .screenshot({ path: `${folder}/condition-detail.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
    "Mobile page overflow",
  );
  await page.screenshot({ path: `${folder}/mobile.png`, fullPage: true });
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${folder}/mobile-viewport.png` });
  assert.deepEqual(errors, []);
  writeFileSync(
    `${folder}/checks.json`,
    JSON.stringify(
      {
        errors,
        checks: [
          "seven conditions",
          "stale snapshot",
          "dated windows",
          "calibration evidence",
          "JSON export",
          "historical cutoff",
          "permission independence",
          "mobile",
        ],
      },
      null,
      2,
    ),
  );
  console.log(folder);
} finally {
  await browser.close();
}
