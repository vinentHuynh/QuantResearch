import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createReadStream, existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer, request as httpRequest } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, normalize, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { chromium, expect } from "@playwright/test";
import { createRecordRepository } from "../../server/infra/recordRepository.ts";

// A standalone fixture: all writes, archive records and artifacts live in a
// temporary WORKBENCH_HOME. Build the application before running this file.
const root = resolve(".");
const dist = join(root, "dist");
assert(existsSync(join(dist, "index.html")), "Run npm run build first.");
const home = await mkdtemp(join(tmpdir(), "strategy-workbench-archive-"));
const artifacts = join(home, "artifacts");
await mkdir(artifacts, { recursive: true });
const delay = milliseconds => new Promise(resolveDone => setTimeout(resolveDone, milliseconds));
async function listen(server) {
  await new Promise((resolveDone, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveDone);
  });
  return server.address().port;
}
const probe = createServer();
const apiPort = await listen(probe);
await new Promise(resolveDone => probe.close(resolveDone));
const apiBase = `http://127.0.0.1:${apiPort}/api/workbench`;
let api;
let apiLog = "";
let web;
let browser;
let database;
async function stopApi() {
  if (!api || api.exitCode !== null) return;
  const exited = new Promise(resolveDone => api.once("exit", resolveDone));
  api.kill("SIGTERM");
  await Promise.race([exited, delay(5_000)]);
  if (api.exitCode === null) {
    api.kill("SIGKILL");
    await exited;
  }
}
async function startApi() {
  api = spawn(process.execPath, ["server/workbench.ts"], {
    cwd: root,
    env: { ...process.env, WORKBENCH_HOME: home, WORKBENCH_ARTIFACTS: artifacts,
      WORKBENCH_PORT: String(apiPort), WORKBENCH_CONCURRENCY: "1", PYTHONDONTWRITEBYTECODE: "1" },
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const capture = chunk => { apiLog = (apiLog + chunk).slice(-20_000); };
  api.stdout.on("data", capture);
  api.stderr.on("data", capture);
  for (let attempt = 0; attempt < 150; attempt += 1) {
    if (api.exitCode !== null) throw new Error(`Fixture API exited:\n${apiLog}`);
    try {
      const response = await fetch(`${apiBase}/state`);
      if (response.ok) return await response.json();
    } catch { /* The isolated listener is not ready yet. */ }
    await delay(100);
  }
  throw new Error(`Fixture API startup timed out:\n${apiLog}`);
}
async function stateSummary() {
  const response = await fetch(`${apiBase}/state?view=summary`);
  assert.equal(response.status, 200);
  return { state: await response.json(), etag: response.headers.get("etag") };
}
async function post(path, body, expected = 200) {
  const response = await fetch(`${apiBase}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const payload = await response.json();
  assert.equal(response.status, expected, JSON.stringify(payload));
  return payload;
}
function fixtureWebServer() {
  return createServer((request, response) => {
    if (request.url?.startsWith("/api/workbench")) {
      const upstream = httpRequest({ hostname: "127.0.0.1", port: apiPort,
        path: request.url, method: request.method,
        headers: { ...request.headers, ...(request.headers.origin === `http://${request.headers.host}`
          ? { origin: `http://127.0.0.1:${apiPort}` } : {}) },
      }, upstreamResponse => {
        response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
        upstreamResponse.pipe(response);
      });
      upstream.on("error", error => {
        response.writeHead(502, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ error: error.message }));
      });
      request.pipe(upstream);
      return;
    }
    const pathname = new URL(request.url || "/", "http://fixture.local").pathname;
    const candidate = normalize(join(dist, pathname.replace(/^\/+/, "")));
    const file = pathname !== "/" && candidate.startsWith(dist) && existsSync(candidate)
      ? candidate : join(dist, "index.html");
    const contentType = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".woff2": "font/woff2" }[extname(file)] || "application/octet-stream";
    response.writeHead(200, { "Content-Type": contentType, "Cache-Control": "no-store" });
    createReadStream(file).pipe(response);
  });
}

