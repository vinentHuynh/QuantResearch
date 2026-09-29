import { chromium, expect as baseExpect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
const expect = baseExpect.configure({ timeout: 60000 });
const folder = `reports/sizing-ui-${new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-")}`;
mkdirSync(folder, { recursive: true });
const browser = await chromium.launch({ channel: "msedge" });
const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
page.setDefaultTimeout(60000);
const errors = [];
const requests = [];
page.on("request", r => { if (r.url().includes("/collective")) requests.push({ event: "request", url: r.url(), at: Date.now() }); });
page.on("response", async r => { if (r.url().includes("/collective")) requests.push({ event: "response", url: r.url(), status: r.status(), at: Date.now() }); });
page.on("requestfailed", r => { if (r.url().includes("/collective")) requests.push({ event: "failed", url: r.url(), error: r.failure(), at: Date.now() }); });
page.on("pageerror", (e) => errors.push(e.message));
const select = async (label, value) => {
  await page.getByRole("textbox", { name: label, exact: true }).click();
  await page.getByRole("option", { name: value, exact: true }).click();
};
try {
  await page.goto("http://127.0.0.1:5173/#/portfolio/pause");
  await expect(page.getByTestId("sizing-benchmarks")).toBeVisible();
  await page
    .getByRole("switch", { name: "Enable pause/resume replay" })
    .check();
  await expect(
    page.getByRole("textbox", { name: "Replay mode", exact: true }),
  ).toHaveValue("Constant size (no pause)");
  await expect(page.getByTestId("sizing-benchmarks")).toContainText(
    "$508,953.75",
  );
  await select("Replay mode", "Portfolio-aware volatility sizing");
  await expect(page.getByLabel("Calibration end (UTC)")).toHaveValue(
    "2023-12-31",
  );
  await expect(page.getByTestId("sizing-validation")).toBeVisible();
  await expect(page.getByTestId("policy-comparison")).toContainText(
    "With volatility scaling",
  );
  const before = await page.getByTestId("policy-comparison").innerText();
  await page.reload();
  await expect(page.getByTestId("policy-comparison")).toHaveText(before, {
    useInnerText: true,
  });
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export comparison", exact: true })
    .click();
  await (await download).saveAs(folder + "/comparison.csv");
  await page.screenshot({
    path: folder + "/portfolio-sizing.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
    "Mobile overflow",
  );
  await page.screenshot({
    path: folder + "/mobile-sizing.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1500, height: 1100 });
  await select("Replay mode", "Sustained deterioration / manual review");
  await expect(page.getByTestId("manual-schedule")).toBeVisible();
  await expect(page.getByTestId("gate-status")).toContainText(
    "Monitoring normalized outcomes",
  );
  await page.getByLabel("Calibration end (UTC)").fill("2024-01-01");
  await expect(
    page.getByText(
      "The reporting period must start after the frozen calibration end date.",
    ),
  ).toBeVisible();
  await page.getByLabel("Calibration end (UTC)").fill("2023-12-31");
  await expect(page.getByTestId("sizing-benchmarks")).toBeVisible();
  await select("Replay mode", "Constant size (no pause)");
  await page.getByLabel("Round down to recorded whole contracts").check();
  await expect(page.getByTestId("sizing-validation")).toContainText(
    "Whole-contract rounding: on",
  );
  await page
    .getByRole("switch", { name: "Enable pause/resume replay" })
    .uncheck();
  await expect(
    page.getByRole("heading", { name: "Replay is off" }),
  ).toBeVisible();
  await expect(page.getByTestId("sizing-benchmarks")).toContainText(
    "$678,605.00",
  );
  assert.deepEqual(errors, []);
  writeFileSync(
    folder + "/checks.json",
    JSON.stringify(
      {
        errors,
        checks: [
          "default fixed sizing",
          "benchmarks",
          "portfolio mode",
          "frozen calibration",
          "persistence",
          "CSV",
          "mobile",
          "deterioration manual review",
          "date validation",
          "whole contracts",
          "disabled baseline",
        ],
      },
      null,
      2,
    ),
  );
  console.log(folder);
} finally {
  writeFileSync(folder + "/requests.json", JSON.stringify(requests, null, 2));
  writeFileSync(folder + "/last-page.txt", await page.locator("body").innerText());
  await browser.close();
}
