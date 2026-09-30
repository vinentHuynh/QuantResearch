import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const suffix = randomUUID().slice(0, 8);
const home = join(root, "data", `wbtest-log-${suffix}`);
const strategyId = `validation-log-${suffix}`;
const strategyPath = join(root, "strategies", `validation_log_${suffix}.py`);
const python = join(root, process.platform === "win32"
  ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const port = 14000 + Math.floor(Math.random() * 10000);
const base = `http://127.0.0.1:${port}/api/workbench`;
const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");
const delay = (ms) => new Promise((done) => setTimeout(done, ms));
let server;
let serverOutput = "";

async function api(path, body) {
  const response = await fetch(base + path, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const value = response.headers.get("content-type")?.includes("application/json")
    ? await response.json() : await response.text();
  return { status: response.status, value };
}

async function waitForServer() {
  for (let attempt = 0; attempt < 120; attempt++) {
    try {
      const response = await api("/state");
      if (response.status === 200) return;
    } catch { /* The listener may not be ready yet. */ }
    if (server.exitCode !== null) throw new Error(serverOutput);
    await delay(100);
  }
  throw new Error(`Workbench test server did not start: ${serverOutput}`);
}

async function waitForRun(id) {
  for (let attempt = 0; attempt < 300; attempt++) {
    const response = await api(`/runs/${id}`);
    assert.equal(response.status, 200, JSON.stringify(response.value));
    if (response.value.status === "Succeeded") return response.value;
    if (["Failed", "Canceled", "Interrupted"].includes(response.value.status))
      throw new Error(JSON.stringify(response.value));
    await delay(100);
  }
  throw new Error(`Test run ${id} did not finish`);
}

try {
  assert(!existsSync(strategyPath), "Temporary strategy path already exists");
  mkdirSync(join(home, "datasets"), { recursive: true });
  const dataPath = join(home, "datasets", "bars.parquet");
  execFileSync(python, ["-c", `
import numpy as np, pandas as pd, sys
index = pd.date_range('2026-01-05', '2026-01-10', freq='1min', inclusive='left', tz='UTC', name='ts_event')
close = 100 + np.arange(len(index)) * .001
pd.DataFrame({'open': close, 'high': close + .01, 'low': close - .01,
              'close': close + .005, 'volume': 100,
              'instrument_id': 1}, index=index).to_parquet(sys.argv[1])
`, dataPath], { windowsHide: true });
  const dataset = {
    id: `fixture-${suffix}`, symbol: "NQ", first: "2026-01-05T00:00:00Z",
    last: "2026-01-09T23:59:00Z", path: dataPath,
    checksum: digest(readFileSync(dataPath)), registered_at: new Date().toISOString(),
    currency: "USD", tick_size: .25, point_value: 20, warnings: [],
  };
  writeFileSync(join(home, "datasets", "catalog.json"),
    JSON.stringify({ datasets: [dataset], errors: [] }));
  writeFileSync(strategyPath, `STRATEGY = {'id': '${strategyId}', 'name': 'Log integrity fixture',
    'version': '1', 'description': 'Isolated artifact test', 'timeframes': ['1m'],
    'execution_model': 'event-v1', 'parameters': {}}
class Model:
    def __init__(self):
        self.sent = False
    def on_close(self, i, bar, state):
        if state['tradable'] and not self.sent:
            self.sent = True
            return {'target': 1, 'timing': 'next-open', 'bracket': (0., 200.),
                    'order_id': 'fixture-order', 'signal_id': 'fixture-signal',
                    'reason': 'integrity-fixture'}
        return None
def create_strategy(bars, parameters, request):
    print('AW_LOG_START', flush=True)
    print('x' * 120000, flush=True)
    print('AW_LOG_END', flush=True)
    return Model()
`);
  server = spawn(process.execPath, ["server/workbench.ts"], {
    cwd: root, windowsHide: true, stdio: "pipe",
    env: { ...process.env, WORKBENCH_HOME: home,
           WORKBENCH_PORT: String(port), WORKBENCH_CONCURRENCY: "1" },
  });
  server.stdout.on("data", (bytes) => { serverOutput += bytes; });
  server.stderr.on("data", (bytes) => { serverOutput += bytes; });
  await waitForServer();
  const input = {
    strategy_id: strategyId, dataset_id: dataset.id,
    start: "2026-01-05", end: "2026-01-09", timeframe: "1m",
    session: "full-trading-day", stage: "Exploratory", capital: 100000,
    fee: 0, slippage: 0, warmup_days: 0, timeout: 30, parameters: {},
  };
  const preview = await api("/preview", input);
  assert.equal(preview.status, 200, JSON.stringify(preview.value));
  const launched = await api("/runs", input);
  assert.equal(launched.status, 201, JSON.stringify(launched.value));
  const run = await waitForRun(launched.value[0].id);
  const folder = join(home, "runs", run.id);
  const logPath = join(folder, "process.log");
  const manifestPath = join(folder, "manifest.json");
  const log = readFileSync(logPath);
  assert(log.length > 100000, "The complete process log should exceed the old cap");
  assert(log.toString().includes("AW_LOG_START"));
  assert(log.toString().includes("AW_LOG_END"));
  const entry = run.result.artifacts.find((artifact) => artifact.name === "process.log");
  assert(entry, "The published manifest must checksum process.log");
  assert.equal(entry.checksum, digest(log));
  const signalEntry = run.result.artifacts.find((artifact) => artifact.name === "signals.csv");
  assert(signalEntry, "Event runs must publish a checksummed signals.csv ledger");
  const signalPath = join(folder, "signals.csv");
  const signals = readFileSync(signalPath);
  assert.equal(signalEntry.checksum, digest(signals));
  assert(signals.toString().includes("fixture-signal"));
  assert.deepEqual(JSON.parse(readFileSync(manifestPath)), run.result);
  const logArtifact = await fetch(`${base}/runs/${run.id}/artifact?name=process.log`);
  assert.equal(logArtifact.status, 200);
  assert.equal(Buffer.compare(Buffer.from(await logArtifact.arrayBuffer()), log), 0);
  const signalArtifact = await fetch(`${base}/runs/${run.id}/artifact?name=signals.csv`);
  assert.equal(signalArtifact.status, 200);
  assert.equal(Buffer.compare(Buffer.from(await signalArtifact.arrayBuffer()), signals), 0);

  writeFileSync(logPath, Buffer.concat([log, Buffer.from("tampered")]));
  assert.equal((await api(`/runs/${run.id}/artifact?name=process.log`)).status, 400);
  assert.equal((await api(`/runs/${run.id}`)).status, 400);
  writeFileSync(logPath, log);
  writeFileSync(signalPath, Buffer.concat([signals, Buffer.from("tampered")]));
  assert.equal((await api(`/runs/${run.id}/artifact?name=signals.csv`)).status, 400);
  writeFileSync(signalPath, signals);
  const tradesPath = join(folder, "trades.csv");
  const trades = readFileSync(tradesPath);
  writeFileSync(tradesPath, Buffer.concat([trades, Buffer.from("tampered")]));
  assert.equal((await api(`/runs/${run.id}/artifact?name=trades.csv`)).status, 400);
  writeFileSync(tradesPath, trades);
  const originalManifest = readFileSync(manifestPath);
  const changedManifest = JSON.parse(originalManifest);
  changedManifest.metrics.net_pnl += 1;
  writeFileSync(manifestPath, JSON.stringify(changedManifest));
  assert.equal((await api(`/runs/${run.id}/artifact?name=manifest.json`)).status, 400);
  writeFileSync(manifestPath, originalManifest);

  // Saved runs from before this change have no process.log checksum.
  const legacy = structuredClone(run);
  legacy.result.artifacts = legacy.result.artifacts.filter((artifact) =>
    artifact.name !== "process.log");
  writeFileSync(manifestPath, JSON.stringify(legacy.result));
  const db = new DatabaseSync(join(home, "workbench.sqlite3"));
  try {
    db.prepare("UPDATE records SET body=? WHERE kind='run' AND id=?")
      .run(JSON.stringify(legacy), run.id);
  } finally { db.close(); }
  assert.equal((await api(`/runs/${run.id}`)).status, 200);
  assert.equal((await api(`/runs/${run.id}/artifact?name=process.log`)).status, 200);
  console.log("PASS: event signals and full log checksums, download/tamper validation, old run compatibility");
} finally {
  if (server && server.exitCode === null) {
    const exited = new Promise((done) => server.once("exit", done));
    server.kill("SIGTERM");
    await exited;
  }
  if (existsSync(strategyPath)) rmSync(strategyPath);
  const expectedPrefix = join(root, "data", "wbtest-log-");
  if (!home.startsWith(expectedPrefix)) throw new Error("Unsafe temporary test path");
  if (existsSync(home)) rmSync(home, { recursive: true, force: true });
}
