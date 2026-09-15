import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, writeFile, readFile, unlink, copyFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { resolve, join } from "node:path";

const root = resolve(".");
const home = join(root, "data", `wbtest-${randomUUID().slice(0, 8)}`);
const python = resolve(
  process.platform === "win32"
    ? ".venv/Scripts/python.exe"
    : ".venv/bin/python",
);
const strategyPath = join(root, "strategies/validation_lifecycle.py");
assert.equal(
  existsSync(strategyPath),
  false,
  "Do not overwrite existing strategies",
);
await mkdir(join(home, "datasets"), { recursive: true });
const fixture = join(home, "fixture.py");
await writeFile(
  fixture,
  `import pandas as pd, numpy as np, sys
index = pd.date_range('2026-01-05', '2026-01-10', freq='1min', inclusive='left', tz='UTC', name='ts_event')
close = 100 + np.arange(len(index)) * .001
pd.DataFrame({'open': close, 'high': close + .01, 'low': close - .01, 'close': close + .005, 'volume': 100, 'instrument_id': 1}, index=index).to_parquet(sys.argv[1])
`,
);
const dataPath = join(home, "datasets/bars.parquet");
execFileSync(python, [fixture, dataPath], { windowsHide: true });
const digest = createHash("sha256")
  .update(await readFile(dataPath))
  .digest("hex");
