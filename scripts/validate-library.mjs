import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";

const origin = "http://127.0.0.1:5173";
const api = `${origin}/api/workbench`;
const output = "reports/workbench-validation";
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 1080 } });
const errors = [],
  checks = [],
  runs = [];
page.on("pageerror", (error) => errors.push(error.message));
try {
  await page.goto(origin, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.getByRole("button", { name: "Scripts", exact: true }).click();
  await page
    .getByRole("heading", { name: "Consolidated strategy library" })
    .waitFor();
  const state = await (await fetch(`${api}/state`)).json();
  assert.equal(state.errors.length, 0);
  assert(state.library.total >= 91);
  const signalStrategies = state.strategies.filter(
    (s) => s.execution_model !== "event-v1",
  );
  assert.equal(signalStrategies.length, 5);
  await page.getByLabel("Search strategy library").fill("factor_ls");
  await page.getByText("Adapter required", { exact: true }).waitFor();
  await page
    .getByRole("button", {
      name: "Inspect scripts/cme/factor_ls_backtest.py",
      exact: true,
    })
    .click();
  await page.getByText(/Requires the equity factor panel/).waitFor();
  await page.getByRole("button", { name: "Read original source" }).click();
  await page.getByText("def ls_returns", { exact: false }).waitFor();
  checks.push(
    "Missing factor data has an explicit requirement, original source is readable, and no run button misrepresents readiness",
  );
  const entry = state.library.entries.find(
    (e) => e.path === "scripts/cme/factor_ls_backtest.py",
  );
  const original = await (
    await fetch(`${api}/library/${entry.id}/source`)
  ).json();
  assert.equal(original.file_hash, entry.file_hash);
  assert.equal((await fetch(`${api}/library/unknown/source`)).status, 404);
  await page.keyboard.press("Escape");
  await page.getByLabel("Search strategy library").fill("es_nq_strategies");
  await page
    .getByRole("button", {
      name: "Inspect scripts/es_nq/es_nq_strategies.py",
      exact: true,
    })
    .click();
  await page.getByText(/s_buyhold, s_trend/).waitFor();
  await page
    .getByRole("button", {
      name: "Configure RSI(2) trend-filtered reversion",
      exact: true,
    })
    .click();
  await page.getByLabel("Warmup calendar days", { exact: true }).waitFor();
  assert.equal(
    await page.getByLabel("Warmup calendar days", { exact: true }).inputValue(),
    "400",
  );
  checks.push(
    "Rule collection retains functions and links its RSI adapter to a form with sufficient default warmup",
  );
  for (const strategy of signalStrategies) {
    await page.getByRole("button", { name: "Scripts", exact: true }).click();
    const card = page
      .getByRole("heading", { name: strategy.name, exact: true })
      .locator("..")
      .locator("..");
    await card
      .getByRole("button", { name: "Configure run", exact: true })
      .click();
    await page.getByRole("textbox", { name: "Timeframe", exact: true }).click();
    await page
      .getByRole("option", {
        name: strategy.timeframes.includes("1h")
          ? "1h"
          : strategy.timeframes[0],
        exact: true,
      })
      .click();
    await page
      .getByRole("textbox", { name: "Dataset version", exact: true })
      .click();
    await page.getByRole("option", { name: /^NQ ·/ }).first().click();
    await page
      .getByLabel("Start date (UTC)", { exact: true })
      .fill(strategy.id === "rsi2-reversion" ? "2025-01-02" : "2026-08-03");
    await page
      .getByLabel("End date (UTC, inclusive)", { exact: true })
      .fill(strategy.id === "rsi2-reversion" ? "2025-12-31" : "2026-08-31");
    await page
      .getByLabel("Question / hypothesis", { exact: true })
      .fill(
        `Strategy consolidation validation: ${strategy.id}; ported signals with workbench accounting`,
      );
    await page.getByRole("button", { name: "Validate & preview" }).click();
    await page.getByText("1 job ready", { exact: true }).waitFor();
    const launched = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/workbench/runs") &&
        r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Launch 1 run", exact: true })
      .click();
    const response = await launched;
    const result = await response.json();
    assert.equal(response.status(), 201, JSON.stringify(result));
    runs.push({ id: result[0].id, strategy: strategy.id });
    await page
      .getByRole("heading", { name: "Run ledger", exact: true })
      .waitFor();
  }
  for (const run of runs) {
    let record;
    for (let attempt = 0; attempt < 180; attempt++) {
      record = await (await fetch(`${api}/runs/${run.id}`)).json();
      if (!["Queued", "Running"].includes(record.status)) break;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    assert.equal(record.status, "Succeeded", JSON.stringify(record));
    assert(
      record.result.metrics.trades > 0,
      `${run.strategy} should exercise real trading`,
    );
    assert(record.result.warnings.some((w) => /original|Original/.test(w)));
    run.trades = record.result.metrics.trades;
    run.net_pnl = record.result.metrics.net_pnl;
    checks.push(
      `${run.strategy}: real-data run succeeded with ${run.trades} trades, preserved source, and migration scope in results`,
    );
  }
  await page.getByRole("button", { name: "Scripts", exact: true }).click();
  await page.getByLabel("Search strategy library").fill("");
  await page
    .getByRole("heading", { name: "Consolidated strategy library" })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: `${output}/strategy-library.png`,
    fullPage: false,
  });
  await page
    .getByRole("button", { name: "Runs & Compare", exact: true })
    .click();
  await page.screenshot({
    path: `${output}/consolidated-runs.png`,
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  await writeFile(
    `${output}/strategy-library.json`,
    JSON.stringify(
      { checks, runs, errors, source_count: state.library.total },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ checks, runs, errors }, null, 2));
} catch (error) {
  await page.screenshot({
    path: `${output}/library-failure.png`,
    fullPage: true,
  });
  throw error;
} finally {
  await browser.close();
}
