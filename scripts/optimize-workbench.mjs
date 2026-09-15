// Runs a predeclared, chronological research campaign through the application.
// Resumable: campaign.json records each submitted group and frozen selection.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";

const origin = "http://127.0.0.1:5173",
  api = origin + "/api/workbench";
const folder = "reports/strategy-optimization-2022-2024",
  file = `${folder}/campaign.json`;
await mkdir(folder, { recursive: true });
let campaign = existsSync(file)
  ? JSON.parse(await readFile(file, "utf8"))
  : {
      id: "optimization-2022-2024-v1",
      created_at: new Date().toISOString(),
      groups: {},
      selections: {},
      validation: {},
      holdout: {},
      stress: {},
      transfer: {},
    };
const save = () => writeFile(file, JSON.stringify(campaign, null, 2));
const strategies = [
  { id: "buy-hold", tf: "1h", warmup: 60, sweep: {}, min: 1 },
  {
    id: "moving-average",
    tf: "1h",
    warmup: 60,
    sweep: { lookback: [10, 20, 40, 80] },
    min: 20,
  },
  {
    id: "multi-speed-momentum",
    tf: "1h",
    warmup: 60,
    sweep: { lookback: [10, 20, 40, 60] },
    min: 20,
  },
  {
    id: "rsi2-reversion",
    tf: "1d",
    warmup: 400,
    sweep: { trend_lookback: [100, 200], entry_rsi: [5, 10] },
    min: 10,
  },
  {
    id: "vwap-reversion",
    tf: "5m",
    session: "new-york-rth",
    warmup: 10,
    sweep: { band: [0.001, 0.002, 0.004] },
    min: 20,
  },
  {
    id: "pine-overnight-block",
    tf: "5m",
    warmup: 10,
    sweep: { entry_hour: [17, 23], exit_hour: [4, 6] },
    min: 20,
  },
  {
    id: "pine-daily-tsmom",
    tf: "15m",
    warmup: 600,
    params: { sizing_mode: "Fixed contracts" },
    sweep: { fast_length: [10, 20], slow_length: [90, 120] },
    min: 5,
  },
  {
    id: "pine-overnight-drift",
    tf: "5m",
    warmup: 180,
    params: { sizing_mode: "Fixed contracts" },
    sweep: {
      close_rule: [
        "Long after up close",
        "Long after down close",
        "Long up / short down",
        "Strong close only (long)",
        "Always (no filter)",
      ],
    },
    min: 20,
  },
  {
    id: "pine-tsmom-orb",
    tf: "5m",
    warmup: 600,
    params: { risk_budget: 2500, maximum_contracts: 1 },
    sweep: { minimum_score: [0.25, 0.5], reward_risk: [1.5, 2] },
    min: 20,
  },
];
const plan = {
  strategies,
  development: "2022-01-01 to 2022-12-31",
  validation: "2023-01-01 to 2023-12-31",
  holdout: "2024-01-01 to 2024-12-31",
  selection:
    "Highest daily Sharpe among positive-net-PnL, finite-Sharpe candidates with sufficient trades and drawdown no worse than 35%. If none qualify, keep the highest finite-Sharpe candidate as a diagnostic only. No selection or retuning uses 2023/2024 results.",
  costs: { capital: 100000, fee_per_side: 1.25, slippage_ticks_per_side: 1 },
  exposure:
    "One contract. Pine daily and drift use fixed-contract mode; ORB maximum one contract with a $2500 stop-risk cap. No position-size optimization.",
  warmup_days: "Fixed per strategy in the declared grid",
  stress: "Double commission and slippage on frozen 2024 NQ settings",
  transfer:
    "Frozen settings on ES in 2024; ES uses its actual point/tick values",
  acceptance:
    "Positive net PnL in 2023 and 2024, 2024 drawdown <=35%, sufficient trades in both periods, positive stressed 2024 NQ PnL. ES reported separately, never used to retune.",
  caveat:
    "Chronological historical checks, not certified untouched out-of-sample evidence: earlier repository research may have inspected these periods.",
};
if (campaign.plan)
  assert.deepEqual(
    campaign.plan,
    plan,
    "Do not change the plan of an existing campaign",
  );
