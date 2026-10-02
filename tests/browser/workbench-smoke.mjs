import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { createReadStream, existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { request as httpRequest } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, normalize, resolve } from "node:path";
import { chromium, expect } from "@playwright/test";
import { DatabaseSync } from "node:sqlite";
import { createRecordRepository } from "../../server/infra/recordRepository.ts";

const root = resolve(".");
const dist = join(root, "dist");
assert(existsSync(join(dist, "index.html")), "Run npm run build before the fixture browser smoke test.");

const home = await mkdtemp(join(tmpdir(), "strategy-workbench-browser-"));
const artifacts = join(home, "artifacts");
const datasets = join(home, "datasets");
const collective = join(home, "collective");
await Promise.all([
  mkdir(artifacts, { recursive: true }),
  mkdir(datasets, { recursive: true }),
  mkdir(collective, { recursive: true }),
]);

const dataPath = join(datasets, "fixture.parquet");
const fixtureBytes = Buffer.from("fixture metadata only\n", "utf8");
await writeFile(dataPath, fixtureBytes);
await writeFile(
  join(datasets, "catalog.json"),
  JSON.stringify({
    datasets: [
      {
        id: "browser-fixture-v1",
        symbol: "FIXTURE",
        source: "Synthetic browser fixture",
        rows: 0,
        first: "2026-01-05T00:00:00Z",
        last: "2026-01-09T23:59:00Z",
        path: dataPath,
        archive: "synthetic/browser-fixture",
        checksum: createHash("sha256").update(fixtureBytes).digest("hex"),
        registered_at: "2026-01-10T00:00:00Z",
        currency: "USD",
        tick_size: 0.25,
        point_value: 2,
        warnings: ["Synthetic fixture; browser workflow validation only."],
        quality: {
          gaps_over_one_minute: 0,
          contract_changes: 0,
          duplicates: 0,
          null_rows: 0,
        },
      },
    ],
    errors: [],
  }),
);
const collectiveSeriesName = "0123456789abcdefabcd-0123456789abcdef.json";
const collectiveSeries = {
  id: "fixture-configuration",
  daily: [
    { date: "2026-01-05", pnl: 10 },
    { date: "2026-01-06", pnl: -4, terminal: true },
  ],
  trades: [],
  coverage: [{ start: "2026-01-05", end: "2026-01-06" }],
  provenance_version: 2,
};
const collectiveSeriesBytes = Buffer.from(JSON.stringify(collectiveSeries));
await writeFile(join(collective, collectiveSeriesName), collectiveSeriesBytes);
const periodSeriesName = "fedcba9876543210fedc-fedcba9876543210.json";
const periodSeries = {
  id: "period-fixture-configuration",
  daily: [
    { date: "2025-07-01", pnl: 130 },
    { date: "2025-07-02", pnl: -30 },
    { date: "2025-12-31", pnl: -20 },
    { date: "2026-01-01", pnl: 30 },
    { date: "2026-01-02", pnl: -12 },
    { date: "2026-01-03", pnl: 12 },
    { date: "2026-08-28", pnl: 16 },
    { date: "2026-08-29", pnl: -6 },
    { date: "2026-08-30", pnl: -4 },
    { date: "2026-09-30", pnl: 3, terminal: true },
  ],
  trades: [],
  coverage: [{ start: "2025-07-01", end: "2026-09-30" }],
  provenance_version: 2,
};
periodSeries.trades = periodSeries.daily.map(({ date, pnl }) => ({
  entry: `${date}T09:00:00Z`,
  exit: `${date}T16:00:00Z`,
  pnl,
}));
const periodSeriesBytes = Buffer.from(JSON.stringify(periodSeries));
await writeFile(join(collective, periodSeriesName), periodSeriesBytes);
await writeFile(
  join(collective, "index.json"),
  JSON.stringify({
    version: 1,
    generated_at: "2026-01-10T00:00:00Z",
    items: [
      {
        id: collectiveSeries.id,
        key: "fixture-strategy__FIXTURE__1h__full-trading-day",
        name: "Fixture strategy",
        symbol: "FIXTURE",
        timeframe: "1h",
        session: "full-trading-day",
        source: "Synthetic browser fixture",
        start: "2026-01-05",
        end: "2026-01-06",
        capital: 100000,
        working: true,
        feasible: true,
        tested: true,
        benchmark: false,
        reasons: ["Synthetic browser workflow validation only."],
        parameters: { lookback: 5 },
        net_pnl: 6,
        recent_pnl: 6,
        trades: 0,
        coverage: collectiveSeries.coverage,
        series_file: collectiveSeriesName,
        checksum: createHash("sha256").update(collectiveSeriesBytes).digest("hex"),
      },
      {
        id: periodSeries.id,
        key: "period-fixture-strategy__FIXTURE__1h__full-trading-day",
        name: "Period fixture strategy",
        symbol: "FIXTURE",
        timeframe: "1h",
        session: "full-trading-day",
        source: "Synthetic browser fixture",
        start: "2025-07-01",
        end: "2026-09-30",
        capital: 100000,
        working: false,
        feasible: false,
        tested: true,
        benchmark: false,
        reasons: ["Synthetic period-filter validation only."],
        parameters: { lookback: 5 },
        net_pnl: 119,
        recent_pnl: 39,
        trades: periodSeries.trades.length,
        coverage: periodSeries.coverage,
        series_file: periodSeriesName,
        checksum: createHash("sha256").update(periodSeriesBytes).digest("hex"),
      },
    ],
    errors: [],
    sources: [],
    definitions: {
      working: "Fixture catalog",
      feasible: "Fixture catalog",
      pnl: "Fixture catalog",
    },
    market_data_through: {},
  }),
);

async function listen(server) {
  await new Promise((resolveDone, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveDone);
  });
  const address = server.address();
  assert(address && typeof address === "object");
  return address.port;
}

const apiProbe = createServer();
const apiPort = await listen(apiProbe);
await new Promise((resolveDone) => apiProbe.close(resolveDone));
let api;
let apiLog = "";
let web;
let browser;
let fixtureDb;

const delay = (milliseconds) =>
  new Promise((resolveDone) => setTimeout(resolveDone, milliseconds));

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  const exited = new Promise((resolveDone) => child.once("exit", resolveDone));
  child.kill("SIGTERM");
  await Promise.race([exited, delay(5_000)]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

function contentType(path) {
  return (
    {
      ".css": "text/css; charset=utf-8",
      ".html": "text/html; charset=utf-8",
      ".js": "text/javascript; charset=utf-8",
      ".json": "application/json; charset=utf-8",
      ".svg": "image/svg+xml",
      ".woff2": "font/woff2",
    }[extname(path)] || "application/octet-stream"
  );
}

function fixtureWebServer() {
  return createServer((request, response) => {
    if (request.url?.startsWith("/api/workbench")) {
      const upstream = httpRequest(
        {
          hostname: "127.0.0.1",
          port: apiPort,
          path: request.url,
          method: request.method,
          // This fixture uses a random web port; map only its same-origin
          // browser requests to the isolated API's equivalent origin.
          headers: { ...request.headers, ...(request.headers.origin === `http://${request.headers.host}`
            ? { origin: `http://127.0.0.1:${apiPort}` } : {}) },
        },
        (upstreamResponse) => {
          response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
          upstreamResponse.pipe(response);
        },
      );
      upstream.on("error", (error) => {
        response.writeHead(502, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ error: error.message }));
      });
      request.pipe(upstream);
      return;
    }

    const pathname = new URL(request.url || "/", "http://fixture.local").pathname;
    const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
    const candidate = normalize(join(dist, relative));
    const path = candidate.startsWith(dist) && existsSync(candidate)
      ? candidate
      : join(dist, "index.html");
    response.writeHead(200, {
      "Cache-Control": "no-store",
      "Content-Type": contentType(path),
    });
    createReadStream(path).pipe(response);
  });
}

