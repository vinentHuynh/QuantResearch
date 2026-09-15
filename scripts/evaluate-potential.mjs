import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";

const origin = "http://127.0.0.1:5173",
  api = `http://127.0.0.1:8001/api/workbench`;
const folder = "reports/strategy-potential-2025",
  ledger = `${folder}/campaign.json`;
await mkdir(folder, { recursive: true });
const previous = JSON.parse(
  await readFile(
    "reports/strategy-optimization-2022-2024/campaign.json",
    "utf8",
  ),
);
const campaign = existsSync(ledger)
  ? JSON.parse(await readFile(ledger, "utf8"))
  : {
      id: "potential-2025-v1",
      created_at: new Date().toISOString(),
      evaluations: {},
      regimes: {},
    };
const plan = {
  calibration: "2024-01-01 to 2024-12-31",
  test: "2025-01-01 to 2025-12-31",
  parameters:
    "Frozen 2022 selections; one candidate per strategy, no retuning or exclusion based on 2024 profitability.",
  sizing:
    "Same one-contract settings, $100000 starting capital, $1.25 fee and one tick per side. ORB stop-risk cap $2500.",
  protocol:
    "One chronological fold: 366 training days, 365 test days. Training eligibility: finite net P&L, zero minimum trades so every fixed configuration is evaluated. Test: nonnegative net return, drawdown <=35%, original strategy-specific minimum trade count.",
  scenarios:
    "Baseline and doubled costs for all nine; one additional chart-bar delay for five signal strategies. Event-order delay unavailable.",
  regimes: {
    features: ["volatility", "trend"],
    lookback_bars: 20,
    training_quantile: 0.5,
    seed: 42,
  },
  interpretation:
    "Descriptive historical potential at tested sizing. Later history, not certified untouched data. Regime attribution does not simulate trading only in a selected state.",
};
if (campaign.plan) assert.deepEqual(campaign.plan, plan);
else campaign.plan = plan;
const save = () => writeFile(ledger, JSON.stringify(campaign, null, 2));
await save();
await writeFile(`${folder}/PLAN.json`, JSON.stringify(plan, null, 2));
async function get(path) {
  const r = await fetch(api + path),
    b = await r.json();
  assert(r.ok, JSON.stringify(b));
  return b;
}
async function post(path, body) {
  const r = await fetch(api + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
    b = await r.json();
  assert(r.ok, JSON.stringify(b));
  return b;
}
const initial = await get("/state");
const browser = await chromium.launch(),
  page = await browser.newPage({
    baseURL: origin,
    viewport: { width: 1500, height: 1080 },
  });
page.setDefaultTimeout(60000);
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  for (const config of previous.plan.strategies) {
    if (campaign.evaluations[config.id]) continue;
    const name = `${campaign.id} | ${config.id}`;
    const existing = (await get("/state")).evaluations.filter(
      (e) => e.name === name,
    );
    assert(existing.length <= 1, "Duplicate evaluations require review");
    if (existing.length) {
      campaign.evaluations[config.id] = existing[0].id;
      await save();
      continue;
    }
    const seed = initial.runs.find((r) => r.id === previous.holdout[config.id]);
    assert.equal(seed.status, "Succeeded");
    const event = seed.input.strategy.execution_model === "event-v1";
    await page.goto(origin);
    await page
      .getByRole("button", { name: "Evaluation & Regimes", exact: true })
      .click();
    await page
      .getByRole("textbox", { name: "Starting run", exact: true })
      .fill(seed.id.slice(0, 8));
    await page
      .getByRole("option", { name: new RegExp(seed.id.slice(0, 8)) })
      .click();
    const fields = {
      "Evaluation name": name,
      "Research interval starts (UTC)": "2024-01-01",
      "Research interval ends (UTC)": "2025-12-31",
      "Training calendar days": "366",
      "Test calendar days": "365",
      "Number of folds": "1",
      "Minimum training trades": "0",
      "Minimum combined test trades": String(config.min),
      "Minimum test return (%)": "0",
      "Maximum test drawdown (%)": "35",
      "Stress cost multiplier": "2",
      "Candidate parameter grid (JSON)": "{}",
      "Evaluation hypothesis": `Fixed selected parameters from run ${seed.id}. Evaluate 2025; calibrate states on 2024. No retuning. ${plan.interpretation}`,
    };
    for (const [label, value] of Object.entries(fields))
      await page.getByLabel(label, { exact: true }).fill(value);
    if (event)
      assert(
        await page
          .getByLabel("Additional execution delay (bars)", { exact: true })
          .isDisabled(),
      );
    else
      await page
        .getByLabel("Additional execution delay (bars)", { exact: true })
        .fill("1");
    const pending = page.waitForResponse(
      (r) =>
        r.url().endsWith("/evaluations/preview") &&
        r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Preview evaluation", exact: true })
      .click();
    const preview = await (await pending).json();
    assert.equal(preview.jobs, event ? 3 : 4, JSON.stringify(preview));
    assert.equal(preview.folds[0].train_end, "2024-12-31");
    assert.equal(preview.folds[0].test_start, "2025-01-01");
    assert.equal(preview.folds[0].test_end, "2025-12-31");
    assert.deepEqual(
      preview.candidates[0].parameters,
      previous.selections[config.id].parameters,
    );
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/workbench/evaluations") &&
        r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Launch walk-forward", exact: true })
      .click();
    const launched = await response,
      record = await launched.json();
    assert.equal(launched.status(), 201, JSON.stringify(record));
    campaign.evaluations[config.id] = record.id;
    await save();
    console.log(`Launched ${config.id}: ${preview.jobs} jobs`);
  }
  for (;;) {
    const state = await get("/state"),
      evaluations = Object.values(campaign.evaluations).map((id) =>
        state.evaluations.find((e) => e.id === id),
      );
    assert(evaluations.every(Boolean));
    assert(
      evaluations.every(
        (e) => !["Failed", "Canceled", "Interrupted"].includes(e.status),
      ),
      JSON.stringify(
        evaluations.filter((e) =>
          ["Failed", "Canceled", "Interrupted"].includes(e.status),
        ),
      ),
    );
    console.log(
      `Evaluations: ${evaluations.filter((e) => e.status === "Succeeded").length}/9 complete`,
    );
    if (evaluations.every((e) => e.status === "Succeeded")) {
      assert(evaluations.every((e) => e.result));
      break;
    }
    await new Promise((r) => setTimeout(r, 15000));
  }
  for (const [strategy, id] of Object.entries(campaign.evaluations)) {
    campaign.regimes[strategy] ||= {};
    for (const feature of plan.regimes.features) {
      if (campaign.regimes[strategy][feature]) continue;
      const existing = (await get("/state")).regimes.filter(
        (r) =>
          r.evaluation_id === id &&
          r.feature === feature &&
          r.window === 20 &&
          r.quantile === 0.5 &&
          r.seed === 42,
      );
      assert(existing.length <= 1);
      const task =
        existing[0] ||
        (await post(`/evaluations/${id}/regimes`, {
          feature,
          window: 20,
          quantile: 0.5,
          seed: 42,
        }));
      campaign.regimes[strategy][feature] = task.id;
      await save();
    }
  }
  for (;;) {
    const state = await get("/state"),
      studies = Object.values(campaign.regimes)
        .flatMap((v) => Object.values(v))
        .map((id) => state.regimes.find((r) => r.id === id));
    assert(studies.every(Boolean));
    assert(
      studies.every((r) => !["Failed", "Interrupted"].includes(r.status)),
      JSON.stringify(
        studies.filter((r) => ["Failed", "Interrupted"].includes(r.status)),
      ),
    );
    console.log(
      `Regime studies: ${studies.filter((r) => r.status === "Succeeded").length}/18 complete`,
    );
    if (studies.every((r) => r.status === "Succeeded")) break;
    await new Promise((r) => setTimeout(r, 15000));
  }
  const state = await get("/state"),
    summaries = [];
  for (const config of previous.plan.strategies) {
    const e = await get(`/evaluations/${campaign.evaluations[config.id]}`);
    const studies = Object.fromEntries(
      plan.regimes.features.map((f) => [
        f,
        state.regimes.find((r) => r.id === campaign.regimes[config.id][f]),
      ]),
    );
    const scenarios = Object.fromEntries(
        e.result.scenarios.map((s) => [s.name, s]),
      ),
      baseline = scenarios.Baseline;
    for (const study of Object.values(studies)) {
      assert(
        Math.abs(
          study.result.states.reduce((n, s) => n + s.net_pnl, 0) -
            baseline.metrics.net_pnl,
        ) < 0.01,
      );
      assert.equal(
        study.result.states.reduce((n, s) => n + s.entry_count, 0),
        baseline.metrics.trades,
      );
      assert.equal(study.result.thresholds[0].calibrated_through, "2024-12-31");
    }
    for (const run of e.runs)
      assert.deepEqual(
        run.input.parameters,
        previous.selections[config.id].parameters,
      );
    assert(
      e.runs
        .filter((r) => r.input.research.role === "Test")
        .every((r) => r.created_at >= e.folds[0].selection.selected_at),
    );
    const allPass = e.result.scenarios.every(
        (s) => s.outcome === "Meets criteria",
      ),
      priorPass =
        previous.summary.find((r) => r.strategy === config.id).outcome ===
        "Passed declared historical checks";
    const assessment =
      config.id === "buy-hold"
        ? "Passive benchmark; assess drawdown separately"
        : baseline.outcome !== "Meets criteria"
          ? "Did not meet 2025 return/risk/trade criteria"
          : !allPass
            ? "Baseline passes; sensitive to execution stress"
            : priorPass
              ? "Passed prior and 2025 checks; further research candidate"
              : "2025 checks pass; earlier weaknesses remain";
    summaries.push({
      strategy: config.id,
      evaluation_id: e.id,
      scenarios,
      regimes: studies,
      parameters: previous.selections[config.id].parameters,
      prior_pass: priorPass,
      assessment,
    });
    await writeFile(
      `${folder}/${config.id}.json`,
      JSON.stringify({ evaluation: e, studies }, null, 2),
    );
  }
  campaign.summary = summaries;
  campaign.completed_at = new Date().toISOString();
  await save();
  const money = (n) =>
      n.toLocaleString("en-US", { style: "currency", currency: "USD" }),
    pct = (n) => `${(n * 100).toFixed(2)}%`;
  const lines = [
    "# Strategy potential: 2025 evaluations and regimes",
    "",
    "## Protocol",
    "",
    ...Object.entries(plan).map(
      ([k, v]) =>
        `- **${k}:** ${typeof v === "string" ? v : JSON.stringify(v)}`,
    ),
    "",
    "## Every strategy",
    "",
    "| Strategy | 2025 net P&L | Max drawdown | Trades | Doubled-cost P&L | Delayed P&L | Historical assessment |",
    "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ...summaries.map(
      (s) =>
        `| ${s.strategy} | ${money(s.scenarios.Baseline.metrics.net_pnl)} | ${pct(s.scenarios.Baseline.metrics.max_drawdown)} | ${s.scenarios.Baseline.metrics.trades} | ${money(s.scenarios["Higher costs"].metrics.net_pnl)} | ${s.scenarios["Delayed execution"] ? money(s.scenarios["Delayed execution"].metrics.net_pnl) : "Unavailable for event orders"} | ${s.assessment} |`,
    ),
    "",
    "## Regime attribution",
    "",
    "Higher/Lower means above/below the **2024 training median**, not necessarily bull/bear or positive/negative trend. Features use 20 bars of each strategy's native timeframe, lagged one completed bar; horizons differ between strategies. Net P&L comes from the original continuous path, including costs. These are not separate state-only trading backtests. Unequal exposure, time in each state, and dependent episodes limit comparisons.",
    "",
  ];
  for (const s of summaries) {
    lines.push(
      `### ${s.strategy}`,
      "",
      s.assessment + ".",
      "",
      `Evaluation: ${s.evaluation_id}. Parameters: \`${JSON.stringify(s.parameters)}\`.`,
      "",
      "| Feature | State | Bars | Episodes | Net P&L | P&L/bar | Invested bars | Entries | Mean episode P&L (95% bootstrap interval) |",
      "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    );
    for (const [feature, study] of Object.entries(s.regimes))
      for (const r of study.result.states)
        lines.push(
          `| ${feature} | ${r.state} | ${r.observations} | ${r.episodes} | ${money(r.net_pnl)} | ${money(r.net_pnl / r.observations)} | ${pct(r.invested_bar_fraction)} | ${r.entry_count} | ${money(r.mean_episode_pnl)} (${r.mean_episode_pnl_interval_95?.map(money).join(" to ") || "unavailable: sparse"}) |`,
        );
    lines.push("");
  }
  lines.push(
    "## Limits",
    "",
    "These descriptive findings do not establish future returns, a trading switch, or live readiness. The previous campaign already inspected 2022–2024; this evaluation does not erase earlier failures. Unadjusted continuous futures include roll gaps. No margin liquidation is simulated. Event fills use existing one-minute bracket assumptions; event execution-delay sensitivity remains untested. The new snapshot adds evaluation support and event-entry bar metadata without changing strategy rules.",
    "",
    `Completed ${campaign.completed_at}: nine evaluations, 32 child runs, and 18 regime investigations. Every prior run and unsuccessful result remains in the app. Exact IDs, thresholds, scenarios, inputs and warnings are in campaign.json and per-strategy JSON files.`,
    "",
  );
  await writeFile(`${folder}/RESULTS.md`, lines.join("\n"));
  await writeFile(
    `${folder}/launch-browser-errors.json`,
    JSON.stringify(errors),
  );
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify(
      summaries.map((s) => ({
        strategy: s.strategy,
        pnl: s.scenarios.Baseline.metrics.net_pnl,
        assessment: s.assessment,
      })),
      null,
      2,
    ),
  );
} catch (error) {
  console.error(error);
  await writeFile(`${folder}/error.txt`, String(error));
  await page.screenshot({ path: `${folder}/failure.png`, timeout: 10000 }).catch(() => {});
  throw error;
} finally {
  await browser.close();
}
