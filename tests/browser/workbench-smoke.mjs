import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { createReadStream, existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { request as httpRequest } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, normalize, resolve } from "node:path";
import { chromium } from "@playwright/test";

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
          headers: request.headers,
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
  assert.deepEqual(
    trackedStrategies.map((strategy) => strategy.id).sort(),
    baselineStrategyIds.sort(),
  );
  const trackedLibrary = state.library.entries.filter((entry) =>
    trackedPaths.has(entry.path),
  );
  assert.equal(trackedLibrary.length, 171);
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
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const routes = [
    { route: "portfolio", heading: "Combined portfolio", activeTab: "Overview" },
    { route: "portfolio/calendar", heading: "Combined portfolio", activeTab: "Calendar" },
    { route: "portfolio/contributions", heading: "Combined portfolio", activeTab: "Contributions" },
    { route: "portfolio/pause", heading: "Combined portfolio", activeTab: "Pause & sizing" },
    { route: "workspace", heading: "Research workspace" },
    { route: "scorecards", heading: "Strategy scorecards" },
    { route: "runs", heading: "Runs & compare" },
    { route: "runs/nq-monthly", heading: "Runs & compare", activeTab: "NQ monthly" },
    { route: "runs/experiments", heading: "Runs & compare", activeTab: "Experiments" },
    { route: "new-run", heading: "New run" },
    { route: "evaluations", heading: "Evaluations & regimes" },
    { route: "event-studies", heading: "Pattern event studies" },
    { route: "watchlist", heading: "Watchlist" },
    { route: "scripts", heading: "Scripts & library", activeTab: "Runnable scripts" },
    { route: "scripts/library", heading: "Scripts & library", activeTab: "Library" },
    { route: "datasets", heading: "Datasets" },
  ];
  await page.goto(`${base}/#/${routes[0].route}`);
  for (let index = 0; index < routes.length; index += 1) {
    const { route, heading, activeTab } = routes[index];
    if (index > 0) {
      await page.evaluate((nextRoute) => {
        window.location.hash = `#/${nextRoute}`;
      }, route);
    }
    await page.getByRole("heading", { name: heading, level: 1 }).waitFor();
    if (activeTab) {
      const tab = page.getByRole("link", { name: activeTab, exact: true });
      await tab.waitFor();
      assert.equal(await tab.getAttribute("aria-current"), "page", route);
    }
    if (route === "portfolio")
      await page.getByText("Collective evidence", { exact: true }).waitFor();
  }
  await page.evaluate(() => {
    window.location.hash = "#/portfolio";
  });
  await page.getByRole("heading", { name: "Combined portfolio", level: 1 }).waitFor();
  await page.getByTestId("selected-count").filter({ hasText: "1 book" }).waitFor();
  const copies = page.getByLabel(/Copies of Fixture strategy FIXTURE 1h/);
  await copies.fill("3");
  await page.getByPlaceholder("Name this combination").fill("Fixture saved book");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByLabel(/Remove Fixture strategy FIXTURE 1h/).click();
  await page.getByTestId("selected-count").filter({ hasText: "0 books" }).waitFor();
  await page.reload();
  await page.getByRole("heading", { name: "Combined portfolio", level: 1 }).waitFor();
  await page.getByTestId("selected-count").filter({ hasText: "0 books" }).waitFor();
  await page.getByPlaceholder("Load a saved combination").click();
  await page.getByRole("option", { name: "Fixture saved book", exact: true }).click();
  await page.getByTestId("selected-count").filter({ hasText: "1 book" }).waitFor();
  assert.equal(await page.getByLabel(/Copies of Fixture strategy FIXTURE 1h/).inputValue(), "3");
  const savedBooks = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("quant-collective-combinations-v1") || "[]"),
  );
  assert.equal(savedBooks[0].name, "Fixture saved book");
  assert.equal(savedBooks[0].settings.copies["fixture-configuration"], 3);
  await page.getByText("FIXTURE", { exact: true }).first().waitFor();
  assert.deepEqual(pageErrors, []);
  console.log(
    `Fixture browser smoke passed: ${routes.length} routed views, saved combination reload, isolated state, ${state.strategies.length} adapters (17 tracked baseline), 171 library entries and 21 Pine sources.`,
  );
} finally {
  if (browser) await browser.close();
  if (web) await new Promise((resolveDone) => web.close(resolveDone));
  await stopChild(api);
  await rm(home, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