try {
  api = spawn(process.execPath, ["server/workbench.ts"], {
    cwd: root,
    env: {
      ...process.env,
      WORKBENCH_HOME: home,
      WORKBENCH_ARTIFACTS: artifacts,
      WORKBENCH_PORT: String(apiPort),
      WORKBENCH_CONCURRENCY: "1",
      PYTHONDONTWRITEBYTECODE: "1",
    },
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const capture = (chunk) => {
    apiLog = (apiLog + chunk).slice(-30_000);
  };
  api.stdout.on("data", capture);
  api.stderr.on("data", capture);

  let state;
  for (let attempt = 0; attempt < 150; attempt += 1) {
    if (api.exitCode !== null)
      throw new Error(`Fixture API exited during startup:\n${apiLog}`);
    try {
      const response = await fetch(
        `http://127.0.0.1:${apiPort}/api/workbench/state`,
      );
      if (response.ok) {
        state = await response.json();
        break;
      }
    } catch {
      // The listener is not ready yet.
    }
    await delay(100);
  }
  assert(state, `Fixture API startup timed out:\n${apiLog}`);
  const baselineStrategyIds = [
    "aw-model-nq",
    "buy-hold",
    "market-intraday-momentum",
    "moving-average",
    "multi-speed-momentum",
    "pine-daily-tsmom",
    "pine-overnight-block",
    "pine-overnight-drift",
    "pine-tsmom-orb",
    "rsi2-reversion",
    "rsi2-reversion-corrected",
    "short-term-reversal",
    "short-term-reversal-minute",
    "snd",
    "snd-zone-exit",
    "vwap-reversion",
    "wyckoff-nq",
  ];
  const trackedPaths = new Set(
    execFileSync("git", ["ls-files"], { cwd: root, encoding: "utf8" })
      .split(/\r?\n/u)
      .filter(Boolean),
  );
  const trackedStrategies = state.strategies.filter((strategy) =>
    trackedPaths.has(strategy.file),
  );
  const archivedScripts = state.archived_scripts || [];
  const archivedIds = new Set(archivedScripts.map((script) => script.id));
  // New tracked adapters may extend the preserved baseline.
  const trackedIds = new Set(trackedStrategies.map(strategy => strategy.id));
  for (const id of baselineStrategyIds) assert(trackedIds.has(id) || archivedIds.has(id), `Missing baseline adapter ${id}`);
  assert.equal(trackedIds.size, trackedStrategies.length, "Tracked adapter IDs must be unique");
  const trackedLibrary = state.library.entries.filter((entry) =>
    trackedPaths.has(entry.path),
  );
  const preservedLibraryPaths = new Set([
    ...trackedLibrary.map((entry) => entry.path),
    ...archivedScripts.map((script) => script.original_path).filter((path) => trackedPaths.has(path)),
  ]);
  assert(preservedLibraryPaths.size >= 171, "Tracked and archived library inventory must retain its baseline");
  assert.equal(
    trackedLibrary.filter((entry) => entry.path.endsWith(".pine")).length,
    21,
  );
  assert.deepEqual(state.errors, []);

  web = fixtureWebServer();
  const webPort = await listen(web);
  const base = `http://127.0.0.1:${webPort}`;
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.addInitScript(() => {
    if (!localStorage.getItem("quant-collective-v1"))
      localStorage.setItem("quant-collective-v1", JSON.stringify({
        capital: 100000, copies: { "fixture-configuration": 1 },
        start: "2026-01-05", end: "2026-01-06", basis: "marked", followLatest: true,
      }));
  });
  const pageErrors = [];
  page.on("pageerror", (error) => { pageErrors.push(error.message); console.error(`Browser error: ${error.message}`); });
  const portfolioRequests = { catalog: 0, series: 0, summary: 0 };
  const portfolioResponses = { series: 0, summary: 0 };
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/workbench/collective") portfolioRequests.catalog += 1;
    if (url.pathname === "/api/workbench/collective/series") portfolioRequests.series += 1;
    if (url.pathname === "/api/workbench/state" && url.searchParams.get("view") === "summary") portfolioRequests.summary += 1;
  });
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname === "/api/workbench/collective/series") portfolioResponses.series += 1;
    if (url.pathname === "/api/workbench/state" && url.searchParams.get("view") === "summary") portfolioResponses.summary += 1;
  });

  const routes = [
    { route: "portfolio", heading: "Combined portfolio", activeTab: "Overview" },
    { route: "portfolio/calendar", heading: "Combined portfolio", activeTab: "Calendar" },
    { route: "portfolio/contributions", heading: "Combined portfolio", activeTab: "Contributions" },
    { route: "portfolio/pause", heading: "Combined portfolio", activeTab: "Pause & sizing" },
    { route: "workspace", heading: "Research" },
    { route: "scorecards", heading: "Strategy scorecards" },
    { route: "runs", heading: "Runs & compare" },
    { route: "runs/nq-monthly", heading: "Runs & compare", activeTab: "NQ monthly" },
    { route: "runs/experiments", heading: "Runs & compare", activeTab: "Experiments" },
    { route: "new-run", heading: "New run" },
    { route: "evaluations", heading: "Evaluations & regimes" },
    { route: "event-studies", heading: "Pattern event studies" },
    { route: "scripts", heading: "Scripts & library", activeTab: "Runnable scripts" },
    { route: "scripts/library", heading: "Scripts & library", activeTab: "Library" },
    { route: "datasets", heading: "Datasets" },
  ];
  await page.goto(`${base}/#/${routes[0].route}`);
  await page.getByTestId("selected-count").filter({ hasText: "1 book" }).waitFor();
  await expect.poll(() => portfolioResponses.series).toBeGreaterThan(0);
  const compactRow = page.getByTestId("selected-strategies").locator("li");
  await expect(compactRow).toHaveCount(1);
  await expect(compactRow.locator(".wb-book-symbol")).toHaveText("FIXTURE");
  await expect(compactRow.locator(".wb-book-name")).toHaveText("Fixture strategy");
  await expect(compactRow.locator(".wb-book-coverage")).toContainText("Data through 2026-01-09");
  await expect(compactRow.locator(".wb-book-coverage")).toContainText("Simulated through 2026-01-06");
  await expect(compactRow.locator(".wb-book-coverage")).toContainText("Manual update required");
  const initialEnd = page.getByRole("textbox", { name: "P&L end" });
  const initialFollowLatest = page.getByRole("switch", { name: /Follow latest/ });
  await initialEnd.fill("2026-01-07");
  await expect(initialFollowLatest).not.toBeChecked();
  await expect(initialEnd).toHaveValue("2026-01-07");
  await expect(page.getByText(/Your manually set P&L end is 2026-01-07/)).toBeVisible();
  await expect(page.getByText(/Fixture strategy \/ FIXTURE \/ 1h is simulated through 2026-01-06/)).toBeVisible();
  await expect(page.getByText(/The selected period \(2026-01-05 to 2026-01-07\)/)).toHaveCount(0);
  await page.getByRole("button", { name: "Apply common tested window" }).click();
  await expect(initialEnd).toHaveValue("2026-01-06");
  await expect(initialFollowLatest).not.toBeChecked();
  await initialFollowLatest.check();
  await expect(compactRow.locator(".wb-book-performance span")).toHaveText(["P&L +0.01%", "Drawdown 0.00%"]);
  await expect(compactRow.getByRole("button", { name: "Remove Fixture strategy FIXTURE 1h" })).toBeVisible();
  await expect(compactRow.locator("button")).toHaveCount(1);
  await expect(compactRow.locator("a, input, details")).toHaveCount(0);
  assert.equal(portfolioRequests.summary, 0, "Portfolio startup must defer research state");
  assert.equal(portfolioRequests.catalog, 1, "StrictMode must share the initial catalog request");
  const seriesBeforePicker = portfolioRequests.series;
  await page.getByRole("button", { name: "Add", exact: true }).first().click();
  await expect(page.getByRole("tablist", { name: "Strategy research status" })).toBeVisible();
  assert(portfolioRequests.summary > 0, "Opening the picker must load research state");
  assert.equal(portfolioRequests.series, seriesBeforePicker, "Research state must not refetch portfolio series");
  const summaryBeforePoll = portfolioResponses.summary;
  await expect.poll(() => portfolioResponses.summary, { timeout: 20_000 }).toBeGreaterThan(summaryBeforePoll);
  assert.equal(portfolioRequests.series, seriesBeforePicker, "A timed research state poll must not refetch portfolio series");
  await page.getByRole("button", { name: "Done", exact: true }).click();
  const searchPage = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let searchSummaryRequests = 0;
  searchPage.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/workbench/state" && url.searchParams.get("view") === "summary") searchSummaryRequests += 1;
  });
  await searchPage.goto(`${base}/#/portfolio`);
  await searchPage.getByTestId("selected-count").filter({ hasText: "1 book" }).waitFor();
  assert.equal(searchSummaryRequests, 0, "Fresh portfolio Search must also defer research state until opened");
  await searchPage.getByRole("button", { name: "Search Ctrl K" }).click();
  const searchDialog = searchPage.getByRole("dialog", { name: "Search the workbench" });
  await searchDialog.getByRole("textbox", { name: "Search pages, runs, strategies and evaluations" }).fill("moving");
  await expect(searchDialog.getByRole("button", { name: /Moving-average trend/ })).toBeVisible();
  assert(searchSummaryRequests > 0, "Search must load research state on demand");
  await searchPage.close();
  for (let index = 0; index < routes.length; index += 1) {
    const { route, heading, activeTab } = routes[index];
    if (index > 0) {
      await page.evaluate((nextRoute) => {
        window.location.hash = `#/${nextRoute}`;
      }, route);
    }
    await page.getByRole("heading", { name: heading, level: 1 }).waitFor();
    await expect(page.getByRole("navigation", { name: "Strategy development progression" })).toHaveCount(0);
    if (activeTab) {
      const tab = page.getByRole("link", { name: activeTab, exact: true });
      await tab.waitFor();
      assert.equal(await tab.getAttribute("aria-current"), "page", route);
    }
    if (route === "portfolio")
      await page.getByRole("button", { name: "Add", exact: true }).first().waitFor();
  }
  await page.evaluate(() => {
    window.location.hash = "#/portfolio";
  });
  await page.getByRole("heading", { name: "Combined portfolio", level: 1 }).waitFor();
  await page.getByTestId("selected-count").filter({ hasText: "1 book" }).waitFor();
  const pickerForCopies = async () => {
    await page.getByRole("button", { name: "Add", exact: true }).first().click();
    const picker = page.locator(".collective-picker:visible");
    const summary = picker.locator("summary").filter({ hasText: "Selected copies" });
    if (!(await summary.evaluate(element => element.parentElement.open))) await summary.click();
    return { picker, input: picker.getByLabel(/Copies of Fixture strategy FIXTURE 1h/) };
  };
  const setFixtureCopies = async count => {
    const { picker, input } = await pickerForCopies();
    await input.fill(String(count));
    await picker.getByRole("button", { name: "Done", exact: true }).click();
  };
  const expectFixtureCopies = count => expect.poll(() => page.evaluate(() =>
    JSON.parse(localStorage.getItem("quant-collective-v1") || "{}").copies?.["fixture-configuration"],
  )).toBe(count);
  const clearFixtureSelection = async () => {
    await page.getByRole("button", { name: "Add", exact: true }).first().click();
    const picker = page.locator(".collective-picker:visible");
    await picker.getByRole("button", { name: "Clear", exact: true }).click();
    await picker.getByRole("button", { name: "Done", exact: true }).click();
  };
  await setFixtureCopies(3);
  await page.getByPlaceholder("Name this combination").fill("Fixture saved book");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByPlaceholder("Load a saved combination")).toHaveValue("Fixture saved book");
  await clearFixtureSelection();
  await page.getByTestId("selected-count").filter({ hasText: "0 books" }).waitFor();
  await page.reload();
  await page.getByRole("heading", { name: "Combined portfolio", level: 1 }).waitFor();
  await page.getByTestId("selected-count").filter({ hasText: "1 book" }).waitFor();
  await expectFixtureCopies(3);
  const restoredCopies = await pickerForCopies();
  await expect(restoredCopies.input).toHaveValue("3");
  await restoredCopies.picker.getByRole("button", { name: "Done", exact: true }).click();
  const savedBooks = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("quant-collective-combinations-v1") || "[]"),
  );
  assert.equal(savedBooks[0].name, "Fixture saved book");
  assert.equal(savedBooks[0].settings.copies["fixture-configuration"], 3);
  await expect(page.getByRole("textbox", { name: "P&L start" })).toHaveValue(savedBooks[0].settings.start);
  await expect(page.getByRole("textbox", { name: "P&L end" })).toHaveValue(savedBooks[0].settings.end);

  await clearFixtureSelection();
  await page.getByTestId("selected-count").filter({ hasText: "0 books" }).waitFor();
  await page.getByPlaceholder("Load a saved combination").click();
  await page.getByRole("option", { name: "Fixture saved book", exact: true }).click();
  await page.getByTestId("selected-count").filter({ hasText: "1 book" }).waitFor();
  await expect(page.getByPlaceholder("Load a saved combination")).toHaveValue("Fixture saved book");
  await expectFixtureCopies(3);
  const pnlStart = page.getByRole("textbox", { name: "P&L start" });
  const pnlEnd = page.getByRole("textbox", { name: "P&L end" });
  const followLatest = page.getByRole("switch", { name: /Follow latest/ });
  await pnlStart.fill("2026-01-05");
  await pnlEnd.fill("2026-01-05");
  await expect(followLatest).not.toBeChecked();
  await page.reload();
  await page.getByTestId("selected-count").filter({ hasText: "1 book" }).waitFor();
  await expect(page.getByRole("textbox", { name: "P&L start" })).toHaveValue(savedBooks[0].settings.start);
  await expect(page.getByRole("textbox", { name: "P&L end" })).toHaveValue(savedBooks[0].settings.end);
  await expect(page.getByRole("switch", { name: /Follow latest/ })).toBeChecked();
  await expectFixtureCopies(3);
  await expect.poll(async () => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/workbench/collective/tracking`);
    return (await response.json()).selection;
  }).toEqual(["fixture-configuration"]);
  await page.getByRole("switch", { name: /Follow latest/ }).uncheck();
  await page.getByRole("textbox", { name: "P&L end" }).fill("2026-01-05");
  await page.getByRole("switch", { name: /Follow latest/ }).check();
  await expect(page.getByRole("textbox", { name: "P&L end" })).toHaveValue("2026-01-06");

  // Saving a loaded combination updates its existing record, and deletion persists.
  await page.getByPlaceholder("Load a saved combination").click();
  await page.getByRole("option", { name: "Fixture saved book", exact: true }).click();
  await expect(page.getByPlaceholder("Load a saved combination")).toHaveValue("Fixture saved book");
  await setFixtureCopies(5);
  await page.locator(".wb-saved-combinations").getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByPlaceholder("Load a saved combination")).toHaveValue("Fixture saved book");
  await expect.poll(() => page.evaluate(() =>
    JSON.parse(localStorage.getItem("quant-collective-combinations-v1") || "[]"),
  )).toMatchObject([{ id: savedBooks[0].id, name: "Fixture saved book", settings: { copies: { "fixture-configuration": 5 } } }]);

  // The row X changes the active combination without rewriting its saved record.
  await page.getByTestId("selected-strategies")
    .getByRole("button", { name: "Remove Fixture strategy FIXTURE 1h" }).click();
  await expect(page.getByTestId("selected-count")).toHaveText("0 books");
  await expect(page.getByPlaceholder("Load a saved combination")).toHaveValue("Fixture saved book");
  await expect.poll(() => page.evaluate(() =>
    JSON.parse(localStorage.getItem("quant-collective-v1") || "{}").copies,
  )).toEqual({});
  await expect.poll(() => page.evaluate(() =>
    JSON.parse(localStorage.getItem("quant-collective-combinations-v1") || "[]")[0]?.settings.copies,
  )).toEqual({ "fixture-configuration": 5 });
  await page.reload();
  await page.getByTestId("selected-count").filter({ hasText: "1 book" }).waitFor();
  await expectFixtureCopies(5);
  await expect(page.getByPlaceholder("Load a saved combination")).toHaveValue("Fixture saved book");
  await expect(page.getByPlaceholder("Clear selection to save a new combination")).toBeDisabled();
  await page.locator(".wb-saved-combinations").getByRole("button", { name: "Clear saved combination" }).click();
  await expect(page.getByPlaceholder("Load a saved combination")).toHaveValue("");
  await expect(page.getByPlaceholder("Name this combination")).toBeEnabled();
  await expectFixtureCopies(5);
  await page.getByPlaceholder("Name this combination").fill("Second saved book");
  await page.locator(".wb-saved-combinations").getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByPlaceholder("Load a saved combination")).toHaveValue("Second saved book");
  await expect.poll(() => page.evaluate(() =>
    JSON.parse(localStorage.getItem("quant-collective-combinations-v1") || "[]").map((book) => book.name),
  )).toEqual(["Second saved book", "Fixture saved book"]);
  await page.locator(".wb-saved-combinations").getByRole("button", { name: "Delete", exact: true }).click();
  await expect.poll(() => page.evaluate(() =>
    JSON.parse(localStorage.getItem("quant-collective-combinations-v1") || "[]").map((book) => book.name),
  )).toEqual(["Fixture saved book"]);
  await expect(page.getByPlaceholder("Load a saved combination")).toHaveValue("");
  await expectFixtureCopies(5);
  await page.getByPlaceholder("Load a saved combination").click();
  await page.getByRole("option", { name: "Fixture saved book", exact: true }).click();
  await page.locator(".wb-saved-combinations").getByRole("button", { name: "Delete", exact: true }).click();
  await expect.poll(() => page.evaluate(() =>
    JSON.parse(localStorage.getItem("quant-collective-combinations-v1") || "[]"),
  )).toEqual([]);
  await expect(page.getByPlaceholder("No saved combinations")).toHaveValue("");
  await page.reload();
  await page.getByTestId("selected-count").filter({ hasText: "1 book" }).waitFor();
  await expect(page.getByPlaceholder("No saved combinations")).toHaveValue("");
  const followCommonStart = page.getByRole("switch", { name: /Follow common start/ });
  await followCommonStart.check();
  await expect(page.getByRole("textbox", { name: "P&L start" })).toHaveValue("2026-01-05");
  await page.getByRole("textbox", { name: "P&L start" }).fill("2026-01-04");
  await expect(followCommonStart).not.toBeChecked();
  await page.reload();
  await page.getByTestId("selected-count").filter({ hasText: "1 book" }).waitFor();
  await expect(page.getByRole("textbox", { name: "P&L start" })).toHaveValue("2026-01-04");
  await expect(page.getByRole("switch", { name: /Follow common start/ })).not.toBeChecked();
  await page.getByRole("switch", { name: /Follow common start/ }).check();
  await expect(page.getByRole("textbox", { name: "P&L start" })).toHaveValue("2026-01-05");

  // Exercise the research-to-portfolio stages without creating production runs.
  const strategy = state.strategies.find(candidate => candidate.id === "moving-average");
  const fixtureRun = (id, lookback, overrides = {}) => ({
    id, created_at: "2026-09-30", status: "Succeeded", tags: "", notes: "",
    input: { strategy, source_hash: strategy.file_hash, dataset: state.datasets[0], timeframe: "1h", session: "full-trading-day",
      parameters: { lookback }, start: "2026-01-05", end: "2026-01-06", capital: 100000, fee: 1, slippage: 1, stage: "Exploratory" },
    result: { warnings: [], artifacts: [], equity_preview: [], trade_preview: [], metrics: { net_pnl: 100, net_return: .001, max_drawdown: -.0001, trades: 40,
      monthly: [], first: "2026-01-05", last: "2026-01-06", observations: 2, costs: 2, underwater_bars: 0, current_underwater_bars: 0, basis: "Synthetic fixture" } }, ...overrides,
  });
  const passed = fixtureRun("passed", 20);
  passed.input.research = { scenario: "Baseline", role: "Test" };
  const researchRuns = [passed, fixtureRun("development", 30), fixtureRun("queued", 40, { status: "Queued", result: undefined }),
    fixtureRun("evaluating", 50), fixtureRun("failed", 60, { tags: "checks-failed" }),
    fixtureRun("old", 70, { input: { ...passed.input, strategy: { ...strategy, file_hash: "old-source" }, source_hash: "old-source", parameters: { lookback: 70 }, research: undefined } })];
  const researchState = { ...state, runs: researchRuns, evaluations: [
    { id: "passing-evaluation", created_at: "2026-09-30", status: "Succeeded", folds: [{ training: [], tests: ["passed"] }], scenarios: ["Baseline"],
      result: { scenarios: [{ name: "Baseline", outcome: "Meets criteria", metrics: passed.result.metrics }] } },
    { id: "active-evaluation", created_at: "2026-09-30", status: "Summarizing", folds: [{ training: [], tests: ["evaluating"] }], jobs: 1, scenarios: ["Baseline"] },
  ] };
  const template = JSON.parse(await (await fetch(`http://127.0.0.1:${apiPort}/api/workbench/collective`)).text()).items[0];
  const catalogFixture = { version: 1, generated_at: "2026-09-30", errors: [], definitions: {}, items:
    researchRuns.filter(run => !["queued", "evaluating"].includes(run.id)).map(run => ({
      ...template, id: run.id, key: `${strategy.id}__FIXTURE`, name: `Stage ${run.id}`, parameters: run.input.parameters,
      source_run_ids: [run.id], working: false, feasible: false, trades: 40, net_pnl: 100,
    })) };
  fixtureDb = new DatabaseSync(join(home, "workbench.sqlite3"));
  const fixtureRecords = createRecordRepository(fixtureDb);
  fixtureRecords.put("run", passed.id, passed);
  fixtureRecords.put("evaluation", "passing-evaluation", researchState.evaluations[0]);
  const rejectSkip = await fetch(`http://127.0.0.1:${apiPort}/api/workbench/runs/passed/readiness`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phase: "practical", reviewer: "Fixture review" }),
  });
  assert.equal(rejectSkip.status, 400, "The server must reject skipped readiness stages");
  await page.route("**/api/workbench/state?view=summary", async route => {
    passed.readiness_reviews = fixtureRecords.get("run", passed.id).readiness_reviews;
    await route.fulfill({ json: researchState });
  });
  await page.route("**/api/workbench/collective", route => route.fulfill({ json: catalogFixture }));
  await page.goto(`${base}/#/portfolio/strategies`);
  await page.reload();
  const picker = page.getByRole("list", { name: "Strategies and exact histories" });
  const tab = page.getByRole("tablist", { name: "Strategy research status" });
  const expandPickerGroup = async () => {
    const group = picker.locator(".strategy-picker-group-head").filter({ hasText: "Moving-average trend" });
    if (await group.getAttribute("aria-expanded") === "false") await group.click();
  };
  await expect(tab).toBeVisible();
  await expect(picker.getByText("Moving-average trend")).toBeVisible();
  await expandPickerGroup();
  const passedRow = picker.locator('[data-history-id="passed"]');
  await passedRow.getByRole("checkbox").check();
  await tab.getByRole("tab", { name: /In progress/ }).click();
  await expandPickerGroup();
  await expect(picker.locator('[data-history-id="development"]')).toBeVisible();
  await expect(page.getByText(/outside this view/)).toBeVisible();
  await tab.getByRole("tab", { name: /Failed/ }).click();
  await expandPickerGroup();
  await expect(picker.locator('[data-history-id="failed"]')).toBeVisible();
  await tab.getByRole("tab", { name: /Passed/ }).click();
  await expandPickerGroup();
  await expect(passedRow.getByRole("checkbox")).toBeChecked();
  const rejectAssessment = await fetch(`http://127.0.0.1:${apiPort}/api/workbench/runs/passed/stage-assessments`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ attemptedStage: 5, outcome: "passed", reviewer: "Fixture reviewer", criteria: ["Operating plan"], findings: "Ready", evidence: ["passed"] }),
  });
  assert.equal(rejectAssessment.status, 400, "Assessments cannot skip readiness stages");
  const acceptedAssessment = await fetch(`http://127.0.0.1:${apiPort}/api/workbench/runs/passed/stage-assessments`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ attemptedStage: 3, outcome: "blocked", reviewer: "Fixture reviewer", criteria: ["Execution evidence required"], findings: "Execution evidence is missing.", evidence: ["passed"] }),
  });
  assert.equal(acceptedAssessment.status, 201, await acceptedAssessment.text());
  assert.equal(fixtureRecords.get("run", passed.id).stage_assessments.length, 1);
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page.goto(`${base}/#/workspace`);
  await expect(page.getByRole("heading", { name: "Research", level: 1 })).toBeVisible();
  await expect(page.getByRole("region", { name: "Selected configuration" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Research tools" })).toBeVisible();
  await page.getByRole("region", { name: "Research configurations" }).getByRole("button").filter({ hasText: "Moving-average trend" }).first().click();
  await expect(page.getByText("1. Backtest")).toBeVisible();
  await expect(page.getByText("5. Practical readiness")).toBeVisible();
  await page.goto(`${base}/#/scripts`);
  await expect(page.getByRole("heading", { name: "Scripts & library", level: 1 })).toBeVisible();
  await page.getByLabel("Search runnable strategies").fill("moving average");
  await expect(page.getByText(/configurations.*failed.*attempts/).first()).toBeVisible();
  await page.goto(`${base}/#/watchlist`);
  await expect(page.getByRole("heading", { name: "Research", level: 1 })).toBeVisible();
  assert.equal(new URL(page.url()).hash, "#/workspace");
  await page.goto(base);
  await expect(page.getByRole("heading", { name: "Combined portfolio", level: 1 })).toBeVisible();
  const screenshots = join(root, "artifacts", "workbench-validation", "strategy-development");
  await mkdir(screenshots, { recursive: true });
  await page.screenshot({ path: join(screenshots, "desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("navigation", { name: "Primary, compact" }).getByRole("link", { name: "Portfolio" })).toBeVisible();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2), false);
  await page.screenshot({ path: join(screenshots, "mobile.png"), fullPage: true });
  await page.getByRole("navigation", { name: "Primary, compact" }).getByRole("link", { name: "Research" }).click();
  await expect(page.getByRole("heading", { name: "Research", level: 1 })).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 900 });

  // Two saved NQ histories for one strategy must remain distinct in the picker,
  // including when a run is also part of a combined imported history.
  const reversal = state.strategies.find(candidate => candidate.id === "short-term-reversal");
  assert(reversal, "The reversal adapter is required for the exact-history fixture");
  const oldId = "312436e7-1111-4111-8111-111111111111";
  const newId = "d43e22d3-2222-4222-8222-222222222222";
  const esId = "eeeeeeee-3333-4333-8333-333333333333";
  const compositeId = "cccccccc-4444-4444-8444-444444444444";
  const oldSource = "archived-reversal-source";
  const reversalRun = ({ id, symbol, start, end, pnl, source, lookback, warnings = [], created = "2026-09-30" }) => ({
    id, created_at: created, status: "Succeeded", tags: "", notes: "",
    input: {
      strategy: { ...reversal, file_hash: source }, source_hash: source,
      dataset: { ...state.datasets[0], id: `fixture-${symbol.toLowerCase()}`, symbol },
      timeframe: "1d", session: "full-trading-day", parameters: { lookback },
      start, end, capital: 100000, fee: 1, slippage: 1, stage: "Exploratory",
    },
    result: {
      warnings, artifacts: [], equity_preview: [], trade_preview: [],
      metrics: { net_pnl: pnl, net_return: pnl / 100000, max_drawdown: -.1324, trades: 302,
        monthly: [], first: start, last: end, observations: 302, costs: 100,
        underwater_bars: 0, current_underwater_bars: 0, basis: "Synthetic fixture" },
    },
  });
  const oldNq = reversalRun({ id: oldId, symbol: "NQ", start: "2010-06-07", end: "2026-09-03",
    pnl: 177625, source: oldSource, lookback: 7, warnings: ["Insufficient warmup for the first signals."] });
  const newNq = reversalRun({ id: newId, symbol: "NQ", start: "2025-01-02", end: "2025-12-31",
    pnl: 18270, source: reversal.file_hash, lookback: 2 });
  newNq.input.research = { role: "Test", scenario: "Baseline" };
  const esRun = reversalRun({ id: esId, symbol: "ES", start: "2025-01-02", end: "2025-12-31",
    pnl: 9500, source: reversal.file_hash, lookback: 2 });
  const combinedPart = reversalRun({ id: compositeId, symbol: "NQ", start: "2026-01-02", end: "2026-09-03",
    pnl: 1200, source: oldSource, lookback: 7, created: "2026-01-01" });
  for (const run of [oldNq, newNq, esRun, combinedPart]) fixtureRecords.put("run", run.id, run);
  const exactState = { ...state, runs: [oldNq, newNq, esRun, combinedPart], evaluations: [{
    id: "reversal-execution-evaluation", created_at: "2026-09-30", status: "Succeeded",
    folds: [{ training: [], tests: [newId] }], scenarios: ["Baseline", "Delayed execution"], min_return: .01,
    result: { scenarios: [
      { name: "Baseline", outcome: "Meets criteria", metrics: newNq.result.metrics },
      { name: "Delayed execution", outcome: "Misses criteria",
        metrics: { ...newNq.result.metrics, net_pnl: -250, net_return: -.0025 } },
    ] },
  }] };
  const historyItem = (run, id, sourceIds = [run.id]) => ({
    ...template, id, key: `${reversal.id}__${run.input.dataset.symbol}__1d__full-trading-day`,
    name: reversal.name, symbol: run.input.dataset.symbol, timeframe: "1d", session: "full-trading-day",
    start: run.input.start, end: run.input.end, coverage: [{ start: run.input.start, end: run.input.end }],
    capital: 100000, working: false, feasible: false, tested: true, benchmark: false,
    parameters: run.input.parameters, source_run_ids: sourceIds, source: "Synthetic exact-run fixture",
    net_pnl: run.result.metrics.net_pnl, recent_pnl: run.result.metrics.net_pnl,
    max_drawdown: id === "catalog-es" ? null : id === "catalog-old-nq" ? -.08 : id === "catalog-new-nq" ? -.05 : -.1,
    max_drawdown_dollars: id === "catalog-es" ? null : id === "catalog-old-nq" ? 8000 : id === "catalog-new-nq" ? 5000 : 10000,
    trades: run.result.metrics.trades, chart_points: [0, run.result.metrics.net_pnl],
  });
  const oldHistory = historyItem(oldNq, "catalog-old-nq");
  const newHistory = historyItem(newNq, "catalog-new-nq");
  const esHistory = historyItem(esRun, "catalog-es");
  const compositeHistory = { ...historyItem(oldNq, "catalog-composite-nq", [oldId, compositeId]),
    max_drawdown: -.2, max_drawdown_dollars: 20000 };
  let exactCatalog = { version: 1, generated_at: "2026-09-30", errors: [], definitions: {},
    items: [newHistory, oldHistory, esHistory] };
  let importFails = false;
  let holdImport = false;
  let releaseImport;
  let riskPending = true;
  let riskRequests = 0;
  const importedRuns = [];
  const exactPage = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  exactPage.on("pageerror", error => pageErrors.push(error.message));
  let exactSelection = [];
  await exactPage.route("**/api/workbench/collective/tracking", async route => {
    if (route.request().method() === "PUT") exactSelection = route.request().postDataJSON().ids;
    await route.fulfill({ json: { selection: exactSelection,
      items: Object.fromEntries(exactSelection.map(id => [id, { status: "manual-update-required",
        simulated_through: exactCatalog.items.find(item => item.id === id)?.end || "" }])) } });
  });
  await exactPage.route("**/api/workbench/state?view=summary", route => route.fulfill({ json: exactState }));
  await exactPage.route("**/api/workbench/collective", route => route.fulfill({ json: exactCatalog }));
  await exactPage.route("**/api/workbench/collective/risk", async route => {
    riskRequests += 1;
    const { runIds = [] } = route.request().postDataJSON();
    await route.fulfill({ json: {
      ready: riskPending ? {} : Object.fromEntries(runIds.map(id => [id, {
        max_drawdown: -.1, max_drawdown_dollars: 10000,
        net_pnl: exactState.runs.find(run => run.id === id)?.result?.metrics.net_pnl || 0,
      }])),
      pending: riskPending ? runIds : [], errors: {},
    } });
  });
  await exactPage.route("**/api/workbench/collective/series", async route => {
    const { ids } = route.request().postDataJSON();
    await route.fulfill({ json: ids.map(id => {
      const item = exactCatalog.items.find(candidate => candidate.id === id);
      return { id, daily: [{ date: item.start, pnl: item.net_pnl, terminal: true }], trades: [], coverage: item.coverage };
    }) });
  });
  await exactPage.route("**/api/workbench/collective/import", async route => {
    const { runId } = route.request().postDataJSON();
    importedRuns.push(runId);
    if (importFails === "response")
      await route.fulfill({ json: { running: false, error: "Synthetic exact-run response rejected." } });
    else if (importFails) await route.fulfill({ status: 500, json: { error: "Synthetic exact-run import failed." } });
    else {
      if (holdImport) await new Promise(resolve => { releaseImport = resolve; });
      exactCatalog = { ...exactCatalog, items: [...exactCatalog.items, oldHistory] };
      await route.fulfill({ json: { running: false, error: "" } });
    }
  });
  await exactPage.route("**/api/workbench/collective/status", route => route.fulfill({ json: { running: false, error: "", evidence_error: "" } }));
  const selectedExactIds = () => exactPage.evaluate(() => Object.entries(
    JSON.parse(localStorage.getItem("quant-collective-v1") || "{}").copies || {},
  ).filter(([, count]) => count > 0).map(([id]) => id).sort());
  await exactPage.goto(`${base}/#/portfolio`);
  await exactPage.getByRole("button", { name: "Add", exact: true }).first().click();
  const exactPicker = exactPage.getByRole("list", { name: "Strategies and exact histories" });
  await exactPage.getByRole("tab", { name: /^All \(/ }).click();
  const reversalGroup = exactPicker.locator('[data-strategy-id="short-term-reversal"]');
  await expect(reversalGroup.locator(".strategy-picker-group-head")).toContainText("Calculating best run");
  riskPending = false;
  const reversalPreview = reversalGroup.locator(".strategy-picker-group-preview");
  await expect(reversalPreview).toContainText(/Best run.*NQ.*1d/, { timeout: 15000 });
  await expect(reversalPreview).toContainText("$177,625");
  await expect(reversalPreview).toContainText("8.00%");
  await expect(reversalPreview).toContainText("302");
  await expect(reversalPreview).toContainText("22.20");
  for (const label of ["Net P&L", "Drawdown", "Trades", "Return/DD"])
    await expect(reversalPreview).toContainText(label);
  const bestPnl = reversalPreview.locator(".strategy-picker-preview-metric")
    .filter({ hasText: "Net P&L" }).locator("strong");
  const bestPnlColor = await bestPnl.evaluate(element => getComputedStyle(element).color);
  const bestPnlRgb = bestPnlColor.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/)?.slice(1).map(Number);
  assert(bestPnlRgb && bestPnlRgb[1] > bestPnlRgb[0] && bestPnlRgb[1] > bestPnlRgb[2],
    `Positive best-run P&L should resolve to teal or green, received ${bestPnlColor}`);
  for (const detail of ["Retest required", "2010-06-07", "2026-09-03", "run warning", "research note"])
    await expect(reversalPreview).not.toContainText(detail);
  const emptyStrategyGroup = exactPicker.locator('[data-strategy-id="moving-average"]');
  await expect(emptyStrategyGroup.locator(".strategy-picker-group-head")).toContainText("No saved history");
  await expect(emptyStrategyGroup.locator(".strategy-picker-group-head")).not.toContainText("No market");
  await expect(emptyStrategyGroup.locator(".strategy-picker-group-count")).toHaveCount(0);
  assert(riskRequests >= 2, "The picker must resolve pending daily risk before ranking histories");
  await exactPage.screenshot({ path: join(screenshots, "exact-histories-collapsed-desktop.png"), fullPage: true });
  await exactPage.setViewportSize({ width: 390, height: 844 });
  await expect(reversalGroup.locator(".strategy-picker-group-preview")).toBeVisible();
  assert.equal(await exactPage.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2), false);
  await exactPage.screenshot({ path: join(screenshots, "exact-histories-collapsed-mobile.png"), fullPage: true });
  await exactPage.setViewportSize({ width: 1280, height: 900 });
  const addBest = reversalGroup.getByRole("button", { name: `Add best run for ${reversal.name}` });
  await addBest.click();
  await expect.poll(selectedExactIds).toEqual(["catalog-old-nq"]);
  await expect(reversalGroup.getByRole("button", { name: `Best run already added for ${reversal.name}` })).toBeDisabled();
  await exactPage.getByRole("tab", { name: /^Failed \(/ }).click();
  await expect(reversalPreview).toContainText("$18,270");
  await expect(reversalPreview).toContainText(/Best run.*NQ.*1d/);
  await expect(reversalPreview).not.toContainText("Failed checks");
  await addBest.click();
  await expect.poll(selectedExactIds).toEqual(["catalog-new-nq"]);
  await exactPage.getByRole("tab", { name: /^All \(/ }).click();
  await addBest.click();
  await expect.poll(selectedExactIds).toEqual(["catalog-old-nq"]);
  await exactPage.getByLabel("Find a strategy").fill(newId);
  if (await reversalGroup.locator(".strategy-picker-group-head").getAttribute("aria-expanded") === "true")
    await reversalGroup.locator(".strategy-picker-group-head").click();
  await expect(reversalPreview).toContainText("$18,270");
  await exactPage.getByLabel("Find a strategy").clear();
  await expect(reversalPreview).toContainText("$177,625");
  await exactPage.getByLabel("Find a strategy").fill(esId);
  await expect(reversalPreview).toContainText("Unscored");
  await expect(reversalPreview).toContainText(/ES.*1d/);
  await exactPage.getByLabel("Find a strategy").clear();
  await expect(reversalPreview).toContainText("$177,625");
  await reversalGroup.locator(".strategy-picker-group-head").click();
  const oldRow = reversalGroup.locator('[data-history-id="catalog-old-nq"]');
  const newRow = reversalGroup.locator('[data-history-id="catalog-new-nq"]');
  const esRow = reversalGroup.locator('[data-history-id="catalog-es"]');
  await expect(oldRow).toBeVisible();
  await expect(newRow).toBeVisible();
  await expect(esRow).toBeVisible();
  await expect(oldRow).toContainText("$177,625.00");
  await expect(newRow).toContainText("$18,270.00");
  await expect(oldRow).toContainText("2010-06-07");
  await expect(oldRow).toContainText("2026-09-03");
  await expect(newRow).toContainText("2025-01-02");
  await expect(newRow).toContainText("2025-12-31");
  await expect(oldRow).toContainText("Retest required");
  await expect(newRow).toContainText("Failed checks");
  await expect(oldRow).toContainText("Starting capital $100,000.00");
  await expect(oldRow).not.toContainText(oldId);
  await expect(newRow).not.toContainText(newId);
  await expect(oldRow).toContainText("Source");
  await expect(newRow).toContainText("Source");
  await expect(oldRow).toContainText("8.00%");
  await expect(newRow).toContainText("5.00%");
  await expect(oldRow).toContainText("22.20");
  await expect(oldRow).toContainText("Daily max drawdown");
  await expect(oldRow).toContainText("P&L ÷ drawdown");
  await expect(oldRow).not.toContainText("run return");
  await expect(oldRow.locator(".strategy-picker-option-result")).toHaveCSS("text-align", "center");
  await expect(exactPicker.locator(".strategy-picker-chart")).toHaveCount(0);
  await expect(oldRow.getByRole("link", { name: "Inspect run" })).toHaveAttribute("href", new RegExp(oldId));
  await oldRow.locator("summary").click();
  await expect(oldRow).toContainText("Insufficient warmup for the first signals.");
  await expect(oldRow).toContainText('"lookback": 7');
  await expect(oldRow).toContainText("Research status: The tested execution source differs");
  await expect(oldRow).toContainText("Saved history note:");
  await newRow.locator("summary").click();
  await expect(newRow).toContainText("Delayed execution: Misses criteria");
  await exactPage.screenshot({ path: join(screenshots, "exact-histories-desktop.png"), fullPage: true });
  await exactPage.setViewportSize({ width: 390, height: 844 });
  await expect(oldRow.locator(".strategy-picker-option-result")).toHaveCSS("text-align", "center");
  assert.equal(await exactPage.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2), false);
  await exactPage.screenshot({ path: join(screenshots, "exact-histories-mobile.png"), fullPage: true });
  await exactPage.setViewportSize({ width: 1280, height: 900 });

  await newRow.getByRole("checkbox").check();
  await expect.poll(selectedExactIds).toEqual(["catalog-new-nq"]);
  await exactPage.getByRole("button", { name: "Add shown (1)" }).click();
  await expect.poll(selectedExactIds).toEqual(["catalog-es", "catalog-new-nq"]);
  await expect(exactPage.getByRole("button", { name: "Add shown (0)" })).toBeDisabled();
  await oldRow.getByRole("checkbox").check();
  await expect.poll(selectedExactIds).toEqual(["catalog-es", "catalog-old-nq"]);
  await exactPage.getByRole("button", { name: "Done", exact: true }).click();
  await expect(exactPage.getByTestId("selected-count")).toHaveText("2 books");
  const selectedRows = exactPage.getByTestId("selected-strategies").locator("li");
  await expect(selectedRows).toHaveCount(2);
  await expect(selectedRows.locator(".wb-book-symbol")).toHaveText(["NQ", "ES"]);
  for (const row of await selectedRows.all()) {
    await expect(row.locator(".wb-book-name")).toContainText(reversal.name);
    await expect(row.locator(".wb-book-performance span")).toHaveText([/P&L/, /Drawdown/]);
    await expect(row.getByRole("button", { name: /^Remove / })).toHaveCount(1);
    await expect(row.locator("button")).toHaveCount(1);
    await expect(row.locator("a, input, details")).toHaveCount(0);
  }
  await expect(exactPage.getByTestId("selected-strategies")).not.toContainText("2010-06-07");
  await expect(exactPage.getByTestId("selected-strategies")).not.toContainText(oldId);

  await exactPage.goto(`${base}/#/runs`);
  await exactPage.getByLabel("Search runs").fill(oldId);
  await exactPage.getByRole("region", { name: "Run ledger" }).getByRole("button", { name: "Add this run" }).click();
  await expect(exactPage.getByRole("tab", { name: /^All \(/ })).toHaveAttribute("aria-selected", "true");
  await expect(exactPage.getByRole("list", { name: "Strategies and exact histories" }).locator('[data-history-id="catalog-old-nq"]')).toBeVisible();
  await expect.poll(selectedExactIds).toEqual(["catalog-es", "catalog-old-nq"]);
  assert.deepEqual(importedRuns, [], "An exact single-run catalog history must be reused");

  // Replacing the single-run catalog entry with a combined history must force
  // the import endpoint to create a new exact choice for the requested run.
  exactCatalog = { ...exactCatalog, items: [newHistory, esHistory, compositeHistory] };
  await exactPage.reload();
  await exactPage.getByRole("button", { name: "Add", exact: true }).first().click();
  await exactPage.getByRole("tab", { name: /^All \(/ }).click();
  const compositeGroup = exactPage.getByRole("list", { name: "Strategies and exact histories" }).locator('[data-strategy-id="short-term-reversal"]');
  await compositeGroup.locator(".strategy-picker-group-head").click();
  const combinedRow = compositeGroup.locator('[data-history-id="catalog-composite-nq"]');
  await expect(combinedRow).toContainText("Combined history");
  await expect(combinedRow).not.toContainText(oldId);
  await combinedRow.getByText("Inspect source runs (2)").click();
  await expect(combinedRow.getByRole("link", { name: "Run 1" })).toHaveAttribute("href", new RegExp(oldId));
  await compositeGroup.locator('[data-history-id="catalog-new-nq"]').getByRole("checkbox").check();
  await expect.poll(selectedExactIds).toEqual(["catalog-es", "catalog-new-nq"]);
  await compositeGroup.locator(".strategy-picker-group-head").click();
  await exactPage.getByLabel("Find a strategy").fill(oldId);
  await expect(compositeGroup.locator(".strategy-picker-group-preview")).toHaveAttribute("data-preview-run-id", oldId);
  holdImport = true;
  await compositeGroup.getByRole("button", { name: `Add best run for ${reversal.name}` }).click();
  await expect.poll(() => importedRuns.length).toBe(1);
  await expect.poll(selectedExactIds).toEqual(["catalog-es", "catalog-new-nq"]);
  releaseImport();
  holdImport = false;
  await expect.poll(selectedExactIds, { timeout: 10000 }).toEqual(["catalog-es", "catalog-old-nq"]);
  await expect(compositeGroup.getByRole("button", { name: `Best run already added for ${reversal.name}` })).toBeDisabled();
  await exactPage.getByLabel("Find a strategy").clear();
  await compositeGroup.locator(".strategy-picker-group-head").click();
  await expect(compositeGroup.locator('[data-history-id="catalog-old-nq"]')).toBeVisible();
  assert.deepEqual(importedRuns, [oldId], "The combined history must not stand in for its source run");
  await exactPage.getByRole("button", { name: "Done", exact: true }).click();
  await exactPage.goto(`${base}/#/runs`);
  await exactPage.getByLabel("Search runs").fill(oldId);
  await exactPage.getByRole("region", { name: "Run ledger" }).getByRole("button", { name: "Add this run" }).click();
  await expect(exactPage.getByRole("tab", { name: /^All \(/ })).toHaveAttribute("aria-selected", "true");
  await expect.poll(selectedExactIds, { timeout: 10000 }).toEqual(["catalog-es", "catalog-old-nq"]);
  assert.deepEqual(importedRuns, [oldId], "A direct run action must reuse the imported exact history");

  exactCatalog = { ...exactCatalog, items: [newHistory, esHistory, compositeHistory] };
  importFails = true;
  await exactPage.reload();
  await exactPage.getByRole("button", { name: "Add", exact: true }).first().click();
  await exactPage.getByRole("tab", { name: /^All \(/ }).click();
  const failedImportGroup = exactPage.getByRole("list", { name: "Strategies and exact histories" }).locator('[data-strategy-id="short-term-reversal"]');
  await failedImportGroup.locator(".strategy-picker-group-head").click();
  await failedImportGroup.locator('[data-history-id="catalog-new-nq"]').getByRole("checkbox").check();
  await expect.poll(selectedExactIds).toEqual(["catalog-es", "catalog-new-nq"]);
  await failedImportGroup.locator(".strategy-picker-group-head").click();
  await exactPage.getByLabel("Find a strategy").fill(oldId);
  await expect(failedImportGroup.locator(".strategy-picker-group-preview")).toHaveAttribute("data-preview-run-id", oldId);
  await failedImportGroup.getByRole("button", { name: `Add best run for ${reversal.name}` }).click();
  await expect(exactPage.locator(".collective-picker:visible").getByRole("alert")
    .filter({ hasText: "Synthetic exact-run import failed." }).first()).toBeVisible();
  await expect.poll(selectedExactIds).toEqual(["catalog-es", "catalog-new-nq"]);
  await expect(failedImportGroup.getByRole("button", { name: `Add best run for ${reversal.name}` })).toBeEnabled();
  await exactPage.getByRole("button", { name: "Done", exact: true }).click();
  await exactPage.goto(`${base}/#/runs`);
  await exactPage.getByLabel("Search runs").fill(oldId);
  await exactPage.getByRole("region", { name: "Run ledger" }).getByRole("button", { name: "Add this run" }).click();
  await expect(exactPage.locator(".collective-picker:visible").getByRole("alert")
    .filter({ hasText: "Synthetic exact-run import failed." }).first()).toBeVisible();
  await expect.poll(selectedExactIds).toEqual(["catalog-es", "catalog-new-nq"]);
  importFails = "response";
  const responseErrorRow = exactPage.getByRole("list", { name: "Strategies and exact histories" })
    .locator(`[data-run-id="${oldId}"]:not([data-history-id])`);
  await responseErrorRow.getByRole("button", { name: "Import exact run" }).click();
  await expect(responseErrorRow.getByRole("alert")).toContainText("Synthetic exact-run response rejected.");
  await expect.poll(selectedExactIds).toEqual(["catalog-es", "catalog-new-nq"]);
  assert.deepEqual(importedRuns, [oldId, oldId, oldId, oldId]);
  await exactPage.close();

  // The period selector changes P&L and risk metrics while preserving the
  // full verified calculation window. Dated trades reconcile to daily marks.
  const periodPage = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  periodPage.on("pageerror", (error) => pageErrors.push(error.message));
  await periodPage.addInitScript(() => {
    localStorage.setItem("quant-collective-v1", JSON.stringify({
      capital: 100000,
      copies: { "period-fixture-configuration": 1 },
      start: "2025-07-01",
      end: "2026-09-30",
      followLatest: false,
      basis: "marked",
      policy: { enabled: false },
    }));
  });
  await periodPage.goto(`${base}/#/portfolio`);
  const periodKpi = periodPage.getByTestId("portfolio-metrics").locator(".wb-kpi.lead");
  const periodValue = periodPage.getByTestId("portfolio-pnl");
  const periodRanges = periodPage.getByRole("group", { name: "P&L period" });
  const metricValue = label => periodPage.getByTestId("portfolio-metrics").locator(".wb-kpi")
    .filter({ has: periodPage.getByText(label, { exact: true }) }).locator(".wb-kpi-value");
  const drawdownValue = metricValue("Maximum drawdown");
  const scoreValue = metricValue("Combination score");
  const profitFactorValue = metricValue("Profit factor");
  const expectPeriodMetrics = async ({ range, pnl, drawdown, score, profitFactor }) => {
    await expect(periodKpi.locator(".wb-kpi-label")).toHaveText(`Combined net P&L · ${range}`);
    await expect(periodValue).toHaveText(pnl);
    await expect(drawdownValue).toHaveText(drawdown);
    await expect(scoreValue).toHaveText(score);
    await expect(profitFactorValue).toHaveText(profitFactor);
  };
  const periodCases = [
    { range: "All time", pnl: "$119.00", drawdown: "$50.00", score: "2.38", profitFactor: "2.65", contributionReturn: "0.12%", trades: "10" },
    { range: "1 year", pnl: "$19.00", drawdown: "$20.00", score: "0.95", profitFactor: "1.45", contributionReturn: "0.02%", trades: "8" },
    { range: "YTD", pnl: "$39.00", drawdown: "$12.00", score: "3.25", profitFactor: "2.77", contributionReturn: "0.04%", trades: "7" },
    { range: "6 months", pnl: "$9.00", drawdown: "$10.00", score: "0.90", profitFactor: "1.90", contributionReturn: "0.01%", trades: "4" },
    { range: "1 month", pnl: "-$1.00", drawdown: "$4.00", score: "-0.25", profitFactor: "0.75", contributionReturn: "-0.00%", trades: "2" },
  ];
  await expectPeriodMetrics(periodCases[0]);
  for (const entry of [...periodCases.slice(1), periodCases[0]]) {
    const { range } = entry;
    await periodRanges.getByRole("button", { name: range, exact: true }).click();
    await expectPeriodMetrics(entry);
  }
  await periodRanges.getByRole("button", { name: "6 months", exact: true }).click();
  await expectPeriodMetrics(periodCases[3]);
  await periodPage.getByRole("link", { name: "Contributions", exact: true }).click();
  const contributionRanges = periodPage.getByRole("group", { name: "P&L period" });
  const contributionRows = periodPage.getByTestId("strategy-contributions").locator("tbody tr");
  const expectContributionPeriod = async ({ range, pnl, drawdown, contributionReturn, trades }) => {
    await expect(contributionRanges.getByRole("button", { name: range, exact: true }))
      .toHaveAttribute("aria-pressed", "true");
    await expect(contributionRows).toHaveCount(1);
    const cells = contributionRows.first().locator("td");
    await expect(cells.nth(2)).toHaveText(pnl);
    await expect(cells.nth(3)).toHaveText(drawdown);
    await expect(cells.nth(4)).toHaveText(contributionReturn);
    await expect(cells.nth(5)).toHaveText(pnl);
    await expect(cells.nth(6)).toHaveText(trades);
    await expect(cells.nth(7)).toHaveText("0");
  };
  await expect(contributionRanges.getByRole("button")).toHaveCount(periodCases.length);
  await expectContributionPeriod(periodCases[3]);
  for (const entry of [periodCases[4], periodCases[2], periodCases[1], periodCases[0]]) {
    await contributionRanges.getByRole("button", { name: entry.range, exact: true }).click();
    await expectContributionPeriod(entry);
  }
  await contributionRanges.getByRole("button", { name: "1 month", exact: true }).click();
  await expectContributionPeriod(periodCases[4]);
  await periodPage.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(periodRanges.getByRole("button", { name: "1 month", exact: true }))
    .toHaveAttribute("aria-pressed", "true");
  await expectPeriodMetrics(periodCases[4]);
  await expect(periodPage.getByRole("textbox", { name: "P&L start" })).toHaveValue("2025-07-01");
  await expect(periodPage.getByRole("textbox", { name: "P&L end" })).toHaveValue("2026-09-30");
  await periodPage.close();

  assert.deepEqual(pageErrors, []);
  console.log(
    `Fixture browser smoke passed: ${routes.length} routed views, synced Overview and Contributions period ranges, saved combination reload, exact-history picker and run import, development stages across research and portfolio, unfinished and failed evidence, mobile layout, isolated state, ${state.strategies.length} adapters (17 tracked baseline), 171 library entries and 21 Pine sources.`,
  );
} finally {
  if (fixtureDb) fixtureDb.close();
  if (browser) await browser.close();
  if (web) await new Promise((resolveDone) => web.close(resolveDone));
  await stopChild(api);
  await rm(home, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
