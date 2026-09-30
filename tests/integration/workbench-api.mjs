import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import {
  cp,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";

const root = resolve(".");
const python =
  process.env.WORKBENCH_PYTHON ||
  resolve(
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python",
  );
assert(
  process.env.WORKBENCH_PYTHON || existsSync(python),
  `Workbench Python was not found at ${python}`,
);

const home = await mkdtemp(join(tmpdir(), "strategy-workbench-api-"));
const artifacts = join(home, "artifacts");
const datasets = join(home, "datasets");
await mkdir(artifacts, { recursive: true });
await mkdir(datasets, { recursive: true });

const fixturePath = join(datasets, "bars.parquet");
const fixtureProgram = [
  "import numpy as np, pandas as pd, sys",
  "index = pd.date_range('2026-01-05', '2026-01-27', freq='1min', inclusive='left', tz='UTC', name='ts_event')",
  "close = 100 + np.arange(len(index), dtype=float) * 0.001",
  "frame = pd.DataFrame({'open': close, 'high': close + .02, 'low': close - .02, 'close': close + .005, 'volume': 100, 'instrument_id': 1}, index=index)",
  "frame.to_parquet(sys.argv[1])",
].join("\n");
const fixtureResult = spawnSync(python, ["-c", fixtureProgram, fixturePath], {
  cwd: root,
  encoding: "utf8",
  windowsHide: true,
});
assert.equal(
  fixtureResult.status,
  0,
  fixtureResult.stderr || fixtureResult.error?.message,
);

const checksum = createHash("sha256")
  .update(await readFile(fixturePath))
  .digest("hex");
const dataset = {
  id: "fixture-v1",
  symbol: "FIXTURE",
  source: "Synthetic API fixture",
  rows: 7_200,
  first: "2026-01-05T00:00:00Z",
  last: "2026-01-09T23:59:00Z",
  path: fixturePath,
  checksum,
  registered_at: "2026-01-10T00:00:00Z",
  timeframe: "1m",
  timezone: "UTC",
  currency: "USD",
  tick_size: 0.25,
  point_value: 2,
  warnings: ["Synthetic fixture; software validation only."],
};
const latestDataset = {
  ...dataset,
  schema_version: 2,
  id: "fixture-v2",
  rows: 31_680,
  last: "2026-01-26T23:59:00Z",
  path: "datasets/bars.parquet",
  registered_at: "2026-01-11T00:00:00Z",
};
const catalogReplacementForLegacyId = {
  ...dataset,
  schema_version: 2,
  path: "datasets/bars.parquet",
  registered_at: "2026-01-12T00:00:00Z",
};
await writeFile(
  join(datasets, "catalog.json"),
  JSON.stringify({ datasets: [catalogReplacementForLegacyId, latestDataset], errors: [] }),
);
const legacyDatasetBytes = JSON.stringify(dataset);
{
  const database = new DatabaseSync(join(home, "workbench.sqlite3"));
  try {
    database.exec(
      "CREATE TABLE records (kind TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(kind,id))",
    );
    database
      .prepare("INSERT INTO records(kind,id,body) VALUES(?,?,?)")
      .run("dataset", dataset.id, legacyDatasetBytes);
  } finally {
    database.close();
  }
}

async function freePort() {
  const probe = createServer();
  await new Promise((resolveDone, reject) => {
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", resolveDone);
  });
  const address = probe.address();
  const port = typeof address === "object" && address ? address.port : 0;
  await new Promise((resolveDone) => probe.close(resolveDone));
  return port;
}

const port = await freePort();
const base = `http://127.0.0.1:${port}/api/workbench`;
let server;
let serverLog = "";

const delay = (milliseconds) =>
  new Promise((resolveDone) => setTimeout(resolveDone, milliseconds));

async function request(path, body, method = "POST", expected = 200) {
  const response = await fetch(base + path, {
    ...(body === undefined
      ? {}
      : {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  assert.equal(response.status, expected, JSON.stringify(payload));
  return payload;
}

async function startServer() {
  server = spawn(process.execPath, ["server/workbench.ts"], {
    cwd: root,
    env: {
      ...process.env,
      WORKBENCH_HOME: home,
      WORKBENCH_ARTIFACTS: artifacts,
      WORKBENCH_PORT: String(port),
      WORKBENCH_CONCURRENCY: "1",
      PYTHONDONTWRITEBYTECODE: "1",
    },
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const capture = (chunk) => {
    serverLog = (serverLog + chunk).slice(-30_000);
  };
  server.stdout.on("data", capture);
  server.stderr.on("data", capture);

  for (let attempt = 0; attempt < 150; attempt += 1) {
    if (server.exitCode !== null)
      throw new Error(`Isolated API exited during startup:\n${serverLog}`);
    try {
      return await request("/state");
    } catch {
      await delay(100);
    }
  }
  throw new Error(`Isolated API startup timed out:\n${serverLog}`);
}

async function stopServer() {
  if (!server || server.exitCode !== null) return;
  const exited = new Promise((resolveDone) => server.once("exit", resolveDone));
  server.kill("SIGTERM");
  await Promise.race([exited, delay(5_000)]);
  if (server.exitCode === null) server.kill("SIGKILL");
}

async function waitForRun(id) {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const run = await request(`/runs/${id}`);
    if (run.status === "Succeeded") return run;
    if (["Failed", "Canceled", "Interrupted"].includes(run.status))
      throw new Error(`Run ${id} ended ${run.status}: ${run.error || run.log}`);
    await delay(100);
  }
  throw new Error(`Run ${id} did not finish`);
}

async function waitForEvaluation(id) {
  for (let attempt = 0; attempt < 600; attempt += 1) {
    const evaluation = await request(`/evaluations/${id}`);
    if (evaluation.status === "Succeeded") return evaluation;
    if (["Failed", "Canceled"].includes(evaluation.status))
      throw new Error(
        `Evaluation ${id} ended ${evaluation.status}: ${evaluation.error || evaluation.note}`,
      );
    await delay(100);
  }
  throw new Error(`Evaluation ${id} did not finish`);
}

async function waitForRegime(id) {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const state = await request("/state?view=summary");
    const regime = state.regimes.find((record) => record.id === id);
    if (regime?.status === "Succeeded") return regime;
    if (["Failed", "Canceled", "Interrupted"].includes(regime?.status))
      throw new Error(
        `Regime ${id} ended ${regime.status}: ${regime.error || "unknown error"}`,
      );
    await delay(100);
  }
  throw new Error(`Regime ${id} did not finish`);
}

async function waitForDeletionPreview(ids) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const response = await fetch(`${base}/runs/delete-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    });
    const payload = JSON.parse(await response.text());
    if (response.ok) return payload;
    if (/Cancel active runs/i.test(String(payload.error))) {
      await delay(50);
      continue;
    }
    assert.fail(`Deletion preview failed (${response.status}): ${JSON.stringify(payload)}`);
  }
  throw new Error("Canceled worker did not release before deletion preview");
}

async function replayProtocolV1(v2Run) {
  const legacyId = "legacy-v1-replay";
  const sourceRoot = join(home, "legacy-v1-source");
  const runRoot = join(home, "runs", legacyId);
  const includeSource = (source) =>
    !source.split(/[\\/]/).includes("__pycache__") && !source.endsWith(".pyc");
  await Promise.all([
    cp(join(root, "workbench"), join(sourceRoot, "workbench"), {
      recursive: true,
      filter: includeSource,
    }),
    cp(join(root, "strategy_engine"), join(sourceRoot, "strategy_engine"), {
      recursive: true,
      filter: includeSource,
    }),
    mkdir(join(sourceRoot, "strategies"), { recursive: true }),
    mkdir(runRoot, { recursive: true }),
  ]);
  await cp(
    join(root, "strategies", "buy_hold.py"),
    join(sourceRoot, "strategies", "buy_hold.py"),
  );
  await writeFile(
    join(sourceRoot, "environment.json"),
    JSON.stringify({ dependencies: [] }, null, 2),
  );

  const adapterPath = join(sourceRoot, "strategies", "buy_hold.py");
  const adapterHash = createHash("sha256")
    .update(await readFile(adapterPath))
    .digest("hex");
  const legacyInput = structuredClone(v2Run.input);
  legacyInput.protocol = 1;
  legacyInput.id = legacyId;
  legacyInput.dataset.path = resolve(fixturePath);
  delete legacyInput.dataset.schema_version;
  legacyInput.source_dir = resolve(sourceRoot);
  legacyInput.strategy.file = "strategies/buy_hold.py";
  legacyInput.strategy.file_hash = adapterHash;
  legacyInput.source_hash = adapterHash;
  delete legacyInput.source_snapshot;
  delete legacyInput.execution_source_hash;
  delete legacyInput.snapshot_hash;
  delete legacyInput.app_build_hash;

  const requestPath = join(runRoot, "input.json");
  await writeFile(requestPath, JSON.stringify(legacyInput, null, 2));
  const replay = spawnSync(python, ["-m", "workbench.worker", requestPath], {
    cwd: sourceRoot,
    env: {
      ...process.env,
      PYTHONDONTWRITEBYTECODE: "1",
    },
    encoding: "utf8",
    windowsHide: true,
    timeout: 60_000,
  });
  assert.equal(
    replay.status,
    0,
    replay.stderr || replay.stdout || replay.error?.message,
  );
  const manifest = JSON.parse(await readFile(join(runRoot, "manifest.json"), "utf8"));
  assert.equal(manifest.protocol, 1);
  assert.equal(manifest.run_id, legacyInput.id);
  assert.equal("execution_source_hash" in manifest, false);
  assert.equal("snapshot_hash" in manifest, false);
  assert.equal("app_build_hash" in manifest, false);
  assert.deepEqual(manifest.metrics, v2Run.result.metrics);
  assert.deepEqual(
    manifest.artifacts.map((artifact) => artifact.name),
    ["equity.csv", "trades.csv", "positions.csv"],
  );
  return { manifest, input: legacyInput };
}

function storeProtocolV1Run(input, result) {
  const timestamp = new Date().toISOString();
  const run = {
    id: input.id,
    status: "Succeeded",
    created_at: timestamp,
    started_at: timestamp,
    ended_at: timestamp,
    input,
    result,
    notes: "Fixture protocol-v1 row",
    tags: "compatibility",
  };
  const database = new DatabaseSync(join(home, "workbench.sqlite3"));
  try {
    database.exec("PRAGMA busy_timeout=5000");
    database
      .prepare("INSERT INTO records(kind,id,body) VALUES(?,?,?)")
      .run("run", run.id, JSON.stringify(run));
  } finally {
    database.close();
  }
  return run;
}

const input = {
  strategy_id: "buy-hold",
  dataset_id: dataset.id,
  start: "2026-01-05",
  end: "2026-01-09",
  timeframe: "1h",
  session: "full-trading-day",
  stage: "Exploratory",
  capital: 100_000,
  fee: 1.25,
  slippage: 1,
  warmup_days: 0,
  timeout: 30,
  parameters: { contracts: 1 },
};

try {
  const initial = await startServer();
  assert(initial.strategies.some((strategy) => strategy.id === "buy-hold"));
  const preservedV1Dataset = initial.datasets.find((item) => item.id === dataset.id);
  assert(preservedV1Dataset);
  assert.equal(preservedV1Dataset.schema_version, undefined);
  assert.equal(preservedV1Dataset.path, fixturePath);
  {
    const database = new DatabaseSync(join(home, "workbench.sqlite3"));
    try {
      const stored = database
        .prepare("SELECT body FROM records WHERE kind='dataset' AND id=?")
        .get(dataset.id);
      assert.equal(stored.body, legacyDatasetBytes);
    } finally {
      database.close();
    }
  }
  const registeredV2 = initial.datasets.find(
    (item) => item.id === latestDataset.id,
  );
  assert.equal(registeredV2.schema_version, 2);
  assert.equal(registeredV2.path, "datasets/bars.parquet");
  assert.deepEqual(initial.errors, []);

  const preview = await request("/preview", input);
  assert.equal(preview.jobs, 1);

  const launched = await request("/runs", input, "POST", 201);
  assert.equal(launched.length, 1);
  const run = await waitForRun(launched[0].id);
  const hash64 = /^[a-f0-9]{64}$/;
  assert.equal(run.input.protocol, 2);
  assert.equal(run.input.development_end, "");
  assert.equal(run.input.dataset.id, dataset.id);
  assert.equal(run.input.dataset.schema_version, 2);
  assert.equal(isAbsolute(run.input.dataset.path), false);
  assert.equal(run.input.dataset.path, "datasets/bars.parquet");
  assert.match(run.input.source_snapshot, /^sources\/[a-f0-9]{64}$/);
  assert.equal(run.input.source_dir, run.input.source_snapshot);
  assert.equal(isAbsolute(run.input.source_snapshot), false);
  for (const field of [
    "execution_source_hash",
    "snapshot_hash",
    "app_build_hash",
  ])
    assert.match(run.input[field], hash64, field);
  assert.equal(run.input.source_hash, run.input.execution_source_hash);
  assert.equal(run.result.protocol, 2);
  assert.equal(run.result.execution_source_hash, run.input.execution_source_hash);
  assert.equal(run.result.snapshot_hash, run.input.snapshot_hash);
  assert.equal(run.result.app_build_hash, run.input.app_build_hash);
  assert.equal(run.result.metrics.trades, 1);

  const retryRecord = await request(`/runs/${run.id}/retry`, {}, "POST", 201);
  const retry = await waitForRun(retryRecord.id);
  assert.equal(retry.input.retry_of, run.id);
  assert.equal(
    retry.input.execution_source_hash,
    run.input.execution_source_hash,
  );
  assert.equal(retry.input.snapshot_hash, run.input.snapshot_hash);
  assert.equal(retry.input.app_build_hash, run.input.app_build_hash);
  assert.deepEqual(retry.result.metrics, run.result.metrics);

  const comparison = await request("/compare", {
    ids: [run.id, retry.id],
    mode: "as-run",
  });
  assert.equal(comparison.runs.length, 2);

  const exported = await request(`/runs/${run.id}/export`);
  assert.equal(exported.run.id, run.id);
  assert(Object.keys(exported.source_files).length > 0);

  const watch = await request("/watchlist", {
    run_id: run.id,
    reason: "Synthetic protocol-v2 tracking verification",
  }, "POST", 201);
  const trackingRecord = await request(`/watchlist/${watch.id}/update`, {}, "POST", 201);
  assert.equal(trackingRecord.input.protocol, 2);
  assert.equal(trackingRecord.input.dataset.id, latestDataset.id);
  assert.equal(trackingRecord.input.dataset.path, "datasets/bars.parquet");
  assert.equal(isAbsolute(trackingRecord.input.dataset.path), false);
  const tracking = await waitForRun(trackingRecord.id);
  assert.equal(tracking.status, "Succeeded");

  const evaluationRequest = {
    name: "Synthetic protocol-v2 evaluation lifecycle",
    base: {
      ...input,
      dataset_id: latestDataset.id,
      start: "2026-01-05",
      end: "2026-01-25",
    },
    sweep: {},
    train_days: 7,
    test_days: 7,
    folds: 1,
    metric: "net_pnl",
    min_trades: 1,
    min_test_trades: 1,
    min_return: -1,
    max_drawdown: 1,
    stress_multiple: 2,
    delay_bars: 1,
    hypothesis: "Synthetic software verification only.",
  };
  const evaluationPlan = await request(
    "/evaluations/preview",
    evaluationRequest,
  );
  assert.equal(evaluationPlan.jobs, 4);
  const evaluationRecord = await request(
    "/evaluations",
    evaluationRequest,
    "POST",
    201,
  );
  const evaluation = await waitForEvaluation(evaluationRecord.id);
  assert.equal(evaluation.result.scenarios.length, 3);
  assert.match(evaluation.source_snapshot, /^sources\/[a-f0-9]{64}$/);
  assert(
    evaluation.runs.every(
      (candidate) => candidate.input.source_snapshot === evaluation.source_snapshot,
    ),
  );
  const regimeRecord = await request(
    `/evaluations/${evaluation.id}/regimes`,
    { feature: "volatility", window: 3, quantile: 0.5, seed: 42 },
    "POST",
    201,
  );
  const regime = await waitForRegime(regimeRecord.id);
  assert.equal(regime.result.thresholds.length, 1);

  const cancelCandidate = await request("/runs", input, "POST", 201);
  assert.equal(cancelCandidate.length, 1);
  const canceled = await request(
    `/runs/${cancelCandidate[0].id}/cancel`,
    {},
  );
  assert.equal(canceled.status, "Canceled");
  assert.equal((await request(`/runs/${canceled.id}`)).status, "Canceled");

  const deletionPreview = await waitForDeletionPreview([canceled.id]);
  assert.deepEqual(deletionPreview.affected_ids, [canceled.id]);
  const deletion = await request("/runs/delete", {
    ids: deletionPreview.ids,
    token: deletionPreview.token,
  });
  assert.equal(deletion.counts.runs, 1);
  assert(existsSync(join(deletion.backup, "records.json")));
  const deletedLookup = await request(`/runs/${canceled.id}`, undefined, "GET", 400);
  assert.match(deletedLookup.error, /not found/i);
  const recovered = await request("/runs/restore", {
    deletion_id: deletion.id,
  });
  assert(recovered.restored);
  assert.equal((await request(`/runs/${canceled.id}`)).status, "Canceled");
  assert.equal((await request(`/runs/${run.id}`)).status, "Succeeded");
  assert.equal((await request(`/runs/${retry.id}`)).status, "Succeeded");

  const legacyReplay = await replayProtocolV1(run);
  assert.equal(legacyReplay.manifest.metrics.trades, 1);
  const storedLegacy = storeProtocolV1Run(
    legacyReplay.input,
    legacyReplay.manifest,
  );

  const openedLegacy = await request(`/runs/${storedLegacy.id}`);
  assert.equal(openedLegacy.input.protocol, 1);
  assert.equal(openedLegacy.input.dataset.path, resolve(fixturePath));
  assert.equal(openedLegacy.input.source_dir, resolve(home, "legacy-v1-source"));

  const exportedLegacy = await request(`/runs/${storedLegacy.id}/export`);
  assert.equal(exportedLegacy.run.id, storedLegacy.id);
  assert(
    Object.keys(exportedLegacy.source_files)
      .map((path) => path.replaceAll("\\", "/"))
      .includes("strategies/buy_hold.py"),
  );

  const legacyComparison = await request("/compare", {
    ids: [run.id, storedLegacy.id],
    mode: "as-run",
  });
  assert.deepEqual(
    legacyComparison.runs.map((candidate) => candidate.id),
    [run.id, storedLegacy.id],
  );

  const legacyRetryRecord = await request(
    `/runs/${storedLegacy.id}/retry`,
    {},
    "POST",
    201,
  );
  assert.equal(legacyRetryRecord.input.protocol, 1);
  assert.equal(isAbsolute(legacyRetryRecord.input.dataset.path), true);
  const legacyRetry = await waitForRun(legacyRetryRecord.id);
  assert.equal(legacyRetry.input.retry_of, storedLegacy.id);
  assert.equal(legacyRetry.result.protocol, 1);

  const legacyWatch = await request(
    "/watchlist",
    {
      run_id: storedLegacy.id,
      reason: "Synthetic protocol-v1 tracking verification",
    },
    "POST",
    201,
  );
  const legacyTrackingRecord = await request(
    `/watchlist/${legacyWatch.id}/update`,
    {},
    "POST",
    201,
  );
  assert.equal(legacyTrackingRecord.input.protocol, 1);
  assert.equal(legacyTrackingRecord.input.dataset.id, latestDataset.id);
  assert.equal(legacyTrackingRecord.input.dataset.path, resolve(fixturePath));
  assert.equal(isAbsolute(legacyTrackingRecord.input.dataset.path), true);
  const legacyTracking = await waitForRun(legacyTrackingRecord.id);
  assert.equal(legacyTracking.result.protocol, 1);

  const finalState = await request("/state?view=summary");
  assert.equal(finalState.runs.length, 7 + evaluation.runs.length);
  console.log(
    `Isolated API lifecycle passed: protocol-v2 launch/retry/compare/export/watch/cancel/delete/restore/evaluation/regime plus protocol-v1 open/export/compare/retry/watch (${run.id}).`,
  );
} finally {
  await stopServer();
  await rm(home, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
