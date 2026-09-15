import { chromium, expect } from "@playwright/test";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import assert from "node:assert/strict";
const folder = "reports/strategy-potential-2025",
  origin = "http://127.0.0.1:5173",
  api = `${origin}/api/workbench`;
const campaign = JSON.parse(await readFile(`${folder}/campaign.json`, "utf8"));
const prior = JSON.parse(
  await readFile(
    "reports/strategy-optimization-2022-2024/campaign.json",
    "utf8",
  ),
);
assert(campaign.completed_at);
const state = await (await fetch(`${api}/state`)).json();
const browser = await chromium.launch(),
  page = await browser.newPage({
    baseURL: origin,
    viewport: { width: 1500, height: 1080 },
  });
const errors = [],
  checks = [];
page.on("pageerror", (e) => errors.push(e.message));
page.setDefaultTimeout(60000);
try {
  await page.goto(origin);
  await page
    .getByRole("heading", { name: "Run ledger", exact: true })
    .waitFor();
  let navigations = 0;
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) navigations++;
  });
  // A source-snapshot tsconfig must not reload the running application.
  await mkdir("data/workbench/watch-probe", { recursive: true });
  await writeFile(
    "data/workbench/watch-probe/tsconfig.json",
    JSON.stringify({
      compilerOptions: { strict: true },
      checked_at: new Date().toISOString(),
    }),
  );
  await page.waitForTimeout(2500);
  assert.equal(navigations, 0, "Snapshot triggered frontend reload");
  checks.push("Snapshot tsconfig creation does not reload the application");
  for (const summary of campaign.summary) {
    const e = JSON.parse(
      await readFile(`${folder}/${summary.strategy}.json`, "utf8"),
    ).evaluation;
    const original = state.runs.find(
      (r) => r.id === prior.holdout[summary.strategy],
    );
    const training = e.runs.find((r) => r.input.research.role === "Training");
    for (const key of ["net_pnl", "max_drawdown", "trades", "costs"])
      assert.equal(
        training.result.metrics[key],
        original.result.metrics[key],
        `${summary.strategy}: 2024 economics changed`,
      );
    const expected =
      original.input.strategy.execution_model === "event-v1" ? 2 : 3;
    assert.equal(e.result.scenarios.length, expected);
    assert.equal(e.runs.length, expected + 1);
    assert(
      e.runs.every(
        (r) =>
          r.status === "Succeeded" && r.input.source_hash === e.source_hash,
      ),
    );
    const base = e.result.scenarios[0].metrics,
      stress = e.result.scenarios[1].metrics;
    assert(Math.abs(stress.net_pnl - (base.net_pnl - base.costs)) < 0.01);
    await page.goto(origin);
    await page
      .getByRole("button", { name: "Evaluation & Regimes", exact: true })
      .click();
    await page
      .getByRole("row")
      .filter({ has: page.getByText(e.name, { exact: true }) })
      .getByRole("button", { name: "Open evaluation", exact: true })
      .click();
    await page.getByRole("heading", { name: e.name, exact: true }).waitFor();
    const chart = page.getByRole("img", {
      name: "Walk-forward test equity",
      exact: true,
    });
    await expect(chart).toBeVisible();
    await chart.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: `${folder}/${summary.strategy}-evaluation.png`,
      animations: "disabled",
    });
    assert.equal(
      await page
        .getByText("Historical conditional attribution", { exact: true })
        .count(),
      2,
    );
    for (const [feature, task] of Object.entries(summary.regimes)) {
      const href = `/api/workbench/research-artifact?kind=regimes&id=${task.id}&name=observations.csv`;
      const link = page.locator(`a[href="${href}"]`);
      await expect(link).toHaveCount(1);
      const response = await page.request.get(href);
      assert(response.ok());
      assert((await response.text()).includes("entry_count"));
      const total = task.result.states.reduce((sum, r) => sum + r.net_pnl, 0);
      assert(Math.abs(total - base.net_pnl) < 0.01);
      assert.equal(
        task.result.states.reduce((sum, r) => sum + r.entry_count, 0),
        base.trades,
      );
      assert(
        task.result.thresholds.every(
          (t) => t.calibrated_through === "2024-12-31",
        ),
      );
      if (feature === "volatility") {
        await link.scrollIntoViewIfNeeded();
        await page.screenshot({
          path: `${folder}/${summary.strategy}-regimes.png`,
          animations: "disabled",
        });
      }
    }
    const result = await page.request.get(
      `/api/workbench/research-artifact?kind=evaluations&id=${e.id}&name=result.json`,
    );
    assert(result.ok());
    assert.equal((await result.json()).outcome, e.outcome);
    checks.push(
      `${summary.strategy}: unchanged 2024 economics, declared scenarios, frozen source, cost reconciliation, charts, two regime tables, downloads, entry/P&L reconciliation and threshold dates`,
    );
    console.log(`Validated ${summary.strategy}`);
  }
  assert.deepEqual(errors, []);
  const rows = [["strategy", "net_pnl_2025", "max_drawdown", "trades", "higher_cost_pnl", "delayed_pnl", "lower_volatility_pnl", "higher_volatility_pnl", "lower_trend_pnl", "higher_trend_pnl", "assessment"]];
  for (const s of campaign.summary) {
    const statePnl = (feature, name) => s.regimes[feature].result.states.find(r => r.state === name)?.net_pnl ?? "";
    rows.push([s.strategy, s.scenarios.Baseline.metrics.net_pnl, s.scenarios.Baseline.metrics.max_drawdown, s.scenarios.Baseline.metrics.trades, s.scenarios["Higher costs"].metrics.net_pnl, s.scenarios["Delayed execution"]?.metrics.net_pnl ?? "Unavailable", statePnl("volatility", "Lower"), statePnl("volatility", "Higher"), statePnl("trend", "Lower"), statePnl("trend", "Higher"), s.assessment]);
  }
  await writeFile(`${folder}/summary.csv`, rows.map(row => row.map(value => '"' + String(value).replaceAll('"', '""') + '"').join(',')).join('\n'));
  const after = await (await fetch(`${api}/state`)).json();
  assert.equal(after.runs.length, state.runs.length);
  await writeFile(
    `${folder}/browser-validation.json`,
    JSON.stringify(
      {
        checked_at: new Date().toISOString(),
        checks,
        errors,
        evaluations: 9,
        regimes: 18,
        child_runs: 32,
      },
      null,
      2,
    ),
  );
} catch (error) {
  await page.screenshot({
    path: `${folder}/validation-failure.png`,
    fullPage: true,
  });
  await writeFile(
    `${folder}/validation-failure.txt`,
    await page.locator("body").innerText(),
  );
  throw error;
} finally {
  await browser.close();
}
