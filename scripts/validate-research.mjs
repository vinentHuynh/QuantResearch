import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, writeFile, readFile, unlink } from "node:fs/promises";
import { existsSync } from "node:fs";
import { resolve, join } from "node:path";

const root = resolve("."),
  home = join(root, "data", `research-test-${randomUUID().slice(0, 6)}`);
const python = resolve(
  process.platform === "win32"
    ? ".venv/Scripts/python.exe"
    : ".venv/bin/python",
);
const strategyPath = join(root, "strategies/validation_research.py");
assert(!existsSync(strategyPath));
await mkdir(join(home, "datasets"), { recursive: true });
const fixture = join(home, "fixture.py"),
  dataPath = join(home, "datasets/bars.parquet");
await writeFile(
  fixture,
  `import pandas as pd, numpy as np, sys
index = pd.date_range('2026-01-05', '2026-03-01', freq='1min', inclusive='left', tz='UTC', name='ts_event')
t = np.arange(len(index)) / 1440
price = 100 + np.where(t < 14, t, 28-t) + .02*np.sin(t*50)
pd.DataFrame({'open': price, 'high': price+.01, 'low': price-.01, 'close': price+.002, 'volume': 100, 'instrument_id': 1}, index=index).to_parquet(sys.argv[1])
`,
);
execFileSync(python, [fixture, dataPath], { windowsHide: true });
const dataset = {
  id: "research-fixture",
  symbol: "NQ",
  first: "2026-01-05T00:00:00Z",
  last: "2026-02-28T23:59:00Z",
  path: dataPath,
  checksum: createHash("sha256")
    .update(await readFile(dataPath))
    .digest("hex"),
  registered_at: new Date().toISOString(),
  currency: "USD",
  tick_size: 0.25,
  point_value: 20,
  warnings: ["Synthetic research fixture"],
};
await writeFile(
  join(home, "datasets/catalog.json"),
  JSON.stringify({ datasets: [dataset], errors: [] }),
);
await writeFile(
  strategyPath,
  `STRATEGY = {'id':'validation-research','name':'Research fixture','description':'Temporary validation','version':'1','timeframes':['1h'],'parameters':{'direction':{'type':'integer','default':1,'minimum':-1,'maximum':1},'mode':{'type':'enum','default':'normal','choices':['normal','fail','slow']}}}
def signals(bars, parameters):
    import pandas as pd, time
    if parameters['mode'] == 'fail' and parameters['direction'] == -1: raise RuntimeError('Candidate failure')
    if parameters['mode'] == 'slow': time.sleep(30)
    return pd.Series(parameters['direction'], index=bars.index)
`,
);
const base = "http://127.0.0.1:8003/api/workbench",
  checks = [];
