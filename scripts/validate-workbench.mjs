import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";

const output = "reports/workbench-validation";
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const base = "http://127.0.0.1:5173";
const checks = [];
try {
  await page.goto(base);
  await page
    .getByRole("heading", { name: "Every experiment, in context." })
    .waitFor();
  checks.push("Runs & Compare is the landing page");
  await page.getByRole("button", { name: "Datasets", exact: true }).click();
  await page.getByText("Local archive ingestion", { exact: true }).waitFor();
  for (const symbol of ["NQ", "ES", "YM", "CL"])
    await page.getByText(symbol, { exact: true }).waitFor();
  await page.screenshot({ path: `${output}/datasets.png`, fullPage: true });
  checks.push("All four ZIP datasets are registered and visible");
  await page.getByRole("button", { name: "Scripts", exact: true }).click();
  await page
    .getByRole("heading", { name: "Moving-average trend", exact: true })
    .locator("..")
    .locator("..")
    .getByRole("button", { name: "Configure run", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Dataset version", exact: true })
    .click();
  await page.getByRole("option", { name: /^NQ ·/ }).first().click();
  await page.getByLabel("Start date (UTC)", { exact: true }).fill("2026-08-03");
  await page
    .getByLabel("End date (UTC, inclusive)", { exact: true })
    .fill("2026-08-31");
  await page
    .getByLabel("Question / hypothesis", { exact: true })
    .fill(
      "Application validation: neighboring moving-average lookbacks across NQ, ES, YM and CL",
    );
  for (const symbol of ["ES", "YM", "CL"]) {
    await page
      .getByRole("textbox", {
        name: "Additional dataset versions",
        exact: true,
      })
      .click();
    await page
      .getByRole("option", { name: new RegExp("^" + symbol + " ·") })
      .first()
      .click();
    await page.keyboard.press("Escape");
  }
  await page
    .getByLabel("Parameter sweep (JSON)", { exact: true })
    .fill('{"lookback": [10, 20]}');
  await page.getByRole("button", { name: "Validate & preview" }).click();
  await page.getByText("8 jobs ready", { exact: true }).waitFor();
  await page.screenshot({ path: `${output}/new-run.png`, fullPage: true });
  const launched = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/workbench/runs") &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Launch 8 runs", exact: true })
    .click();
  const response = await launched;
  const runs = await response.json();
  assert.equal(response.status(), 201, JSON.stringify(runs));
  assert.equal(runs.length, 8);
  checks.push(
    "Generated form previews and launches eight runs across four real markets and two lookbacks",
  );
  await page.reload();
  await page.getByRole("heading", { name: "Run ledger" }).waitFor();
  for (const run of runs) {
    for (let i = 0; i < 90; i++) {
      const result = await page.request.get(
        `${base}/api/workbench/runs/${run.id}`,
      );
      const record = await result.json();
      if (record.status === "Succeeded") break;
      if (["Failed", "Canceled", "Interrupted"].includes(record.status))
        throw new Error(JSON.stringify(record));
      if (i === 89) throw new Error("Run completion timeout");
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  checks.push("Queued jobs survive page refresh and succeed on real ZIP data");
  await page.reload();
  for (const run of runs.slice(0, 2))
    await page.getByRole("checkbox", { name: `Compare ${run.id}` }).check();
  await page
    .getByRole("button", { name: "Compare as run", exact: true })
    .click();
  await page.getByRole("heading", { name: "As run comparison" }).waitFor();
  await page
    .getByRole("button", { name: "Align evaluation interval", exact: true })
    .click();
  await page.getByRole("heading", { name: "Aligned comparison" }).waitFor();
  checks.push("As-run and aligned comparisons render saved runs");
  await page.screenshot({ path: `${output}/runs-compare.png`, fullPage: true });
  const row = page.getByRole("row").filter({
    has: page.getByRole("checkbox", { name: `Compare ${runs[0].id}` }),
  });
  await row.getByRole("button", { name: "Inspect", exact: true }).click();
  await page.getByRole("img", { name: "Equity curve in US dollars" }).waitFor();
  await page.getByRole("img", { name: "Continuous drawdown chart" }).waitFor();
  await page
    .getByLabel("Research notes", { exact: true })
    .fill(
      "Validated through the browser on local archived data. This is a workflow check, not strategy approval.",
    );
  await page.getByLabel("Tags", { exact: true }).fill("app-validation");
  await page.getByRole("button", { name: "Save notes", exact: true }).click();
  await page
    .getByLabel("Reason for freezing this configuration", { exact: true })
    .fill("Validate frozen replay workflow; no trading eligibility claim.");
  await page
    .getByRole("button", { name: "Freeze in watchlist", exact: true })
    .click();
  await page.screenshot({ path: `${output}/run-detail.png`, fullPage: true });
  checks.push(
    "Equity, logs, research notes, artifacts and watchlist freeze work",
  );
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await page
    .getByText(
      "Validate frozen replay workflow; no trading eligibility claim.",
      { exact: true },
    )
    .first()
    .waitFor();
  await page
    .getByRole("button", { name: "Run on latest data", exact: true })
    .first()
    .click();
  await page.screenshot({ path: `${output}/watchlist.png`, fullPage: true });
  checks.push(
    "Frozen configuration can be queued through the latest data endpoint",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("button", { name: "Runs & Compare", exact: true })
    .click();
  await page.screenshot({ path: `${output}/mobile.png`, fullPage: true });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  assert.equal(overflow, false, "Page must fit mobile viewport");
  assert.deepEqual(errors, [], "Browser runtime errors");
  checks.push("Mobile layout fits viewport; no uncaught browser errors");
  await writeFile(
    `${output}/browser-results.json`,
    JSON.stringify(
      {
        checked_at: new Date().toISOString(),
        checks,
        run_ids: runs.map((r) => r.id),
        errors,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({ checks, run_ids: runs.map((r) => r.id), errors }, null, 2),
  );
} catch (error) {
  await page.screenshot({ path: `${output}/failure.png`, fullPage: true });
  console.error(error);
  process.exitCode = 1;
} finally {
  await browser.close();
}