try {
  const initial = await startApi();
  const strategy = initial.strategies.find(candidate => candidate.id === "moving-average");
  assert(strategy, "The fixture needs the moving-average adapter.");
  database = new DatabaseSync(join(home, "workbench.sqlite3"));
  const records = createRecordRepository(database);
  const fixtureDataset = symbol => ({ id: `archive-fixture-${symbol}`, symbol, source: "Synthetic archive browser fixture",
    rows: 0, first: "2026-01-05T00:00:00Z", last: "2026-01-09T23:59:00Z", currency: "USD", tick_size: .25, point_value: 2 });
  const run = (id, symbol, created_at, end) => ({
    id, created_at, status: "Succeeded", tags: "checks-failed", notes: "Preserve this recorded research finding.",
    input: { strategy, source_hash: strategy.file_hash, dataset: fixtureDataset(symbol), timeframe: "1h", session: "full-trading-day",
      parameters: { lookback: 20 }, start: "2026-01-05", end, capital: 100000, fee: 1, slippage: 1, stage: "Exploratory" },
    result: { warnings: ["Synthetic fixture"], artifacts: ["equity.csv"], equity_preview: [], trade_preview: [],
      metrics: { net_pnl: 100, net_return: .001, max_drawdown: -.0001, trades: 40, monthly: [], first: "2026-01-05", last: end,
        observations: 2, costs: 2, underwater_bars: 0, current_underwater_bars: 0, basis: "Synthetic fixture" } },
  });
  const latest = run("latest-archive-run", "ARCHIVE_A", "2026-09-30T00:00:00Z", "2026-01-06");
  const older = run("earlier-history-run", "ARCHIVE_A", "2026-09-29T00:00:00Z", "2026-01-05");
  const separate = run("separate-config-run", "KEEP_B", "2026-09-30T00:00:00Z", "2026-01-06");
  const runs = [older, latest, separate];
  const artifactBytes = Buffer.from("date,equity\n2026-01-05,100000\n2026-01-06,100100\n");
  for (const item of runs) {
    records.put("run", item.id, item);
    await mkdir(join(home, "runs", item.id), { recursive: true });
    await writeFile(join(home, "runs", item.id, "equity.csv"), artifactBytes);
  }
  const evaluation = { id: "archive-fixture-evaluation", name: "Recorded failed evaluation", created_at: "2026-09-30", status: "Succeeded",
    folds: [{ training: [older.id], tests: [latest.id] }], scenarios: ["Baseline"], jobs: 2,
    result: { scenarios: [{ name: "Baseline", outcome: "Does not meet criteria", metrics: latest.result.metrics }] } };
  records.put("evaluation", evaluation.id, evaluation);
  const preserved = new Map(runs.map(item => [item.id, records.raw("run", item.id)]));
  const evidenceBytes = records.raw("evaluation", evaluation.id);
  const assertRetained = async () => {
    for (const item of runs) {
      assert.equal(records.raw("run", item.id), preserved.get(item.id), "Archiving must preserve raw run records.");
      assert.deepEqual(await readFile(join(home, "runs", item.id, "equity.csv")), artifactBytes);
    }
    assert.equal(records.raw("evaluation", evaluation.id), evidenceBytes, "Archiving must preserve evaluation evidence.");
  };

  const before = await stateSummary();
  assert.equal(before.state.runs.length, 3);
  assert.deepEqual(before.state.research_archive, { runs: [], configurations: [] });
  await post("/runs/archive", { ids: [latest.id, "unknown-fixture-run"] }, 400);
  assert.deepEqual((await stateSummary()).state.research_archive, before.state.research_archive,
    "An invalid batch must not partially archive a valid run.");

  web = fixtureWebServer();
  const webPort = await listen(web);
  const base = `http://127.0.0.1:${webPort}`;
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  const row = id => page.getByRole("region", { name: "Run ledger" }).getByRole("row")
    .filter({ has: page.getByRole("checkbox", { name: `Compare ${id}`, exact: true }) });
  const navigate = async route => {
    await page.goto(`${base}/#/${route}`);
    await page.getByRole("heading", { name: route.startsWith("runs") ? "Runs & compare" : "Research", exact: true, level: 1 }).waitFor();
  };
  await navigate("runs");
  await expect(row(latest.id)).toBeVisible();
  await expect(row(older.id)).toHaveCount(0);
  await row(latest.id).getByRole("button", { name: "Archive", exact: true }).click();
  await expect(row(latest.id)).toHaveCount(0);
  await expect(row(older.id)).toBeVisible();
  await expect(row(separate.id)).toBeVisible();
  const archivedRun = await stateSummary();
  assert.notEqual(archivedRun.etag, before.etag, "Archiving must invalidate the summary ETag.");
  assert.deepEqual(archivedRun.state.research_archive.runs.map(item => item.id), [latest.id]);
  assert.equal(archivedRun.state.runs.length, 3, "Archived runs remain available as evidence in state.");
  await assertRetained();
  await page.reload();
  await expect(row(latest.id)).toHaveCount(0);
  await expect(row(older.id)).toBeVisible();
  await page.getByRole("navigation", { name: "Run views" }).getByRole("link", { name: "Archive", exact: true }).click();
  await expect(row(latest.id)).toBeVisible();
  await expect(row(older.id)).toHaveCount(0);
  await row(latest.id).getByRole("button", { name: "Restore", exact: true }).click();
  await expect(row(latest.id)).toHaveCount(0);
  await navigate("runs");
  await expect(row(latest.id)).toBeVisible();
  await expect(row(older.id)).toHaveCount(0);

  // Compare actions must archive the selected histories and clear stale results.
  await row(latest.id).getByRole("checkbox").check();
  await row(separate.id).getByRole("checkbox").check();
  await page.getByRole("toolbar", { name: "Selected runs" }).getByRole("button", { name: "Compare as run", exact: true }).click();
  await expect(page.getByRole("heading", { name: "As run comparison" })).toBeVisible();
  await page.getByRole("button", { name: "Archive compared runs", exact: true }).click();
  await expect(page.getByRole("heading", { name: "As run comparison" })).toHaveCount(0);
  await expect(row(latest.id)).toHaveCount(0);
  await expect(row(separate.id)).toHaveCount(0);
  await navigate("runs/archive");
  await row(latest.id).getByRole("checkbox").check();
  await row(separate.id).getByRole("checkbox").check();
  await page.getByRole("toolbar", { name: "Selected runs" }).getByRole("button", { name: "Restore selected", exact: true }).click();
  await expect(row(latest.id)).toHaveCount(0);
  await expect(row(separate.id)).toHaveCount(0);

  await navigate("workspace");
  await page.getByLabel("Search research configurations").fill("moving-average");
  const configs = page.getByRole("region", { name: "Research configurations" });
  const targetConfig = configs.getByRole("button").filter({ hasText: "ARCHIVE_A" });
  const separateConfig = configs.getByRole("button").filter({ hasText: "KEEP_B" });
  await targetConfig.click();
  await page.getByRole("button", { name: "Archive configuration", exact: true }).click();
  await expect(targetConfig).toHaveCount(0);
  await expect(separateConfig).toBeVisible();
  const archivedConfig = await stateSummary();
  assert.equal(archivedConfig.state.research_archive.configurations.length, 1);
  assert.equal(archivedConfig.state.research_archive.configurations[0].strategy_id, strategy.id);
  assert.deepEqual(archivedConfig.state.research_archive.runs, [], "Configuration archive must not rewrite per-run choices.");
  assert.equal(archivedConfig.state.runs.length, 3);
  await assertRetained();

  // Persistence includes a real API restart, not just React state or localStorage.
  await stopApi();
  await startApi();
  await page.reload();
  await page.getByLabel("Search research configurations").fill("moving-average");
  await expect(targetConfig).toHaveCount(0);
  await expect(separateConfig).toBeVisible();
  await page.getByRole("navigation", { name: "Research views" }).getByRole("button", { name: "Archive", exact: true }).click();
  await expect(targetConfig).toBeVisible();
  await expect(separateConfig).toHaveCount(0);
  await expect(page.getByText("Attempts and evidence (2)", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Restore configuration", exact: true }).click();
  await expect(targetConfig).toHaveCount(0);
  await page.getByRole("navigation", { name: "Research views" }).getByRole("button", { name: "Active configurations", exact: true }).click();
  await expect(targetConfig).toBeVisible();
  await expect(separateConfig).toBeVisible();
  await assertRetained();
  assert.deepEqual((await stateSummary()).state.research_archive, { runs: [], configurations: [] });
  assert.deepEqual(pageErrors, []);
  console.log("Archive browser fixture passed: row and comparison archive, fallback history, bulk restore, configuration archive/restore, API restart persistence, summary ETags, atomic invalid batch, unchanged research evidence and artifacts.");
} finally {
  if (browser) await browser.close();
  if (web) await new Promise(resolveDone => web.close(resolveDone));
  await stopApi();
  if (database) database.close();
  await rm(home, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
