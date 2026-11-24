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
    if (path.endsWith("/collective")) return route.fulfill({ json: { items: [item], generated_at: dataset.last, errors: [], definitions: {}, market_data_through: {} } });
    if (path.endsWith("/series")) return route.fulfill({ json: [{ id: item.id, coverage: item.coverage, trades: [], daily: [{ date: input.start, pnl: 20 }] }] });
    if (path.includes("/tracking")) return route.fulfill({ json: { selection: [item.id], items: {} } });
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
  await page.getByRole("textbox", { name: "Use preset", exact: true }).click();
  await page.getByRole("option", { name: "MNQ baseline" }).click();
  const launch = page.getByRole("button", { name: "Launch backtest" });
  await expect(launch).toBeEnabled();
  await expect(page.getByLabel("Parameter sweep (JSON)")).toBeHidden();
  await page.getByLabel("Test multiple variants").check();
  await page.getByLabel("Parameter sweep (JSON)").fill('{"lookback":[5,10]}');
  await expect(page.getByRole("button", { name: "Launch 2 runs" })).toBeEnabled();
  await page.getByLabel("Test multiple variants").uncheck();
  await expect(launch).toBeEnabled();
  const end = page.getByLabel("End date (UTC, inclusive)");
  await end.fill("2025-01-01");
  await expect(launch).toBeDisabled();
  await expect(page.getByText("End precedes start")).toBeVisible();
  await end.fill(input.end);
  await page.getByRole("textbox", { name: "Run purpose", exact: true }).click();
  await page.getByRole("option", { name: "Evaluation" }).click();
  await expect(launch).toBeDisabled();
  await page.getByLabel("Development ends").fill("2026-01-04");
  await page.getByLabel("Evaluation criteria").fill("At least 30 trades");
  await expect(launch).toBeEnabled();
  assert.equal(launches.length, 0);
  await launch.click();
  await expect.poll(() => launches.length).toBe(1);
  assert.deepEqual(launches[0], previews.at(-1));
  assert.deepEqual(launches[0].sweep, {});
  await page.goto(base + "/#/portfolio");
  const name = page.getByLabel("New portfolio name");
  const saveAs = page.getByRole("button", { name: "Save as new portfolio" });
  const saved = () => page.evaluate(() => JSON.parse(localStorage.getItem("quant-collective-combinations-v1")));
  await expect(page.getByTestId("selected-count")).toHaveText("1 book");
  await name.fill("Original");
  await saveAs.click();
  const original = (await saved())[0];
  await name.fill("original");
  await expect(saveAs).toBeDisabled();
  await name.fill("Variation");
  const capital = page.getByLabel("Starting capital (USD)");
  await capital.fill("80000");
  await saveAs.click();
  await expect.poll(async () => (await saved()).length).toBe(2);
  let books = await saved();
  assert.deepEqual(books[1], original);
  assert.notEqual(books[0].id, original.id);
  const copyId = books[0].id;
  await capital.fill("70000");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect.poll(async () => (await saved())[0].settings.capital).toBe(70000);
  books = await saved();
  assert.equal(books[0].id, copyId);
  assert.deepEqual(books[1], original);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("link", { name: "New backtest", exact: true }).click();
  await expect(page.getByRole("heading", { name: "New backtest" })).toBeVisible();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2), false);
  assert.deepEqual(errors, []);
  console.log("Passed backtest setup, failed-check cards, portfolio save and copy, and mobile navigation.");
} finally {
  await browser.close();
}
