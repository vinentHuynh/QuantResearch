import assert from "node:assert/strict";
import { resolve } from "node:path";
import { chromium, expect } from "@playwright/test";
import { initialNewRunInput } from "../../src/features/new-run/model.ts";

// Intercept all HTTP traffic so these tests can never launch a real research job.
const base = "https://workbench.test";
const strategy = { id: "sample", name: "Sample strategy", description: "", file_hash: "fixture", timeframes: ["1h"], parameters: {} };
const dataset = { id: "sample-data", symbol: "MNQ", first: "2026-01-05", last: "2026-01-09", rows: 100, tick_size: .25, point_value: 2 };
const input = { ...initialNewRunInput, strategy_id: strategy.id, dataset_id: dataset.id, start: dataset.first, end: dataset.last };
const metrics = { trades: 12, net_pnl: 150, net_return: .015, max_drawdown: -.01, monthly: [] };
const run = { id: "failed-check", created_at: dataset.last, status: "Succeeded", tags: "checks-failed", notes: "Minimum trades missed.",
  input: { ...input, strategy, dataset }, result: { metrics, warnings: [], artifacts: [] } };
const state = { strategies: [strategy], datasets: [dataset], presets: [{ id: "preset", name: "MNQ baseline", input }],
  runs: [run], errors: [], experiments: [], views: [], watchlist: [], evaluations: [], limits: { concurrency: 1, maxBatch: 24 } };
const item = { id: "book", key: "sample__MNQ", name: "Sample strategy", symbol: "MNQ", timeframe: "1h", session: input.session,
  start: input.start, end: input.end, capital: 100000, working: true, feasible: true, tested: true, reasons: [], parameters: {},
  net_pnl: 20, recent_pnl: 20, trades: 2, coverage: [{ start: input.start, end: input.end }] };
