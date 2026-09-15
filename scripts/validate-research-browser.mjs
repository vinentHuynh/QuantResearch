import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";

const base = "http://127.0.0.1:5173",
  output = "reports/workbench-validation";
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
const errors = [],
  checks = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await page.goto(base);
  await page
    .getByRole("button", { name: "Evaluation & Regimes", exact: true })
    .click();
  await page
    .getByRole("heading", {
      name: "Plan a walk-forward evaluation",
      exact: true,
    })
    .waitFor();
  await page
    .getByRole("textbox", { name: "Starting run", exact: true })
    .click();
  await page
    .getByRole("option", { name: /Moving-average trend · NQ/ })
    .first()
    .click();
  await page
    .getByLabel("Evaluation name", { exact: true })
    .fill("NQ phase 4 browser validation");
  await page
    .getByLabel("Research interval starts (UTC)", { exact: true })
    .fill("2026-07-01");
  await page
    .getByLabel("Research interval ends (UTC)", { exact: true })
    .fill("2026-08-31");
  await page.getByLabel("Training calendar days", { exact: true }).fill("30");
  await page.getByLabel("Test calendar days", { exact: true }).fill("14");
  await page.getByLabel("Number of folds", { exact: true }).fill("2");
  await page
    .getByLabel("Minimum combined test trades", { exact: true })
    .fill("1");
  await page
    .getByLabel("Candidate parameter grid (JSON)", { exact: true })
    .fill('{"lookback":[10,20]}');
  await page
    .getByLabel("Evaluation hypothesis", { exact: true })
    .fill(
      "Validate a frozen rolling selection rule and implementation stress across subsequent NQ intervals.",
    );
  await page
    .getByRole("button", { name: "Preview evaluation", exact: true })
    .click();
  await page
    .getByText("10 planned jobs · 2 chronological folds", { exact: true })
    .waitFor();
  await page.screenshot({
    path: `${output}/research-plan.png`,
    fullPage: true,
  });
  checks.push(
    "Research form previews candidate count and chronological fold boundaries",
  );
  const responsePromise = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/workbench/evaluations") &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Launch walk-forward", exact: true })
    .click();
  const response = await responsePromise,
    evaluation = await response.json();
  assert.equal(response.status(), 201, JSON.stringify(evaluation));
  await page.reload();
  await page
    .getByRole("button", { name: "Evaluation & Regimes", exact: true })
    .click();
  let record;
  for (let i = 0; i < 120; i++) {
    record = await (
      await page.request.get(
        `${base}/api/workbench/evaluations/${evaluation.id}`,
      )
    ).json();
    if (record.status === "Succeeded") break;
    if (["Failed", "Canceled"].includes(record.status))
      throw new Error(JSON.stringify(record));
    await new Promise((r) => setTimeout(r, 1000));
  }
  assert.equal(record.status, "Succeeded");
  assert.equal(record.runs.length, 10);
  await page
    .getByRole("heading", { name: "Joined subsequent test path", exact: true })
    .waitFor();
  await page
    .getByRole("img", { name: "Walk-forward test equity", exact: true })
    .waitFor();
  checks.push(
    "Ten real-data jobs complete across refresh; sensitivity, selection lineage and test scenarios render",
  );
  await page.screenshot({
    path: `${output}/research-evaluation.png`,
    fullPage: true,
  });
  const regimePromise = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/evaluations/${evaluation.id}/regimes`) &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run regime investigation", exact: true })
    .click();
  const regime = await (await regimePromise).json();
  let investigation;
  for (let i = 0; i < 90; i++) {
    const state = await (
      await page.request.get(`${base}/api/workbench/state`)
    ).json();
    investigation = state.regimes.find((r) => r.id === regime.id);
    if (investigation.status === "Succeeded") break;
    if (["Failed", "Interrupted"].includes(investigation.status))
      throw new Error(JSON.stringify(investigation));
    await new Promise((r) => setTimeout(r, 1000));
  }
  assert.equal(investigation.status, "Succeeded");
  await page
    .getByText("Historical conditional attribution", { exact: true })
    .waitFor();
  checks.push(
    "Training-calibrated volatility investigation renders episodes, costs and uncertainty",
  );
  await page.screenshot({
    path: `${output}/research-regimes.png`,
    fullPage: true,
  });
  const csv = await page.request.get(
    `${base}/api/workbench/research-artifact?kind=regimes&id=${regime.id}&name=observations.csv`,
  );
  assert.equal(csv.status(), 200);
  assert((await csv.text()).includes("threshold"));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: `${output}/research-mobile.png`,
    fullPage: true,
  });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  assert.deepEqual(errors, []);
  checks.push(
    "Research artifact download, mobile layout and browser runtime checks pass",
  );
  const result = {
    checked_at: new Date().toISOString(),
    evaluation_id: evaluation.id,
    regime_id: regime.id,
    checks,
    errors,
  };
  await writeFile(
    `${output}/research-browser-results.json`,
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  await page.screenshot({
    path: `${output}/research-failure.png`,
    fullPage: true,
  });
  console.error(error);
  process.exitCode = 1;
} finally {
  await browser.close();
}