else {
  campaign.plan = plan;
  await save();
}
await writeFile(`${folder}/PLAN.json`, JSON.stringify(plan, null, 2));
async function get(route) {
  const r = await fetch(api + route);
  const b = await r.json();
  assert(r.ok, JSON.stringify(b));
  return b;
}
async function post(route, body) {
  const r = await fetch(api + route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const b = await r.json();
  assert(r.ok, JSON.stringify(b));
  return b;
}
const state = await get("/state");
// A session or host interruption may stop a worker after its group was saved.
// Retry only interrupted attempts, retaining their IDs and the original source.
for (const stage of ["groups", "validation", "holdout", "stress", "transfer"]) {
  for (const [strategy, value] of Object.entries(campaign[stage])) {
    const ids = Array.isArray(value) ? [...value] : [value];
    for (let i = 0; i < ids.length; i++) {
      const run = state.runs.find((r) => r.id === ids[i]);
      assert(run, `Missing saved campaign run ${ids[i]}`);
      if (run.status !== "Interrupted") continue;
      const retried = await post(`/runs/${run.id}/retry`, {});
      (campaign.retries ||= []).push({
        stage,
        strategy,
        original: run.id,
        retry: retried.id,
        reason: run.error,
      });
      ids[i] = retried.id;
      campaign[stage][strategy] = Array.isArray(value) ? ids : ids[0];
      await save();
      console.log(
        `Retried interrupted ${strategy}: ${run.id} -> ${retried.id}`,
      );
    }
  }
}
assert.equal(
  state.strategies.length,
  9,
  "Review new/removed strategies before changing campaign scope",
);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 1080 } });
page.setDefaultTimeout(60000);
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
async function submit(config, parameters, stage, sweep = {}) {
  const spec = state.strategies.find((s) => s.id === config.id),
    symbol = stage === "transfer" ? "ES" : "NQ";
  const year = stage === "groups" ? 2022 : stage === "validation" ? 2023 : 2024;
  const input = {
    strategy_id: spec.id,
    dataset_id: state.datasets.find((d) => d.symbol === symbol).id,
    timeframe: config.tf,
    session: config.session || "full-trading-day",
    start: `${year}-01-01`,
    end: `${year}-12-31`,
    parameters: {
      ...Object.fromEntries(
        Object.entries(spec.parameters).map(([k, v]) => [k, v.default]),
      ),
      ...config.params,
      ...parameters,
    },
    capital: 100000,
    fee: stage === "stress" ? 2.5 : 1.25,
    slippage: stage === "stress" ? 2 : 1,
    warmup_days: config.warmup,
    timeout: 600,
    stage: stage === "groups" ? "Exploratory" : "Evaluation",
    development_end: stage === "groups" ? "" : "2022-12-31",
    criteria:
      stage === "groups"
        ? ""
        : "Frozen 2022 selection; positive net PnL, drawdown <=35%, sufficient trades. No retuning after 2023/2024.",
    hypothesis: `${campaign.id} | ${stage} | ${spec.id} | ${symbol}`,
    sweep,
  };
  // Each development grid is configured, previewed and launched through the UI.
  // Later frozen runs use the same application API and saved selected parameters.
  if (stage !== "groups") return post("/runs", input);
  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Scripts", exact: true }).click();
  await page
    .getByRole("heading", { name: spec.name, exact: true })
    .locator("..")
    .locator("..")
    .getByRole("button", { name: "Configure run", exact: true })
    .click();
  for (const [label, value] of [
    ["Dataset version", /^NQ ·/],
    ["Timeframe", config.tf],
    [
      "Session",
      input.session === "full-trading-day" ? "Full Globex day" : "New York RTH",
    ],
  ]) {
    await page.getByRole("textbox", { name: label, exact: true }).click();
    await page
      .getByRole("option", { name: value, exact: typeof value === "string" })
      .first()
      .click();
  }
  await page.getByLabel("Start date (UTC)", { exact: true }).fill(input.start);
  await page
    .getByLabel("End date (UTC, inclusive)", { exact: true })
    .fill(input.end);
  // Parameter overrides are included as singleton sweep dimensions, preserving
  // every UI-visible default and the exact submitted experiment configuration.
  const grid = {
    ...Object.fromEntries(
      Object.entries(config.params || {}).map(([k, v]) => [k, [v]]),
    ),
    ...sweep,
  };
  await page
    .getByLabel("Parameter sweep (JSON)", { exact: true })
    .fill(JSON.stringify(grid));
  await page
    .getByLabel("Warmup calendar days", { exact: true })
    .fill(String(config.warmup));
  await page
    .getByLabel("Question / hypothesis", { exact: true })
    .fill(input.hypothesis);
  // Use the actual form labels defined by Workbench; keep accounting explicit.
  for (const [label, value] of [
    ["Initial capital (USD)", "100000"],
    ["Fee / contract / side (USD)", "1.25"],
    ["Slippage / side (ticks)", "1"],
    ["Timeout (seconds)", "600"],
  ]) {
    const field = page.getByLabel(label, { exact: true });
    await field.fill(value);
  }
  await page
    .getByRole("button", { name: "Validate & preview", exact: true })
    .click();
  const count = Object.values(grid).reduce((n, v) => n * v.length, 1);
  await page
    .getByText(`${count} job${count === 1 ? "" : "s"} ready`, { exact: true })
    .waitFor();
  const promise = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/workbench/runs") &&
      r.request().method() === "POST",
    { timeout: 120000 },
  );
  await page
    .getByRole("button", {
      name: `Launch ${count} run${count === 1 ? "" : "s"}`,
      exact: true,
    })
    .click();
  const response = await promise,
    result = await response.json();
  assert.equal(response.status(), 201, JSON.stringify(result));
  await page
    .getByRole("heading", { name: "Run ledger", exact: true })
    .waitFor();
  assert(
    result.every(
      (r) =>
        r.input.capital === 100000 &&
        r.input.fee === 1.25 &&
        r.input.slippage === 1,
    ),
    "Unexpected UI accounting defaults",
  );
  return result;
}
async function wait(ids, label) {
  for (;;) {
    const current = await get("/state"),
      records = ids.map((id) => current.runs.find((r) => r.id === id));
    assert(records.every(Boolean), "Campaign run was deleted");
    const pending = records.filter((r) =>
      ["Queued", "Running"].includes(r.status),
    );
    console.log(
      `${label}: ${records.length - pending.length}/${records.length} finished`,
    );
    if (!pending.length) return records;
    await new Promise((resolve) => setTimeout(resolve, 15000));
  }
}
try {
  await page.goto(origin, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page
    .getByRole("heading", { name: "Run ledger", exact: true })
    .waitFor();
  for (const config of strategies) {
    if (!campaign.groups[config.id]) {
      const runs = await submit(config, {}, "groups", config.sweep);
      campaign.groups[config.id] = runs.map((r) => r.id);
      await save();
      console.log(
        `Submitted ${config.id}: ${runs.length} development candidates`,
      );
    }
  }
  const training = await wait(
    Object.values(campaign.groups).flat(),
    "Development",
  );
  for (const config of strategies) {
    if (campaign.selections[config.id]) continue;
    const candidates = training.filter((r) =>
      campaign.groups[config.id].includes(r.id),
    );
    assert(
      candidates.every((r) => r.status === "Succeeded"),
      `Resolve failed grid before selecting ${config.id}: ${JSON.stringify(candidates.filter((r) => r.status !== "Succeeded"))}`,
    );
    const finite = candidates
      .filter((r) => Number.isFinite(r.result.metrics.sharpe))
      .sort(
        (a, b) =>
          b.result.metrics.sharpe - a.result.metrics.sharpe ||
          a.id.localeCompare(b.id),
      );
    const eligible = finite.filter(
      (r) =>
        r.result.metrics.net_pnl > 0 &&
        r.result.metrics.max_drawdown >= -0.35 &&
        r.result.metrics.trades >= config.min,
    );
    const chosen = eligible[0] || finite[0] || candidates[0];
    campaign.selections[config.id] = {
      run_id: chosen.id,
      parameters: chosen.input.parameters,
      eligible: eligible.length > 0,
      selected_at: new Date().toISOString(),
      source_hash: chosen.input.source_hash,
      metrics: chosen.result.metrics,
      ranking: finite.map((r) => ({
        id: r.id,
        parameters: r.input.parameters,
        sharpe: r.result.metrics.sharpe,
        net_pnl: r.result.metrics.net_pnl,
        drawdown: r.result.metrics.max_drawdown,
        trades: r.result.metrics.trades,
      })),
      note: eligible.length
        ? "Training criteria met"
        : "Diagnostic selection only: no candidate met all training criteria",
    };
    await save();
  }
  await writeFile(
    `${folder}/FROZEN_SELECTIONS.json`,
    JSON.stringify(campaign.selections, null, 2),
  );
  for (const stage of ["validation", "holdout", "stress", "transfer"]) {
    for (const config of strategies) {
      if (campaign[stage][config.id]) continue;
      const selected = campaign.selections[config.id];
      const [run] = await submit(config, selected.parameters, stage);
      assert.equal(
        run.input.source_hash,
        selected.source_hash,
        "Source changed after selection; do not mix code versions",
      );
      campaign[stage][config.id] = run.id;
      await save();
    }
    await wait(Object.values(campaign[stage]), stage);
  }
  const final = await get("/state");
  const summary = [];
  for (const config of strategies) {
    const chosen = campaign.selections[config.id];
    const series = Object.fromEntries(
      ["validation", "holdout", "stress", "transfer"].map((stage) => [
        stage,
        final.runs.find((r) => r.id === campaign[stage][config.id]),
      ]),
    );
    assert(
      Object.values(series).every((r) => r.status === "Succeeded"),
      "A frozen check failed",
    );
    const checks = {
      "2022 training eligibility": chosen.eligible,
      "Positive 2023 net P&L": series.validation.result.metrics.net_pnl > 0,
      "Positive 2024 net P&L": series.holdout.result.metrics.net_pnl > 0,
      "2024 drawdown within 35%":
        series.holdout.result.metrics.max_drawdown >= -0.35,
      "Sufficient 2023 trades":
        series.validation.result.metrics.trades >= config.min,
      "Sufficient 2024 trades":
        series.holdout.result.metrics.trades >= config.min,
      "Positive higher-cost 2024 P&L": series.stress.result.metrics.net_pnl > 0,
    };
    const pass = Object.values(checks).every(Boolean);
    summary.push({
      strategy: config.id,
      parameters: chosen.parameters,
      training_eligible: chosen.eligible,
      checks,
      failed_checks: Object.keys(checks).filter((key) => !checks[key]),
      outcome: pass
        ? "Passed declared historical checks"
        : "Did not pass declared checks",
      training: chosen.metrics,
      ...Object.fromEntries(
        Object.entries(series).map(([k, r]) => [
          k,
          { run_id: r.id, ...r.result.metrics },
        ]),
      ),
    });
    const annotation = await fetch(`${api}/runs/${series.holdout.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tags: `${campaign.id}, ${pass ? "historical-checks-passed" : "checks-failed"}`,
        notes: `Frozen parameters selected on 2022 only. ${chosen.note}. ${pass ? "Passed" : "Did not pass"} declared 2023/2024 criteria; historical research only. See reports/strategy-optimization-2022-2024/RESULTS.md.`,
      }),
    });
    assert(annotation.ok, `Failed to annotate ${series.holdout.id}`);
    // Store every selected configuration as a preset, including unsuccessful
    // diagnostics, with an explicit outcome in its name.
    if (!campaign.presets) campaign.presets = {};
    if (!campaign.presets[config.id]) {
      const r = series.holdout,
        input = {
          strategy_id: config.id,
          dataset_id: r.input.dataset.id,
          start: r.input.start,
          end: r.input.end,
          timeframe: r.input.timeframe,
          session: r.input.session,
          parameters: r.input.parameters,
          capital: r.input.capital,
          fee: r.input.fee,
          slippage: r.input.slippage,
          warmup_days: r.input.warmup_days,
          timeout: r.input.timeout,
          stage: "Exploratory",
          hypothesis:
            "Frozen 2022 selection; historical checks already inspected",
          sweep: {},
        };
      const preset = await post("/presets", {
        name: `2022 selected · ${config.id} · ${pass ? "passed checks" : "diagnostic"}`,
        input,
      });
      campaign.presets[config.id] = preset.id;
      await save();
    }
  }
  campaign.summary = summary;
  campaign.completed_at = new Date().toISOString();
  await save();
  const pct = (v) => (100 * v).toFixed(1) + "%",
    dollars = (v) =>
      v.toLocaleString("en-US", { style: "currency", currency: "USD" });
  const lines = [
    "# Strategy optimization results",
    "",
    "## Scope",
    "",
    "All nine enabled strategies; 33 development candidates (including the passive benchmark), selected using 2022 only. Settings frozen before 2023 validation and 2024 holdout/cost/ES checks. No automatic walk-forward engine was used for Pine event ports.",
    "",
    plan.exposure,
    "",
    "Each run starts with $100,000. Base costs are $1.25 per contract per side plus one tick of slippage per side; stress uses $2.50 and two ticks. No margin liquidation is simulated: negative-equity paths are unusable and fail training eligibility.",
    "",
    plan.caveat,
    "",
    "## Results",
    "",
    "| Strategy | 2022 P&L | 2023 P&L | 2024 P&L | 2024 drawdown | Higher-cost 2024 P&L | ES 2024 P&L | Outcome |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ...summary.map(
      (r) =>
        `| ${r.strategy} | ${dollars(r.training.net_pnl)} | ${dollars(r.validation.net_pnl)} | ${dollars(r.holdout.net_pnl)} | ${pct(r.holdout.max_drawdown)} | ${dollars(r.stress.net_pnl)} | ${dollars(r.transfer.net_pnl)} | ${r.outcome} |`,
    ),
    "",
    "## Acceptance checks",
    "",
    `${summary.filter((r) => r.training_eligible && r.failed_checks.length === 0).length} of nine selected configurations passed every declared historical check. ES transfer is reported separately and did not influence selection.`,
    "",
    "| Strategy | Failed criteria |",
    "| --- | --- |",
    ...summary.map(
      (r) => `| ${r.strategy} | ${r.failed_checks.join("; ") || "None"} |`,
    ),
    "",
    "See PLAN.json for the predeclared grids, minimum trade counts and selection rule. A profitable later period does not override failed training eligibility.",
    "",
    "## Selected parameters",
    "",
    ...summary.flatMap((r) => [
      `### ${r.strategy}`,
      "",
      "```json",
      JSON.stringify(r.parameters, null, 2),
      "```",
      "",
      `Training eligibility: ${r.training_eligible}. Holdout run: ${r.holdout.run_id}.`,
      "",
    ]),
    "## Interpretation",
    "",
    "These are the best measured candidates within a small declared grid, not global optima or live-trading approval. Preserve losing trials. Results use unadjusted continuous futures; roll gaps, missing-session classification, execution assumptions and prior research exposure limit inference. ES transfer has different contract economics and is not a risk-normalized comparison.",
    "",
    `Completed ${campaign.completed_at}. All ${training.length + 36} completed campaign runs and nine presets remain in the app, plus ${(campaign.retries || []).length} interrupted attempts retained for audit. See campaign.json and FROZEN_SELECTIONS.json for exact IDs and inputs.`,
    "",
  ];
  await writeFile(`${folder}/RESULTS.md`, lines.join("\n"));
  await page.reload();
  await page
    .getByRole("heading", { name: "Run ledger", exact: true })
    .waitFor();
  await page.screenshot({
    path: `${folder}/run-ledger.png`,
    animations: "disabled",
  });
  const first = page
    .getByRole("button", { name: "Inspect", exact: true })
    .first();
  await first.click();
  await page.getByText("equity.csv", { exact: true }).waitFor();
  await page.screenshot({
    path: `${folder}/run-detail.png`,
    animations: "disabled",
  });
  await writeFile(`${folder}/browser-errors.json`, JSON.stringify(errors));
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify(
      summary.map((r) => ({
        strategy: r.strategy,
        outcome: r.outcome,
        holdout_pnl: r.holdout.net_pnl,
      })),
      null,
      2,
    ),
  );
} catch (error) {
  await page.screenshot({ path: `${folder}/failure.png`, fullPage: true });
  await writeFile(
    `${folder}/failure.txt`,
    await page.locator("body").innerText(),
  );
  throw error;
} finally {
  await browser.close();
}