let catalogItems = [item];
let trackedIds = [item.id];
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  const launches = [];
  const previews = [];
  page.on("pageerror", error => { errors.push(error.message); console.error(error.message); });
  await page.route("**/*", async route => {
    const url = new URL(route.request().url());
    assert.equal(url.origin, base);
    const path = url.pathname;
    if (!path.startsWith("/api/")) return route.fulfill({ path: resolve("dist", "." + (path === "/" ? "/index.html" : path)) });
    if (path.endsWith("/state")) return route.fulfill({ json: state });
    if (path.endsWith("/preview")) {
      const body = route.request().postDataJSON();
      previews.push(body);
      if (body.end < body.start) return route.fulfill({ status: 400, json: { error: "End precedes start" } });
      return route.fulfill({ json: { jobs: Object.values(body.sweep)[0]?.length || 1, warmup: [] } });
    }
    if (path.endsWith("/runs")) {
      launches.push(route.request().postDataJSON());
      return route.fulfill({ json: [{ id: "new" }] });
    }
    if (path.endsWith("/collective")) return route.fulfill({ json: { items: catalogItems, generated_at: dataset.last, errors: [], definitions: {}, market_data_through: {} } });
    if (path.endsWith("/series")) {
      const { ids } = route.request().postDataJSON();
      return route.fulfill({ json: catalogItems.filter(book => ids.includes(book.id)).map(book => ({
        id: book.id, coverage: book.coverage, trades: [], daily: [{ date: input.start, pnl: book.net_pnl }],
      })) });
    }
    if (path.includes("/tracking")) {
      if (route.request().method() === "PUT") trackedIds = route.request().postDataJSON().ids;
      return route.fulfill({ json: { selection: trackedIds, items: {} } });
    }
    return route.fulfill({ json: {} });
  });
  await page.goto(base + "/#/scripts");
  const card = page.locator(".scripts-strategy-card").first();
  await expect(card.getByLabel("Best run summary")).toBeHidden();
  await card.getByRole("button", { name: "Review failed checks" }).click();
  await expect(card.getByText(/Recorded checks failed:/)).toBeVisible();
  await card.getByText(/Results and research history/).click();
  await expect(card.getByLabel("Best run summary")).toContainText("$150");
  await card.getByRole("button", { name: /More actions/ }).click();
  await expect(page.getByRole("menuitem", { name: "Archive script" })).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("link", { name: "New backtest", exact: true }).click();
  await page.getByRole("textbox", { name: "Start from", exact: true }).click();
  await page.getByRole("option", { name: "MNQ baseline" }).click();
  const launch = page.getByRole("button", { name: "Launch backtest" });
  await expect(launch).toBeEnabled();
  await expect(page.getByLabel("Parameter sweep (JSON)")).toBeHidden();
  await page.getByLabel("Test variants").check();
  await page.getByLabel("Parameter sweep (JSON)").fill('{"lookback":[5,10]}');
  await expect(page.getByRole("button", { name: "Launch 2 backtests" })).toBeEnabled();
  await page.getByLabel("Test variants").uncheck();
  await expect(launch).toBeEnabled();
  const end = page.getByLabel("End date (UTC, inclusive)");
  await end.fill("2025-01-01");
  await expect(launch).toBeDisabled();
  await expect(page.getByText("End precedes start")).toBeVisible();
  await end.fill(input.end);
  await page.getByRole("button", { name: /^Evaluate/ }).click();
  await expect(launch).toBeDisabled();
  await page.getByLabel("Development data ends").fill("2026-01-04");
  await page.getByLabel("Pass criteria").fill("At least 30 trades");
  await expect(launch).toBeEnabled();
  assert.equal(launches.length, 0);
  await launch.click();
  await expect.poll(() => launches.length).toBe(1);
  assert.deepEqual(launches[0], previews.at(-1));
  assert.deepEqual(launches[0].sweep, {});
  await expect(page).toHaveURL(/#\/runs/);
  await page.goto(base + "/#/portfolio");
  const switcher = page.getByRole("button", { name: /^Portfolios:/ });
  const saved = () => page.evaluate(() => JSON.parse(localStorage.getItem("quant-collective-combinations-v1")));
  await expect(page.getByTestId("selected-count")).toHaveText("1 strategy");
  await switcher.click();
  const name = page.getByLabel("Save as");
  const saveAs = page.getByRole("button", { name: "Save", exact: true });
  await name.fill("Original");
  await saveAs.click();
  const original = (await saved())[0];
  await name.fill("original");
  await expect(saveAs).toBeDisabled();
  await name.fill("Variation");
  await page.keyboard.press("Escape");
  const setCapital = async (value) => {
    await page.getByRole("button", { name: "Settings", exact: true }).click();
    await page.getByLabel("Starting capital (USD)").fill(value);
    await page.getByRole("button", { name: "Apply", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Portfolio settings" })).toBeHidden();
  };
  await setCapital("80000");
  await switcher.click();
  await expect(page.getByLabel("Save as")).toHaveValue("Variation");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect.poll(async () => (await saved()).length).toBe(2);
  let books = await saved();
  assert.deepEqual(books[1], original);
  assert.notEqual(books[0].id, original.id);
  const copyId = books[0].id;
  await page.keyboard.press("Escape");
  await setCapital("70000");
  await switcher.click();
  await page.getByRole("button", { name: /^Save changes/ }).click();
  await expect.poll(async () => (await saved())[0].settings.capital).toBe(70000);
  books = await saved();
  assert.equal(books[0].id, copyId);
  assert.deepEqual(books[1], original);
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 390, height: 844 });

  catalogItems = [item,
    { ...item, id: "es-book", key: "sample__ES", name: "ES strategy", symbol: "ES" },
    { ...item, id: "nq-book", key: "sample__NQ", name: "NQ strategy", symbol: "NQ" },
  ];
  const savedCopies = { [item.id]: 3, "es-book": 1, "nq-book": 2 };
  await page.evaluate(copies => {
    const key = "quant-collective-combinations-v1";
    const saved = JSON.parse(localStorage.getItem(key));
    saved[0].settings.copies = copies;
    localStorage.setItem(key, JSON.stringify(saved));
  }, savedCopies);
  await page.goto(base + "/#/portfolio/calendar");
  await page.reload();
  await expect(page.getByTestId("selected-count")).toHaveText("3 strategies");
  const removeStrategies = page.getByRole("button", { name: "Remove strategies", exact: true });
  const removal = page.getByRole("dialog", { name: "Remove strategies" });
  await removeStrategies.click();
  await expect(removal.getByRole("button", { name: "Remove", exact: true })).toBeDisabled();
  await removal.getByRole("checkbox", { name: "Select all" }).check();
  await removal.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("selected-count")).toHaveText("3 strategies");
  await removeStrategies.click();
  const selectAll = removal.getByRole("checkbox", { name: "Select all" });
  await expect(selectAll).not.toBeChecked();
  await selectAll.check();
  await removal.getByRole("checkbox", { name: item.name }).uncheck();
  await removal.getByRole("button", { name: "Remove 2 strategies" }).click();
  await expect(page.getByTestId("selected-count")).toHaveText("1 strategy");
  await expect.poll(() => trackedIds).toEqual([item.id]);
  await expect.poll(async () => (await saved())[0].settings.copies).toEqual(savedCopies);
  await page.getByRole("link", { name: "Overview" }).click();
  await page.getByRole("heading", { name: /^Strategies 1/ }).scrollIntoViewIfNeeded();
  const removeRow = page.getByTestId("selected-strategies").getByRole("button", { name: "Remove Sample strategy MNQ 1h" });
  await expect(removeRow).toBeInViewport();
  await expect(removeRow).toHaveText("Remove");
  await removeRow.click();
  await expect(page.getByTestId("selected-count")).toHaveText("0 strategies");
  await expect.poll(() => trackedIds).toEqual([]);
  await expect.poll(async () => (await saved())[0].settings.copies).toEqual(savedCopies);

  await page.getByRole("link", { name: "New backtest", exact: true }).click();
  await expect(page.getByRole("heading", { name: "New backtest" })).toBeVisible();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2), false);

  state.strategies.push({ ...strategy, id: "zulu", name: "Zulu strategy" }, { ...strategy, id: "alpha", name: "Alpha strategy" });
  const passed = { ...run, id: "evaluated-es", tags: "", notes: "", input: { ...run.input,
    dataset: { ...dataset, symbol: "ES" }, research: { role: "Test", scenario: "Baseline" } } };
  state.runs.push(passed);
  state.evaluations.push({ id: "es-evaluation", name: "ES evaluation", created_at: dataset.last, status: "Succeeded",
    folds: [{ training: [], tests: [passed.id] }], scenarios: ["Baseline"],
    result: { scenarios: [{ name: "Baseline", outcome: "Meets criteria", metrics }] } });
  catalogItems = [run, passed].map(source => ({ ...item, id: source === run ? item.id : "passed-es",
    symbol: source.input.dataset.symbol, timeframe: source.input.timeframe, parameters: source.input.parameters,
    max_drawdown: -.01, max_drawdown_dollars: 100, chart_points: [0, -5, 20], source_run_ids: [source.id] }));
  trackedIds = [item.id];
  await page.evaluate(() => localStorage.clear());
  await page.goto(base + "/#/strategies");
  await page.reload();
  const overviewNames = page.locator(".wb-strategy-name strong");
  await expect(overviewNames).toHaveCount(4);
  const expectedOrder = await overviewNames.allTextContents();
  assert.deepEqual(expectedOrder, [strategy.name, "Alpha strategy", "Zulu strategy", strategy.name]);
  await page.goto(base + "/#/portfolio");
  await page.getByRole("button", { name: "Add strategy", exact: true }).click();
  const pickerNames = page.locator(".strategy-picker-group-name");
  await expect(pickerNames).toHaveText(expectedOrder);
  const drawer = page.getByRole("dialog", { name: "Add strategies" });
  const robustness = drawer.getByRole("region", { name: /^At robustness/ });
  const failed = drawer.getByRole("region", { name: /^Failed/ });
  const preview = robustness.locator(".strategy-picker-group-preview");
  await expect(preview.getByText("Net P&L", { exact: true })).toBeVisible();
  await expect(preview.locator("svg, canvas")).toHaveCount(0);
  await expect(robustness.getByRole("heading", { name: /^At robustness/ })).toBeInViewport();
  await expect(robustness.getByText("Robustness · Next up", { exact: true })).toBeInViewport();
  await expect(robustness.getByRole("img", { name: "Robustness · Next up" })).toBeInViewport();
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(robustness.getByText("Robustness · Next up", { exact: true })).toBeInViewport();
  await expect(failed.getByText("Evaluation · Failed", { exact: true })).toBeVisible();
  await expect(robustness.locator(".strategy-picker-group-head")).toHaveAttribute("aria-expanded", "false");
  await robustness.getByRole("button", { name: "Add best run for Sample strategy" }).click();
  await expect(robustness.getByRole("button", { name: "Best run already added for Sample strategy" })).toBeDisabled();
  await expect.poll(() => trackedIds).toContain("passed-es");
  const sort = page.getByRole("textbox", { name: "Sort", exact: true });
  await sort.click();
  await page.getByRole("option", { name: "Highest net P&L" }).click();
  await expect(pickerNames.first()).toHaveText(strategy.name);
  await expect(pickerNames).toHaveCount(3);
  await sort.click();
  await page.getByRole("option", { name: "Research stage", exact: true }).click();
  await expect(pickerNames).toHaveText(expectedOrder);

  // Recalculate even when matching backtests exist. An import retry resumes only this attempt.
  const latest = "2026-01-09";
  const oldRuns = ["MNQ", "ES"].map((symbol, i) => {
    const market = { ...dataset, id: symbol, symbol, first: "2023-01-01", last: latest };
    state.datasets.push(market);
    return { ...run, id: "old-" + symbol, tags: "", input: { ...run.input, dataset: market,
      start: i ? "2025-01-01" : "2024-01-01", end: i ? "2025-06-30" : "2024-06-30" } };
  });
  const historyFor = source => ({ ...item, id: "book-" + source.id, symbol: source.input.dataset.symbol,
    timeframe: source.input.timeframe, source_run_ids: [source.id], net_pnl: source.result.metrics.net_pnl, start: source.input.start, end: source.input.end,
    coverage: [{ start: source.input.start, end: source.input.end }] });
  const latestRuns = oldRuns.map(r => ({ ...r, id: "latest-" + r.input.dataset.symbol, input: { ...r.input, end: latest } }));
  state.runs = [...oldRuns, ...latestRuns];
  state.evaluations = [];
  catalogItems = oldRuns.map(historyFor);
  trackedIds = catalogItems.map(i => i.id);
  await page.evaluate(copies => {
    localStorage.removeItem("quant-collective-combinations-v1");
    const key = "quant-collective-v1";
    localStorage.setItem(key, JSON.stringify({ ...JSON.parse(localStorage.getItem(key)), copies,
      start: "2024-01-01", end: "2024-06-30", followCommonStart: true, followLatest: true }));
  }, { [trackedIds[0]]: 3, [trackedIds[1]]: 2 });
  const freshRuns = [];
  let imports = 0;
  await page.route("**/api/workbench/runs", route => {
    const payload = route.request().postDataJSON();
    const batch = 1 + Math.floor(freshRuns.length / oldRuns.length);
    const template = latestRuns.find(r => r.input.dataset.id === payload.dataset_id);
    assert.equal(payload.end, latest);
    assert.equal(payload.start, template.input.start);
    const fresh = { ...template, id: `fresh-${batch}-${payload.dataset_id}`,
      result: { ...template.result, metrics: { ...template.result.metrics, net_pnl: batch * 10 } } };
    freshRuns.push(fresh);
    return route.fulfill({ json: [{ ...fresh, status: "Queued" }] });
  });
  await page.route("**/api/workbench/runs/fresh-*/status", route => {
    const id = new URL(route.request().url()).pathname.split("/").at(-2);
    state.runs.push(freshRuns.find(r => r.id === id));
    return route.fulfill({ json: { status: "Succeeded" } });
  });
  await page.route("**/api/workbench/collective/import", route => {
    const batch = freshRuns.slice(-2);
    assert.deepEqual(route.request().postDataJSON().runIds.sort(), batch.map(r => r.id).sort());
    if (++imports === 1) return route.fulfill({ json: { running: false, error: "Fixture import interrupted" } });
    catalogItems.push(...batch.map(historyFor));
    return route.fulfill({ json: { running: false } });
  });
  await page.goto(base + "/#/portfolio");
  await page.reload();
  const recalculate = page.getByRole("button", { name: "Recalculate portfolio", exact: true });
  await expect(page.getByRole("heading", { name: "Combined book unavailable" })).toBeVisible();
  await recalculate.click();
  await expect(page.getByText("Fixture import interrupted")).toBeVisible({ timeout: 15000 });
  assert.deepEqual(trackedIds.sort(), oldRuns.map(r => "book-" + r.id).sort());
  await page.getByRole("button", { name: "Retry recalculation" }).click();
  await expect(page.getByText("Portfolio recalculated", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Combined book unavailable" })).toBeHidden();
  assert.equal(freshRuns.length, 2);
  await expect(page.getByTestId("portfolio-pnl")).toHaveText("+$50");
  await recalculate.click();
  await expect.poll(() => trackedIds.slice().sort(), { timeout: 15000 }).toEqual(["book-fresh-2-ES", "book-fresh-2-MNQ"]);
  await expect(page.getByTestId("portfolio-pnl")).toHaveText("+$100");
  const updated = await page.evaluate(() => JSON.parse(localStorage.getItem("quant-collective-v1")));
  assert.deepEqual(updated.copies, { "book-fresh-2-MNQ": 3, "book-fresh-2-ES": 2 });
  assert.deepEqual([updated.start, updated.end], ["2025-01-01", latest]);
  assert.equal(freshRuns.length, 4);

  // Confirm that a sparse trade window spanning New Year reads chronologically.
  await page.route("**/api/workbench/collective/series", route => {
    const { ids } = route.request().postDataJSON();
    const trades = ["2025-12-31", "2026-01-05"].map(date => ({
      entry: date + "T10:00:00Z", exit: date + "T12:00:00Z", pnl: 10, synthetic_exit: false,
    }));
    const daily = trades.map(t => ({ date: t.exit.slice(0, 10), pnl: t.pnl })).concat({ date: latest, pnl: 0 });
    return route.fulfill({ json: ids.map(id => ({
      id, coverage: catalogItems.find(book => book.id === id).coverage, daily, trades,
    })) });
  });
  await page.goto(base + "/#/portfolio/risk");
  await page.reload();
  const recentForm = page.getByTestId("recent-form-book-fresh-2-MNQ");
  const tradeWindow = recentForm.getByText("Last 30 trade exits (2 available)").locator("..");
  await expect(tradeWindow).toContainText(/Dec 31, 2025\s*–\s*Jan 5, 2026/);
  const dailyWindow = recentForm.getByText("Last 20 observed days (3 available)").locator("..");
  await expect(dailyWindow).toContainText(/Dec 31, 2025\s*–\s*Jan 9, 2026/);
  assert.deepEqual(errors, []);
  console.log("Passed backtest setup, portfolio selection, mobile navigation, and fresh portfolio recalculation with retry.");
} finally {
  await browser.close();
}