let server;
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
async function api(path, data, expected = 200) {
  const response = await fetch(
    base + path,
    data === undefined
      ? undefined
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
  );
  const result = await response.json();
  assert.equal(response.status, expected, JSON.stringify(result));
  return result;
}
async function start() {
  server = spawn(process.execPath, ["server/workbench.ts"], {
    cwd: root,
    env: {
      ...process.env,
      WORKBENCH_HOME: home,
      WORKBENCH_PORT: "8003",
      WORKBENCH_CONCURRENCY: "2",
    },
    windowsHide: true,
    stdio: "pipe",
  });
  let log = "";
  server.stdout.on("data", (x) => {
    log += x;
  });
  server.stderr.on("data", (x) => {
    log += x;
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
  throw new Error("Server unavailable: " + log);
}
async function stop() {
  if (!server || server.exitCode !== null) return;
  const closed = new Promise((r) => server.once("exit", r));
  server.kill("SIGKILL");
  await closed;
  await delay(200);
}
async function wait(id, statuses = ["Succeeded"]) {
  for (let i = 0; i < 300; i++) {
    const result = await api("/evaluations/" + id);
    if (statuses.includes(result.status)) return result;
    if (["Failed", "Canceled"].includes(result.status))
      throw new Error(JSON.stringify(result));
    await delay(200);
  }
  throw new Error("Evaluation timeout");
}
const request = {
  name: "Chronology fixture",
  base: {
    strategy_id: "validation-research",
    dataset_id: dataset.id,
    start: "2026-01-05",
    end: "2026-02-28",
    timeframe: "1h",
    session: "new-york-rth",
    capital: 100000,
    fee: 0.1,
    slippage: 0,
    warmup_days: 0,
    timeout: 45,
    parameters: {},
  },
  sweep: { direction: [-1, 1] },
  train_days: 14,
  test_days: 7,
  folds: 2,
  metric: "net_pnl",
  min_trades: 1,
  min_test_trades: 1,
  min_return: 0,
  max_drawdown: 0.2,
  stress_multiple: 2,
  delay_bars: 1,
};
try {
  await start();
  const plan = await api("/evaluations/preview", request);
  assert.equal(plan.jobs, 10);
  assert(plan.folds.every((f) => f.train_end < f.test_start));
  assert(plan.folds[0].test_end < plan.folds[1].test_start);
  await api("/evaluations/preview", { ...request, folds: 12 }, 400);
  await api(
    "/evaluations/preview",
    { ...request, base: { ...request.base, delay_bars: 20 } },
    400,
  );
  checks.push(
    "Plan previews nonoverlapping test folds and rejects invalid bounds/delays",
  );
  const created = await api("/evaluations", request, 201);
  const complete = await wait(created.id);
  assert.equal(complete.runs.length, 10);
  assert.equal(
    complete.folds[0].selection.candidate,
    1,
    "Earlier upward training must select long despite later losses",
  );
  assert(
    complete.runs.find((r) => r.id === complete.folds[0].tests[0]).result
      .metrics.net_pnl < 0,
  );
  for (const fold of complete.folds) {
    for (const id of fold.training) {
      const run = complete.runs.find((r) => r.id === id);
      assert.equal(run.input.end, fold.train_end);
      assert.equal(run.input.source_hash, complete.source_hash);
    }
    for (const id of fold.tests) {
      const run = complete.runs.find((r) => r.id === id);
      assert.equal(run.input.start, fold.test_start);
      assert(run.created_at >= fold.selection.selected_at);
      assert.equal(
        run.input.parameters.direction,
        complete.candidates[fold.selection.candidate].parameters.direction,
      );
    }
  }
  assert.equal(complete.result.scenarios.length, 3);
  assert.equal(
    complete.result.scenarios[1].metrics.costs,
    2 * complete.result.scenarios[0].metrics.costs,
  );
  checks.push(
    "All candidates retained; training-only selection is saved before baseline/cost/delay tests",
  );
  const artifact = await fetch(
    base +
      `/research-artifact?kind=evaluations&id=${complete.id}&name=equity.csv`,
  );
  assert.equal(artifact.status, 200);
  assert((await artifact.text()).includes("scenario"));
  const investigate = await api(
    `/evaluations/${complete.id}/regimes`,
    { feature: "volatility", window: 3, quantile: 0.5, seed: 42 },
    201,
  );
  let result;
  for (let i = 0; i < 200; i++) {
    result = (await api("/state")).regimes.find((r) => r.id === investigate.id);
    if (result.status === "Succeeded") break;
    if (result.status === "Failed") throw new Error(JSON.stringify(result));
    await delay(200);
  }
  assert.equal(result.status, "Succeeded");
  assert.equal(result.result.thresholds.length, 2);
  assert(
    result.result.thresholds.every(
      (t, i) => t.calibrated_through === complete.folds[i].train_end,
    ),
  );
  const statePnl = result.result.states.reduce((sum, s) => sum + s.net_pnl, 0);
  assert(
    Math.abs(statePnl - complete.result.scenarios[0].metrics.net_pnl) < 1e-6,
  );
  checks.push(
    "Regime thresholds use training only and conditional P&L reconciles to baseline",
  );
  const failing = await api(
    "/evaluations",
    { ...request, base: { ...request.base, parameters: { mode: "fail" } } },
    201,
  );
  const failed = await wait(failing.id, ["Failed"]);
  assert(!failed.folds[0].selection);
  assert.equal(failed.folds[0].tests.length, 0);
  checks.push("A failed candidate prevents selection from an incomplete grid");
  const empty = await api(
    "/evaluations",
    { ...request, sweep: { direction: [0] } },
    201,
  );
  const inconclusive = await wait(empty.id);
  assert.equal(inconclusive.outcome, "Inconclusive");
  assert.equal(inconclusive.folds[0].tests.length, 0);
  await api(`/evaluations/${empty.id}/regimes`, {}, 400);
  checks.push(
    "Successful execution with no eligible candidate produces an Inconclusive outcome",
  );
  const canceled = await api(
    "/evaluations",
    { ...request, base: { ...request.base, parameters: { mode: "slow" } } },
    201,
  );
  await api(`/evaluations/${canceled.id}/cancel`, {});
  assert.equal((await api(`/evaluations/${canceled.id}`)).status, "Canceled");
  const interrupted = await api(
    "/evaluations",
    { ...request, base: { ...request.base, parameters: { mode: "slow" } } },
    201,
  );
  await delay(800);
  await stop();
  await start();
  const resumed = await wait(interrupted.id, ["Failed"]);
  assert.equal(resumed.folds[0].tests.length, 0);
  const preserved = await api(`/evaluations/${complete.id}`);
  assert.deepEqual(preserved.folds, complete.folds);
  assert.deepEqual(preserved.result, complete.result);
  checks.push(
    "Cancellation/restart cannot promote partial grids; completed selections survive restart",
  );
  await mkdir("reports/workbench-validation", { recursive: true });
  await writeFile(
    "reports/workbench-validation/research-api-results.json",
    JSON.stringify(
      { checked_at: new Date().toISOString(), checks, home },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ checks }, null, 2));
} finally {
  await stop();
  await unlink(strategyPath);
}