const dataset = {
  id: "fixture-v1",
  symbol: "NQ",
  first: "2026-01-05T00:00:00Z",
  last: "2026-01-09T23:59:00Z",
  path: dataPath,
  checksum: digest,
  registered_at: new Date().toISOString(),
  currency: "USD",
  tick_size: 0.25,
  point_value: 20,
  warnings: ["Synthetic lifecycle fixture only"],
};
await writeFile(
  join(home, "datasets/catalog.json"),
  JSON.stringify({ datasets: [dataset], errors: [] }),
);
const strategyText = `STRATEGY = {'id': 'validation-lifecycle', 'name': 'Lifecycle fixture', 'description': 'Temporary automated test', 'version': '1', 'timeframes': ['1h'], 'parameters': {'mode': {'type': 'enum', 'default': 'normal', 'choices': ['normal', 'fail', 'slow']}}}
def signals(bars, parameters):
    import pandas as pd, time
    if parameters['mode'] == 'fail':
        raise RuntimeError('Deliberate validation failure')
    if parameters['mode'] == 'slow':
        print('Sleeping in fixture strategy', flush=True)
        time.sleep(60)
    return pd.Series(1, index=bars.index)
`;
await writeFile(strategyPath, strategyText);
let server;
const base = "http://127.0.0.1:8002/api/workbench";
const checks = [];
const delay = (ms) => new Promise((done) => setTimeout(done, ms));
async function api(path, data, method = "POST", expected = 200) {
  const response = await fetch(
    base + path,
    data === undefined
      ? undefined
      : {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
  );
  const json = await response.json();
  assert.equal(response.status, expected, JSON.stringify(json));
  return json;
}
async function start() {
  server = spawn(process.execPath, ["server/workbench.ts"], {
    cwd: root,
    env: {
      ...process.env,
      WORKBENCH_HOME: home,
      WORKBENCH_PORT: "8002",
      WORKBENCH_CONCURRENCY: "1",
    },
    windowsHide: true,
    stdio: "pipe",
  });
  let log = "";
  server.stdout.on("data", (d) => {
    log += d;
  });
  server.stderr.on("data", (d) => {
    log += d;
  });
  for (let i = 0; i < 100; i++) {
    try {
      await api("/state");
      return;
    } catch {
      if (server.exitCode !== null) throw new Error(log);
      await delay(100);
    }
  }
  throw new Error("Server startup timed out: " + log);
}
async function stop(abrupt = false) {
  if (!server || server.exitCode !== null) return;
  const exited = new Promise((done) => server.once("exit", done));
  server.kill(abrupt ? "SIGKILL" : "SIGTERM");
  await exited;
  await delay(200);
}
const input = {
  strategy_id: "validation-lifecycle",
  dataset_id: dataset.id,
  start: "2026-01-05",
  end: "2026-01-09",
  timeframe: "1h",
  session: "new-york-rth",
  stage: "Exploratory",
  capital: 100000,
  fee: 1.25,
  slippage: 1,
  warmup_days: 0,
  timeout: 30,
  parameters: {},
};
async function launch(overrides = {}) {
  return (await api("/runs", { ...input, ...overrides }, "POST", 201))[0];
}
async function waitRun(id, statuses = ["Succeeded"]) {
  for (let i = 0; i < 200; i++) {
    const record = await api("/runs/" + id);
    if (statuses.includes(record.status)) return record;
    if (
      ["Succeeded", "Failed", "Canceled", "Interrupted"].includes(record.status)
    )
      throw new Error("Unexpected terminal status: " + JSON.stringify(record));
    await delay(100);
  }
  throw new Error("Wait timeout for " + id);
}
try {
  await start();
  assert(
    (await api("/state")).strategies.some(
      (s) => s.id === "validation-lifecycle",
    ),
  );
  checks.push("New Python file is discovered without registry changes");
  await api("/preview", { ...input, parameters: { bad: 2 } }, "POST", 400);
  await api("/preview", { ...input, start: "2026-02-30" }, "POST", 400);
  await api("/preview", { ...input, stage: "Evaluation" }, "POST", 400);
  await api(
    "/preview",
    { ...input, sweep: { mode: Array(25).fill("normal") } },
    "POST",
    400,
  );
  checks.push(
    "Invalid parameters, dates, chronology and oversized grids fail preflight",
  );
  const run = await waitRun((await launch()).id);
  const replay = await waitRun(
    (await api(`/runs/${run.id}/retry`, {}, "POST", 201)).id,
  );
  assert.deepEqual(replay.result.metrics, run.result.metrics);
  assert.equal(replay.input.retry_of, run.id);
  checks.push(
    "Identical replay reproduces metrics and links the original attempt",
  );
  const failed = await waitRun(
    (await launch({ parameters: { mode: "fail" } })).id,
    ["Failed"],
  );
  assert.match(failed.log, /Deliberate validation failure/);
  const timeout = await waitRun(
    (await launch({ parameters: { mode: "slow" }, timeout: 1 })).id,
    ["Failed"],
  );
  assert.match(timeout.error, /Timeout/);
  checks.push("Exceptions and timeouts remain failed with diagnostic logs");
  const running = await launch({ parameters: { mode: "slow" } });
  await waitRun(running.id, ["Running"]);
  const queued = await launch();
  assert.equal((await api(`/runs/${queued.id}`)).status, "Queued");
  await api(`/runs/${queued.id}/cancel`, {});
  await api(`/runs/${running.id}/cancel`, {});
  assert.equal((await api(`/runs/${queued.id}`)).status, "Canceled");
  assert.equal((await api(`/runs/${running.id}`)).status, "Canceled");
  checks.push(
    "Concurrency bound, queued cancellation and running cancellation work",
  );
  const interrupted = await launch({ parameters: { mode: "slow" } });
  await waitRun(interrupted.id, ["Running"]);
  const persisted = await launch();
  await stop(true);
  await start();
  assert.equal((await api(`/runs/${interrupted.id}`)).status, "Interrupted");
  await waitRun(persisted.id);
  checks.push(
    "Supervisor restart marks lost workers Interrupted and resumes queued jobs",
  );
  const watch = await api(
    "/watchlist",
    { run_id: run.id, reason: "Lifecycle fixture" },
    "POST",
    201,
  );
  assert.equal(
    (await api(`/watchlist/${watch.id}/update`, {})).status,
    "No new data",
  );
  await writeFile(
    strategyPath,
    strategyText.replace("pd.Series(1,", "pd.Series(0,"),
  );
  await api("/discover", {});
  const changed = await waitRun((await launch()).id);
  assert.notEqual(changed.input.source_hash, run.input.source_hash);
  assert.equal(changed.result.metrics.trades, 0);
  const oldReplay = await waitRun(
    (await api(`/runs/${run.id}/retry`, {}, "POST", 201)).id,
  );
  assert.deepEqual(oldReplay.result.metrics, run.result.metrics);
  checks.push(
    "Editing a strategy creates a new source version; old snapshots still replay",
  );
  const correctedPath = join(home, "datasets/corrected.parquet");
  await copyFile(dataPath, correctedPath);
  const corrected = {
    ...dataset,
    id: "fixture-v2-corrected",
    path: correctedPath,
    registered_at: new Date(Date.now() + 1000).toISOString(),
  };
  await writeFile(
    join(home, "datasets/catalog.json"),
    JSON.stringify({ datasets: [dataset, corrected], errors: [] }),
  );
  await api("/state");
  const tracked = await waitRun(
    (await api(`/watchlist/${watch.id}/update`, {}, "POST", 201)).id,
  );
  assert.equal(tracked.input.source_hash, run.input.source_hash);
  assert.equal(tracked.input.configuration_id, run.input.configuration_id);
  assert.equal(tracked.input.dataset.id, corrected.id);
  assert.deepEqual(tracked.result.metrics, run.result.metrics);
  assert.equal((await api(`/runs/${run.id}`)).input.dataset.id, dataset.id);
  checks.push(
    "Corrected-data tracking preserves frozen code and original snapshots",
  );
  const exportData = await api(`/runs/${run.id}/export`);
  assert(
    exportData.source_files[
      "strategies" +
        (process.platform === "win32" ? "\\" : "/") +
        "validation_lifecycle.py"
    ],
  );
  assert(exportData.environment.dependencies.length > 0);
  checks.push("Evidence export includes actual source and dependency versions");
  await writeFile(
    join(root, "reports/workbench-validation/lifecycle-results.json"),
    JSON.stringify(
      { checked_at: new Date().toISOString(), home, checks },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ checks }, null, 2));
} finally {
  await stop();
  await unlink(strategyPath);
}
