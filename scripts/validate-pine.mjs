import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";

const origin = "http://127.0.0.1:5173";
const api = `${origin}/api/workbench`;
const output = "reports/workbench-validation";
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 1050 } });
const errors = [],
  checks = [],
  runs = [];
page.on("pageerror", (error) => errors.push(error.message));
async function post(route, body, expected = 201) {
  const response = await fetch(`${api}${route}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const value = await response.json();
  assert.equal(response.status, expected, JSON.stringify(value));
  return value;
}
try {
  await page.goto(origin, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.getByRole("button", { name: "Scripts", exact: true }).click();
  await page
    .getByRole("heading", { name: "Consolidated strategy library" })
    .waitFor();
  const state = await (await fetch(`${api}/state`)).json();
  assert.deepEqual(state.errors, []);
  const ports = state.strategies.filter(
    (s) => s.execution_model === "event-v1",
  );
  assert.equal(ports.length, 4);
  const pine = state.library.entries.filter((e) => e.path.endsWith(".pine"));
  assert.equal(pine.length, 17);
  await page
    .getByLabel("Search strategy library")
    .fill("SND_phase6_strategy.pine");
  await page
    .getByRole("button", {
      name: "Inspect SND_phase6_strategy.pine",
      exact: true,
    })
    .click();
  await page
    .getByRole("heading", { name: "Existing Python counterparts" })
    .waitFor();
  await page.keyboard.press("Escape");
  await page
    .getByLabel("Search strategy library")
    .fill("pine/cme_tsmom_intraday_orb_strategy.pine");
  await page
    .getByRole("button", {
      name: "Inspect pine/cme_tsmom_intraday_orb_strategy.pine",
      exact: true,
    })
    .click();
  await page
    .getByRole("button", { name: "Read original source", exact: true })
    .click();
  await page
    .getByText('strategy("CME TSMOM Intraday ORB', { exact: false })
    .waitFor();
  await page
    .getByRole("button", {
      name: "Configure Pine · TSMOM intraday ORB",
      exact: true,
    })
    .click();
  assert.equal(
    await page
      .getByRole("textbox", { name: "Session", exact: true })
      .inputValue(),
    "Full Globex day",
  );
  assert.equal(
    await page.getByLabel("Warmup calendar days", { exact: true }).inputValue(),
    "600",
  );
  await page
    .getByRole("textbox", { name: "Dataset version", exact: true })
    .click();
  await page.getByRole("option", { name: /^NQ ·/ }).first().click();
  await page.getByLabel("Start date (UTC)", { exact: true }).fill("2026-08-03");
  await page
    .getByLabel("End date (UTC, inclusive)", { exact: true })
    .fill("2026-08-31");
  await page.getByLabel("risk budget", { exact: true }).fill("3000");
  await page
    .getByLabel("Question / hypothesis", { exact: true })
    .fill(
      "Pine port validation: exercise full-size NQ bracket fills with an explicit $3000 test budget",
    );
  await page.getByRole("button", { name: "Validate & preview" }).click();
  await page.getByText("1 job ready", { exact: true }).waitFor();
  const launched = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/workbench/runs") &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Launch 1 run", exact: true }).click();
  const response = await launched;
  const result = await response.json();
  assert.equal(response.status(), 201, JSON.stringify(result));
  runs.push(result[0]);
  await page
    .getByRole("heading", { name: "Run ledger", exact: true })
    .waitFor();
  checks.push(
    "Pine sources/counterparts visible; ORB form selects full session and warmup; real-data bracket run launched through UI",
  );
  const dataset = state.datasets.find((d) => d.symbol === "NQ");
  for (const strategy of ports.filter((s) => s.id !== "pine-tsmom-orb")) {
    const input = {
      strategy_id: strategy.id,
      dataset_id: dataset.id,
      start: "2026-08-03",
      end: "2026-08-31",
      timeframe: strategy.timeframes[0],
      session: "full-trading-day",
      parameters: {},
      capital: 1000000,
      fee: 1.25,
      slippage: 1,
      warmup_days: strategy.default_warmup_days || 60,
      timeout: 240,
      stage: "Exploratory",
      hypothesis: `Pine port validation: ${strategy.id}; $1m test capital exercises default whole-contract volatility sizing`,
    };
    const [run] = await post("/runs", input);
    runs.push(run);
    assert.match(
      (await post("/preview", { ...input, session: "new-york-rth" }, 400))
        .error,
      /requires session/,
    );
    assert.match(
      (await post("/preview", { ...input, delay_bars: 1 }, 400)).error,
      /execution-delay/,
    );
    if (strategy.id === "pine-daily-tsmom") {
      const rejected = await post(
        "/evaluations/preview",
        { base: input, train_days: 7, test_days: 7, folds: 1, delay_bars: 1 },
        400,
      );
      assert.match(rejected.error, /Walk-forward delay stress/);
      const supported = await post("/evaluations/preview", {
        base: input,
        train_days: 7,
        test_days: 7,
        folds: 1,
        delay_bars: 0,
      });
      assert.deepEqual(supported.scenarios, ["Baseline", "Higher costs"]);
      assert.equal(supported.jobs, 3);
    }
  }
  const evidence = [];
  for (const run of runs) {
    let record;
    for (let attempt = 0; attempt < 240; attempt++) {
      record = await (await fetch(`${api}/runs/${run.id}`)).json();
      if (!["Queued", "Running"].includes(record.status)) break;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    assert.equal(record.status, "Succeeded", JSON.stringify(record));
    assert(
      record.result.metrics.trades > 0,
      `${record.input.strategy.id}: test must exercise trades`,
    );
    assert(
      record.result.warnings.some((w) => w.includes("parity is not certified")),
    );
    const exported = await (await fetch(`${api}/runs/${run.id}/export`)).json();
    const names = Object.keys(exported.source_files).map((s) =>
      s.replaceAll("\\", "/"),
    );
    for (const path of record.input.strategy.pine_sources)
      assert(names.includes(path), `Pine snapshot missing: ${path}`);
    evidence.push({
      id: run.id,
      strategy: record.input.strategy.id,
      trades: record.result.metrics.trades,
      net_pnl: record.result.metrics.net_pnl,
    });
  }
  await page.reload();
  await page
    .getByRole("row")
    .filter({ hasText: "Pine · TSMOM intraday ORB" })
    .first()
    .getByRole("button", { name: "Inspect", exact: true })
    .click();
  await page.getByText("trades.csv", { exact: true }).waitFor();
  await page.screenshot({
    path: `${output}/pine-orb-result.png`,
    animations: "disabled",
  });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Scripts", exact: true }).click();
  await page.getByLabel("Search strategy library").fill(".pine");
  await page
    .getByRole("heading", { name: "Consolidated strategy library" })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: `${output}/pine-audit.png`,
    animations: "disabled",
  });
  assert.deepEqual(errors, []);
  checks.push(
    "All four ports traded real ZIP data; Pine snapshots exported; invalid sessions/delay/evaluation are rejected before launch",
  );
  await writeFile(
    `${output}/pine-validation.json`,
    JSON.stringify({ checks, runs: evidence, errors }, null, 2),
  );
  console.log(JSON.stringify({ checks, runs: evidence, errors }, null, 2));
} catch (error) {
  await page.screenshot({
    path: `${output}/pine-failure.png`,
    animations: "disabled",
  });
  throw error;
} finally {
  await browser.close();
}
