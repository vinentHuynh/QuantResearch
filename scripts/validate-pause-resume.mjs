import { chromium, expect as baseExpect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
const folder = `reports/pause-validation-${Date.now()}`;
const expect = baseExpect.configure({ timeout: 60000 });
mkdirSync(folder, { recursive: true });
const browser = await chromium.launch({ channel: "msedge" });
const page = await browser.newPage({ viewport: { width: 1500, height: 1050 } });
page.setDefaultTimeout(60000);
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const select = async (label, value) => {
  await page.getByRole("textbox", { name: label, exact: true }).click();
  await page.getByRole("option", { name: value, exact: true }).click();
};
try {
  await page.goto("http://127.0.0.1:5173/#/portfolio/pause");
  await page
    .getByRole("switch", { name: "Enable pause/resume replay" })
    .check();
  await select("Replay mode", "Rolling closed-trade losses");
  await expect(page.getByTestId("gate-status")).toBeVisible({ timeout: 60000 });
  await expect(page.getByTestId("gate-status").locator("tbody tr")).toHaveCount(
    7,
  );
  await page.screenshot({
    path: folder + "/automatic-pause.png",
    fullPage: true,
  });
  await select("Replay mode", "Manual pause / resume schedule");
  await page
    .getByRole("textbox", { name: "Strategy to control", exact: true })
    .click();
  await page.getByRole("option").first().click();
  await page.getByLabel("Effective time (UTC)").fill("2024-01-01T00:00");
  await page.getByLabel("Decision reason").fill("Review exposure");
  await page.getByRole("button", { name: "Add decision", exact: true }).click();
  await expect(
    page
      .getByTestId("manual-schedule")
      .getByRole("button", { name: /^Remove pause/ }),
  ).toHaveCount(1);
  await expect(
    page.getByTestId("gate-status").getByText("Paused", { exact: true }),
  ).toHaveCount(1);
  await page.getByLabel("Decision reason").fill("Duplicate must fail");
  await page.getByRole("button", { name: "Add decision", exact: true }).click();
  await expect(
    page.getByText(
      "A decision already exists at that time. Remove it before replacing it.",
    ),
  ).toBeVisible();
  await page.getByLabel("Effective time (UTC)").fill("2025-01-01T00:00");
  await select("Manual action", "Resume new entries");
  await page.getByLabel("Decision reason").fill("Review complete");
  await page.getByRole("button", { name: "Add decision", exact: true }).click();
  await expect(
    page.getByTestId("gate-status").getByText("Enabled", { exact: true }),
  ).toHaveCount(7);
  await expect(
    page
      .getByTestId("manual-schedule")
      .getByRole("button", { name: /^Remove/ }),
  ).toHaveCount(2);
  const comparison = await page.getByTestId("policy-comparison").innerText();
  await page.reload();
  await expect(
    page
      .getByTestId("manual-schedule")
      .getByRole("button", { name: /^Remove/ }),
  ).toHaveCount(2);
  await expect(page.getByTestId("policy-comparison")).toHaveText(comparison, { useInnerText: true });
  const downloadEvent = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export decisions", exact: true })
    .click();
  await (await downloadEvent).saveAs(folder + "/manual-decisions.csv");
  await page.screenshot({ path: folder + "/manual-pause.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
    "Mobile overflow",
  );
  await page.screenshot({
    path: folder + "/manual-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1500, height: 1050 });
  await page
    .getByTestId("manual-schedule")
    .getByRole("button", { name: /^Remove resume/ })
    .click();
  await expect(
    page.getByTestId("gate-status").getByText("Paused", { exact: true }),
  ).toHaveCount(1);
  await page
    .getByRole("switch", { name: "Enable pause/resume replay" })
    .uncheck();
  await expect(
    page.getByRole("heading", { name: "Replay is off" }),
  ).toBeVisible();
  await page
    .getByRole("switch", { name: "Enable pause/resume replay" })
    .check();
  await expect(
    page
      .getByTestId("manual-schedule")
      .getByRole("button", { name: /^Remove pause/ }),
  ).toHaveCount(1);
  await page
    .getByTestId("manual-schedule")
    .getByRole("button", { name: /^Remove pause/ })
    .click();
  await expect(
    page.getByTestId("gate-status").getByText("Enabled", { exact: true }),
  ).toHaveCount(7);
  for (const mode of [
    "Consecutive losing trades",
    "Shadow equity drawdown",
    "Scale size by realized volatility (no pause)",
    "Rolling closed-trade losses",
  ]) {
    await select("Replay mode", mode);
    await expect(page.getByTestId("policy-comparison")).toBeVisible();
  }
  assert.deepEqual(errors, []);
  writeFileSync(
    folder + "/browser-validation.json",
    JSON.stringify(
      {
        checked_at: new Date().toISOString(),
        status: "PASS",
        errors,
        checks: [
          "automatic per-book status",
          "manual pause and resume",
          "duplicate timestamp rejection",
          "persistence after reload",
          "decision export",
          "remove decision",
          "disable/enable retains schedule",
          "all replay modes",
          "mobile overflow",
        ],
      },
      null,
      2,
    ),
  );
  console.log("Pause/resume browser checks passed.");
} catch (error) {
  await page.screenshot({
    path: folder + "/browser-failure.png",
    fullPage: true,
  });
  console.log((await page.locator("body").innerText()).slice(-4000));
  throw error;
} finally {
  await browser.close();
}
