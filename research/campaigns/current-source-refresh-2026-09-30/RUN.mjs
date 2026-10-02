// Resumable, API-backed refresh of stale Workbench research evidence.
// It never changes or deletes original run/evaluation records.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const scriptFolder = dirname(fileURLToPath(import.meta.url));
const root = resolve(scriptFolder, "../../..");
const api = process.env.WORKBENCH_API || "http://127.0.0.1:8001/api/workbench";
const mode = process.argv[2] || "status";
const campaignId = "current-source-refresh-2026-09-30";
// Mutable campaign evidence must sit outside configured source roots.  Source
// snapshots hash JSON under research/, so writing state beside this driver
// would otherwise manufacture a different app build for every submission.
const folder = join(root, "artifacts", "research", campaignId);
const campaignFile = join(folder, "campaign.json");
const activeStatuses = new Set(["Queued", "Running", "Summarizing"]);
const terminalStatuses = new Set(["Succeeded", "Failed", "Canceled", "Interrupted"]);
const stateRoot = join(root, "data", "workbench");
const knownLegacyMappings = {
  "short-term-reversal": {
    sourceHash: "ca10f240944fd10c56c9318cb53b53e0561ed0bbb2365ce3df3de314b80df2da",
    values: {
      max_decline_pct: 0,
      hold_sessions: 1,
      renew_on_signal: true,
      exit_on_rebound: false,
      min_atr_multiple: 0,
      atr_period: 20,
    },
    rationale: "The preserved v1.0 target series held while a same-direction daily signal remained present. These v1.1 settings reproduce that state behavior while leaving the new engine itself subject to comparison.",
  },
  "pine-tsmom-orb": {
    values: { execution_timing: "close" },
    rationale: "The preserved Pine model defaults an omitted execution_timing to close; the explicit current parameter preserves that recorded signal-close setting.",
  },
};

mkdirSync(folder, { recursive: true });

const stamp = () => new Date().toISOString();
const readJson = (path) => JSON.parse(readFileSync(path, "utf8").replace(/^\uFEFF/, ""));
const writeJson = (name, value) =>
  writeFileSync(join(folder, name), `${JSON.stringify(value, null, 2)}\n`);
const stable = (value) => {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, stable(item)]),
    );
  return value;
};
const digest = (value) =>
  createHash("sha256").update(JSON.stringify(stable(value))).digest("hex");
const same = (left, right) => JSON.stringify(stable(left)) === JSON.stringify(stable(right));
const short = (id) => String(id).slice(0, 8);
const trim = (value, length) => String(value || "").slice(0, length);

function walkBuildFiles(folder, accept, output = []) {
  if (!existsSync(folder)) return output;
  for (const item of readdirSync(folder, { withFileTypes: true })) {
    if (["__pycache__", "node_modules", "dist"].includes(item.name)) continue;
    const path = join(folder, item.name);
    if (item.isDirectory()) walkBuildFiles(path, accept, output);
    else if (item.isFile() && accept(path)) output.push(path);
  }
  return output;
}
function applicationBuildHash() {
  const layout = readJson(join(root, "config", "workbench-layout.json"));
  const sourceRoots = (layout.source_roots || []).map((path) => join(root, path));
  const files = [
    ...sourceRoots.flatMap((sourceRoot) => walkBuildFiles(sourceRoot, (path) => /\.(?:ts|tsx|json|css)$/.test(path))),
    ...["package.json", "package-lock.json", "config/workbench-layout.json"]
      .map((path) => join(root, path))
      .filter((path) => existsSync(path)),
  ];
  const rows = [...new Set(files)]
    .sort()
    .map((file) => [relative(root, file).split(sep).join("/"), createHash("sha256").update(readFileSync(file)).digest("hex")]);
  return createHash("sha256").update(JSON.stringify(rows)).digest("hex");
}
function currentRuntimeIdentity() {
  const python = process.env.WORKBENCH_PYTHON || join(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
  const dependencies = JSON.parse(execFileSync(
    python,
    ["-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
    { encoding: "utf8", windowsHide: true },
  ));
  const environment = {
    python: execFileSync(python, ["--version"], { encoding: "utf8", windowsHide: true }).trim(),
    node: process.version,
    platform: process.platform,
    dependencies,
  };
  return {
    app_build_hash: applicationBuildHash(),
    environment,
    environment_hash: digest(environment),
  };
}

let campaign = existsSync(campaignFile) ? readJson(campaignFile) : null;
const save = () => {
  if (!campaign) throw new Error("Campaign has not been initialized");
  campaign.updated_at = stamp();
  writeFileSync(campaignFile, `${JSON.stringify(campaign, null, 2)}\n`);
};

async function call(path, { method = "GET", body } = {}) {
  const response = await fetch(api + path, body === undefined ? { method } : {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const raw = await response.text();
  let value;
  try {
    value = raw ? JSON.parse(raw) : {};
  } catch {
    value = { raw };
  }
  if (!response.ok) {
    const error = new Error(`${method} ${path}: ${value.error || response.statusText || raw}`);
    error.status = response.status;
    throw error;
  }
  return value;
}

const state = (full = false) => call(full ? "/state" : "/state?view=summary");
const strategyHash = (strategy) => strategy.execution_source_hash || strategy.file_hash;
const runHash = (run) => run?.input?.execution_source_hash || run?.input?.source_hash || run?.input?.strategy?.execution_source_hash || run?.input?.strategy?.file_hash || null;
function currentRun(run, strategy, runtime = campaign?.runtime_identity) {
  if (!strategy || run.input.strategy.id !== strategy.id) return false;
  const sourceMatches = run.input.protocol === 2
    ? runHash(run) === strategyHash(strategy)
    : run.input.strategy.file_hash === strategy.file_hash;
  return sourceMatches && runtimeMatchesInput(run.input, runtime);
}
function currentEvaluation(evaluation, strategy, runtime = campaign?.runtime_identity) {
  const candidate = evaluation?.candidates?.[0];
  if (!candidate || !strategy || candidate.strategy?.id !== strategy.id) return false;
  const source = evaluation.execution_source_hash || evaluation.source_hash || candidate.execution_source_hash || candidate.source_hash || candidate.strategy.execution_source_hash || candidate.strategy.file_hash;
  const sourceMatches = candidate.protocol === 2
    ? source === strategyHash(strategy)
    : candidate.strategy.file_hash === strategy.file_hash;
  return sourceMatches && runtimeMatchesInput(evaluation, runtime);
}
function active(records = []) {
  return (records || []).filter((record) => activeStatuses.has(record.status));
}
function sourceFolder(input) {
  const source = input.source_snapshot || input.source_dir || "";
  if (!source) return "";
  return isAbsolute(source) ? source : join(stateRoot, source);
}
function runtimeMatchesInput(input, runtime) {
  if (!runtime) return true;
  if (!input) return false;
  if (input.app_build_hash !== runtime.app_build_hash) return false;
  const snapshotFolder = sourceFolder(input);
  const snapshotPath = join(snapshotFolder, "snapshot.json");
  if (!snapshotFolder || !existsSync(snapshotPath)) return false;
  try {
    const snapshot = readJson(snapshotPath);
    const executionSource = input.execution_source_hash || input.source_hash || null;
    return snapshot.app_build_hash === runtime.app_build_hash &&
      snapshot.snapshot_hash === input.snapshot_hash &&
      snapshot.execution_source_hash === executionSource &&
      same(snapshot.environment, runtime.environment);
  } catch {
    return false;
  }
}
function assertRuntimeInput(input, label) {
  if (runtimeMatchesInput(input, campaign.runtime_identity)) return;
  campaign.runtime_violation = {
    at: stamp(),
    label,
    expected: campaign.runtime_identity,
    actual: {
      app_build_hash: input?.app_build_hash || null,
      snapshot_hash: input?.snapshot_hash || null,
      source_snapshot: input?.source_snapshot || input?.source_dir || null,
    },
  };
  save();
  throw new Error(`Application build or dependency environment changed while submitting ${label}. No further submissions were made.`);
}
function assertFrozenRuntime() {
  const actual = currentRuntimeIdentity();
  if (same(actual, campaign.runtime_identity)) return actual;
  campaign.runtime_drift = {
    at: stamp(),
    expected: campaign.runtime_identity,
    actual,
  };
  save();
  throw new Error("Current application build or Python dependency environment changed after the campaign was frozen. No further submissions were made.");
}
function artifactFolder(runId) {
  return join(stateRoot, "runs", runId);
}
function dateOffset(date, days) {
  return new Date(Date.parse(`${date}T00:00:00Z`) + days * 86400000)
    .toISOString()
    .slice(0, 10);
}
function inclusiveDays(start, end) {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000) + 1;
}
function completedUtcThrough(last) {
  const instant = new Date(last);
  if (!Number.isFinite(instant.getTime())) return "";
  const utc = instant.toISOString();
  const day = utc.slice(0, 10);
  return utc.slice(11, 16) === "23:59" ? day : dateOffset(day, -1);
}
function candidateKey(input) {
  return digest({
    strategy: input.strategy_id,
    dataset: input.dataset_id,
    start: input.start,
    end: input.end,
    timeframe: input.timeframe,
    session: input.session,
    parameters: input.parameters,
    capital: input.capital,
    fee: input.fee,
    slippage: input.slippage,
    warmup_days: input.warmup_days,
    delay_bars: input.delay_bars || 0,
    timeout: input.timeout,
    stage: input.stage,
    development_end: input.development_end || "",
    criteria: input.criteria || "",
    hypothesis: input.original_hypothesis || input.hypothesis || "",
  });
}
function extensionKey(input) {
  return digest({
    strategy: input.strategy_id,
    dataset: input.dataset_id,
    start: input.start,
    end: input.end,
    timeframe: input.timeframe,
    session: input.session,
    parameters: input.parameters,
    capital: input.capital,
    fee: input.fee,
    slippage: input.slippage,
    warmup_days: input.warmup_days,
    delay_bars: input.delay_bars || 0,
    timeout: input.timeout,
    stage: input.stage,
  });
}
function submissionAttempt(task) {
  return task?.attempt ?? 1;
}
function marker(kind, id, attempt = 1) {
  return `${campaignId}|${kind}|${id}|attempt-${attempt}`;
}
function markedHypothesis(kind, id, original, attempt = 1) {
  return trim(`[${marker(kind, id, attempt)}] ${original || ""}`, 2000);
}
function legacyMarker(kind, id) {
  return `[${campaignId}|${kind}|${id}]`;
}
function markedWithExactPrefix(value, prefix) {
  const text = String(value || "");
  return text.startsWith(prefix) && (text.length === prefix.length || /\s/.test(text.charAt(prefix.length)));
}
function legacyTaskRuns(runs, kind, task) {
  const prefix = legacyMarker(kind, task.id);
  return (runs || []).filter((run) => markedWithExactPrefix(run.input?.hypothesis, prefix));
}
function legacyMigrationBarrier() {
  return Boolean(campaign?.legacy_migration?.waiting_for_legacy_terminal);
}
function legacyCampaignRunIds() {
  return new Set((campaign?.legacy_migration?.tasks || []).flatMap((entry) => entry.run_ids || []));
}
function baselineRun(run) {
  if (run.input.portfolio_replay || run.input.research || run.input.delay_bars) return false;
  const tags = String(run.tags || "").toLowerCase();
  return !["stress", "sensitivity", "benchmark"].some((tag) => tags.includes(tag));
}

function resolveParameters(input, strategy) {
  const values = { ...(input.parameters || {}) };
  const definitions = strategy.parameters || {};
  const unknown = Object.keys(values).filter((name) => !(name in definitions));
  if (unknown.length) throw new Error(`Current ${strategy.id} no longer accepts: ${unknown.join(", ")}`);
  const missing = Object.keys(definitions).filter((name) => !(name in values));
  if (!missing.length) return { values, mappings: [] };
  const known = knownLegacyMappings[strategy.id];
  if (!known) throw new Error(`Current ${strategy.id} added unresolved parameters: ${missing.join(", ")}`);
  if (known.sourceHash && input.strategy.file_hash !== known.sourceHash)
    throw new Error(`Legacy mapping for ${strategy.id} only applies to source ${known.sourceHash}`);
  if (!missing.every((name) => name in known.values))
    throw new Error(`Current ${strategy.id} added unresolved parameters: ${missing.join(", ")}`);
  for (const name of missing) values[name] = known.values[name];
  return { values, mappings: [{ parameters: missing, values: Object.fromEntries(missing.map((name) => [name, values[name]])), rationale: known.rationale }] };
}

function makeRunRequest(run, strategy, { extension = false, dataset, end } = {}) {
  const parameterResolution = resolveParameters(run.input, strategy);
  const stage = extension ? "Exploratory" : run.input.stage === "Tracking" ? "Exploratory" : run.input.stage;
  if (!["Exploratory", "Evaluation"].includes(stage))
    throw new Error(`Unsupported saved run purpose ${run.input.stage}`);
  const request = {
    strategy_id: strategy.id,
    dataset_id: dataset?.id || run.input.dataset.id,
    start: run.input.start,
    end: end || run.input.end,
    timeframe: run.input.timeframe,
    session: run.input.session,
    parameters: parameterResolution.values,
    capital: run.input.capital,
    fee: run.input.fee,
    slippage: run.input.slippage,
    warmup_days: run.input.warmup_days,
    timeout: run.input.timeout,
    delay_bars: run.input.delay_bars || 0,
    stage,
    development_end: extension ? "" : run.input.development_end || "",
    criteria: extension ? "" : run.input.criteria || "",
    original_hypothesis: run.input.hypothesis || "",
    mappings: parameterResolution.mappings,
  };
  request.signature = candidateKey(request);
  return request;
}
function launchBody(request, kind, task) {
  const { original_hypothesis, mappings, signature, ...body } = request;
  return {
    ...body,
    hypothesis: markedHypothesis(kind, task.id, original_hypothesis, submissionAttempt(task)),
    sweep: {},
  };
}
function evaluationLaunchBody(task) {
  const originalBaseHypothesis = task.original?.candidates?.[0]?.hypothesis || "";
  return {
    ...task.request,
    base: {
      ...task.request.base,
      hypothesis: markedHypothesis("evaluation-base", task.id, originalBaseHypothesis, submissionAttempt(task)),
    },
    hypothesis: markedHypothesis("evaluation", task.id, task.original?.hypothesis || "", submissionAttempt(task)),
  };
}
function currentRequest(run, strategy) {
  return makeRunRequest(run, strategy);
}
function metricSubset(metrics = {}) {
  return Object.fromEntries(
    ["net_pnl", "net_return", "max_drawdown", "trades", "costs", "sharpe"]
      .map((name) => [name, metrics[name] ?? null]),
  );
}
const allowedArtifactNames = new Set([
  "equity.csv",
  "trades.csv",
  "positions.csv",
  "signals.csv",
  "process.log",
]);
function numericCell(value, label) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${label} is not finite`);
  return parsed;
}
function approximatelyEqual(left, right, label) {
  const tolerance = Math.max(0.0001, 0.000001 * Math.max(1, Math.abs(left), Math.abs(right)));
  if (Math.abs(left - right) > tolerance)
    throw new Error(`${label} does not reconcile (${left} versus ${right})`);
}
function csvAudit(bytes, name, required, numeric = []) {
  const lines = bytes.toString("utf8").replace(/^\uFEFF/, "").trimEnd().split(/\r?\n/);
  if (!lines[0]) throw new Error(`${name} is empty`);
  const header = lines[0].split(",");
  const indexes = new Map(header.map((column, index) => [column, index]));
  for (const column of required)
    if (!indexes.has(column)) throw new Error(`${name} is missing ${column}`);
  const totals = Object.fromEntries(numeric.map((column) => [column, 0]));
  let previous = -Infinity;
  let finalEquity = null;
  let rows = 0;
  for (const line of lines.slice(1)) {
    if (!line) continue;
    const values = line.split(",");
    for (const column of numeric) {
      const value = numericCell(values[indexes.get(column)], `${name}/${column}`);
      totals[column] += value;
      if (column === "equity") finalEquity = value;
    }
    if (indexes.has("timestamp")) {
      const time = Date.parse(values[indexes.get("timestamp")]);
      if (!Number.isFinite(time) || time <= previous)
        throw new Error(`${name} has non-increasing timestamps`);
      previous = time;
    }
    rows++;
  }
  return { rows, totals, final_equity: finalEquity };
}
function verifyManifest(runId, run) {
  const folder = artifactFolder(runId);
  const manifestPath = join(folder, "manifest.json");
  if (!existsSync(manifestPath)) throw new Error(`Missing manifest for ${runId}`);
  const manifestBytes = readFileSync(manifestPath);
  const manifest = JSON.parse(manifestBytes.toString("utf8").replace(/^\uFEFF/, ""));
  if (manifest.run_id && manifest.run_id !== runId)
    throw new Error(`Manifest run ID does not match ${runId}`);
  if (run?.result?.artifacts && !same(manifest.artifacts || [], run.result.artifacts))
    throw new Error(`Published result manifest differs for ${runId}`);
  const artifacts = Array.isArray(manifest.artifacts) ? manifest.artifacts : [];
  const files = new Map();
  for (const artifact of artifacts) {
    if (!allowedArtifactNames.has(artifact.name))
      throw new Error(`Unexpected artifact ${artifact.name} for ${runId}`);
    if (files.has(artifact.name)) throw new Error(`Duplicate artifact ${artifact.name} for ${runId}`);
    const path = join(folder, artifact.name);
    if (!existsSync(path)) throw new Error(`Missing ${artifact.name} for ${runId}`);
    const bytes = readFileSync(path);
    const checksum = createHash("sha256").update(bytes).digest("hex");
    if (checksum !== artifact.checksum)
      throw new Error(`Artifact checksum mismatch for ${runId}/${artifact.name}`);
    if (Number.isSafeInteger(artifact.bytes) && bytes.length !== artifact.bytes)
      throw new Error(`Artifact byte count mismatch for ${runId}/${artifact.name}`);
    files.set(artifact.name, { bytes, artifact });
  }
  for (const name of ["equity.csv", "trades.csv", "positions.csv"])
    if (!files.has(name)) throw new Error(`Required ${name} is missing for ${runId}`);
  const equity = csvAudit(
    files.get("equity.csv").bytes,
    "equity.csv",
    ["timestamp", "equity", "gross_pnl", "cost", "net_pnl"],
    ["equity", "gross_pnl", "cost", "net_pnl"],
  );
  const trades = csvAudit(
    files.get("trades.csv").bytes,
    "trades.csv",
    ["gross_pnl", "cost", "net_pnl"],
    ["gross_pnl", "cost", "net_pnl"],
  );
  const positions = csvAudit(files.get("positions.csv").bytes, "positions.csv", ["timestamp"]);
  for (const [name, { bytes, artifact }] of files) {
    if (Number.isSafeInteger(artifact.rows) && name.endsWith(".csv")) {
      const rows = name === "equity.csv" ? equity.rows : name === "trades.csv" ? trades.rows : name === "positions.csv" ? positions.rows : csvAudit(bytes, name, []).rows;
      if (rows !== artifact.rows) throw new Error(`Artifact row count mismatch for ${runId}/${name}`);
    }
  }
  const metrics = manifest.metrics || run?.result?.metrics;
  if (!metrics) throw new Error(`Metrics are missing from ${runId}`);
  const netPnl = numericCell(metrics.net_pnl, `${runId} metrics.net_pnl`);
  const costs = numericCell(metrics.costs, `${runId} metrics.costs`);
  const tradeCount = numericCell(metrics.trades, `${runId} metrics.trades`);
  approximatelyEqual(trades.totals.net_pnl, netPnl, `${runId} trade net P&L`);
  approximatelyEqual(equity.totals.net_pnl, netPnl, `${runId} equity net P&L`);
  approximatelyEqual(trades.totals.cost, costs, `${runId} trade costs`);
  approximatelyEqual(equity.totals.cost, costs, `${runId} equity costs`);
  approximatelyEqual(
    equity.totals.gross_pnl - equity.totals.cost,
    equity.totals.net_pnl,
    `${runId} equity gross less costs`,
  );
  if (trades.rows !== tradeCount)
    throw new Error(`${runId} trade count does not reconcile (${trades.rows} versus ${tradeCount})`);
  const capital = numericCell(run?.input?.capital, `${runId} input capital`);
  if (equity.final_equity === null) throw new Error(`${runId} equity ledger has no rows`);
  approximatelyEqual(equity.final_equity - capital, netPnl, `${runId} final equity`);
  return {
    status: "verified",
    artifact_count: artifacts.length,
    manifest_sha256: createHash("sha256").update(manifestBytes).digest("hex"),
    snapshot_hash: manifest.snapshot_hash || null,
    ledger: {
      trade_rows: trades.rows,
      equity_rows: equity.rows,
      net_pnl: netPnl,
      costs,
      final_equity: equity.final_equity,
    },
  };
}
function auditManifest(runId, run) {
  try {
    return verifyManifest(runId, run);
  } catch (error) {
    return { status: "failed", error: String(error.message || error) };
  }
}
function sourceIdentity(strategies) {
  return Object.fromEntries(
    strategies.map((strategy) => [strategy.id, {
      file_hash: strategy.file_hash,
      execution_source_hash: strategyHash(strategy),
      source_files: strategy.source_files || [],
    }]),
  );
}
function datasetIdentity(dataset) {
  return {
    id: dataset.id,
    symbol: dataset.symbol,
    first: dataset.first,
    last: dataset.last,
    checksum: dataset.checksum,
    registered_at: dataset.registered_at || null,
    source: dataset.source || null,
    contract: dataset.contract || null,
    query: dataset.query || null,
  };
}
function datasetQueryShape(query) {
  if (typeof query === "string") {
    try { query = JSON.parse(query); } catch { return { raw: query }; }
  }
  return {
    dataset: query?.dataset || null,
    schema: query?.schema || null,
    symbols: query?.symbols || [],
    stype_in: query?.stype_in || null,
    stype_out: query?.stype_out || null,
    encoding: query?.encoding || null,
    compression: query?.compression || null,
    provenance: query?.provenance || null,
  };
}
function compatibleDataset(original, candidate) {
  return candidate.symbol === original.symbol &&
    (candidate.contract || null) === (original.contract || null) &&
    (candidate.source || null) === (original.source || null) &&
    same(datasetQueryShape(candidate.query), datasetQueryShape(original.query));
}
function frozenDataset(current, id) {
  const expected = (campaign.frozen_datasets || []).find((dataset) => dataset.id === id);
  const actual = (current.datasets || []).find((dataset) => dataset.id === id);
  if (!expected) throw new Error(`Dataset ${id} was not registered when this campaign was frozen`);
  if (!actual) throw new Error(`Frozen dataset ${id} is no longer registered`);
  if (!same(datasetIdentity(actual), expected))
    throw new Error(`Frozen dataset ${id} changed after the campaign was frozen`);
  return actual;
}
function requestDatasetId(task, kind) {
  return kind === "evaluation" ? task.request.base.dataset_id : task.request.dataset_id;
}
function isSourceDrift(error) {
  return /strategy changed(?: since discovery)?|execution source changed|source changed after the refresh was frozen/i.test(String(error.message || error));
}
function isTransient(error) {
  if (Number.isInteger(error.status)) return error.status >= 500;
  return /fetch failed|network|socket|ECONN(?:RESET|REFUSED|ABORTED)|ETIMEDOUT|EAI_AGAIN/i.test(String(error?.message || error));
}
async function retryTransient(operation, action) {
  for (;;) {
    try {
      return await operation();
    } catch (error) {
      if (!isTransient(error)) throw error;
      campaign.events = [...(campaign.events || []), {
        at: stamp(),
        action: "transient-api-error; retrying",
        operation: action,
        error: String(error.message || error),
      }];
      campaign.last_transient_error = { at: stamp(), operation: action, message: String(error.message || error) };
      save();
      await new Promise((resolveDone) => setTimeout(resolveDone, 15000));
    }
  }
}
function retryTask(task, error, action) {
  task.status = "planned";
  task.events = [...(task.events || []), { at: stamp(), action, error: String(error.message || error) }];
  save();
}
async function ensureStable({ allowCampaignActive = true, refreshDiscovery = false } = {}) {
  assertFrozenRuntime();
  if (refreshDiscovery) await call("/discover", { method: "POST", body: {} });
  assertFrozenRuntime();
  const current = await state();
  const actual = sourceIdentity(current.strategies);
  if (!same(actual, campaign.source_identity))
    throw new Error("Current execution source changed after the refresh was frozen. No further submissions were made.");
  const submitted = new Set([
    ...campaign.direct.flatMap((task) => task.new_run_ids || []),
    ...campaign.extensions.flatMap((task) => task.new_run_ids || []),
    ...legacyCampaignRunIds(),
  ]);
  const campaignEvaluationIds = new Set(
    campaign.evaluations.map((task) => task.new_evaluation_id).filter(Boolean),
  );
  const campaignRegimeIds = new Set(
    campaign.evaluations.flatMap((task) => (task.regimes || []).map((regime) => regime.new_regime_id).filter(Boolean)),
  );
  const campaignEvaluation = (evaluation) =>
    campaignEvaluationIds.has(evaluation.id) ||
    campaign.evaluations.some((task) =>
      markedWithExactPrefix(evaluation.hypothesis, `[${marker("evaluation", task.id, submissionAttempt(task))}]`),
    );
  const knownEvaluationIds = new Set([
    ...campaignEvaluationIds,
    ...(current.evaluations || []).filter(campaignEvaluation).map((evaluation) => evaluation.id),
  ]);
  const campaignRun = (run) =>
    submitted.has(run.id) ||
    knownEvaluationIds.has(run.input.research?.evaluation_id) ||
    [...campaign.direct, ...campaign.extensions].some((task) =>
      markedWithExactPrefix(run.input?.hypothesis, `[${marker(task.extension ? "extension" : "direct", task.id, submissionAttempt(task))}]`),
    );
  const externalRuns = active(current.runs).filter((run) => !campaignRun(run));
  const externalEvaluations = active(current.evaluations || []).filter((evaluation) => !campaignEvaluation(evaluation));
  const externalRegimes = active(current.regimes || []).filter((regime) => !campaignRegimeIds.has(regime.id) && !knownEvaluationIds.has(regime.evaluation_id));
  if (!allowCampaignActive && (externalRuns.length || externalEvaluations.length || externalRegimes.length))
    throw new Error(`External work became active: ${[
      ...externalRuns.map((run) => run.id),
      ...externalEvaluations.map((evaluation) => evaluation.id),
      ...externalRegimes.map((regime) => regime.id),
    ].join(", ")}`);
  return current;
}
function campaignActivity(current) {
  const submittedRuns = new Set([
    ...campaign.direct.flatMap((task) => task.new_run_ids || []),
    ...campaign.extensions.flatMap((task) => task.new_run_ids || []),
    ...legacyCampaignRunIds(),
  ]);
  const evaluationIds = new Set(campaign.evaluations.map((task) => task.new_evaluation_id).filter(Boolean));
  const regimeIds = new Set(campaign.evaluations.flatMap((task) => (task.regimes || []).map((regime) => regime.new_regime_id).filter(Boolean)));
  const markedCampaignRun = (run) => [...campaign.direct, ...campaign.extensions].some((task) =>
    markedWithExactPrefix(run.input?.hypothesis, `[${marker(task.extension ? "extension" : "direct", task.id, submissionAttempt(task))}]`),
  );
  const markedCampaignEvaluation = (evaluation) => campaign.evaluations.some((task) =>
    markedWithExactPrefix(evaluation.hypothesis, `[${marker("evaluation", task.id, submissionAttempt(task))}]`),
  );
  const knownEvaluationIds = new Set([
    ...evaluationIds,
    ...(current.evaluations || []).filter(markedCampaignEvaluation).map((evaluation) => evaluation.id),
  ]);
  return {
    runs: active(current.runs).filter((run) =>
      submittedRuns.has(run.id) || knownEvaluationIds.has(run.input.research?.evaluation_id) || markedCampaignRun(run),
    ),
    evaluations: active(current.evaluations || []).filter((evaluation) => evaluationIds.has(evaluation.id) || markedCampaignEvaluation(evaluation)),
    regimes: active(current.regimes || []).filter((regime) => regimeIds.has(regime.id) || knownEvaluationIds.has(regime.evaluation_id)),
  };
}
function taskByMarker(runs, kind, task) {
  const prefix = `[${marker(kind, task.id, submissionAttempt(task))}]`;
  return (runs || []).filter((run) => markedWithExactPrefix(run.input?.hypothesis, prefix));
}
function classificationTags(value) {
  const allowed = new Set(["stress", "sensitivity", "benchmark"]);
  return [...new Set(
    String(value || "")
      .toLowerCase()
      .split(/[\s,]+/)
      .filter((tag) => allowed.has(tag)),
  )];
}
function annotation(task, kind) {
  const origins = (task.source_run_ids || [task.source_run_id]).filter(Boolean).join(", ");
  const mappings = task.request.mappings?.length
    ? ` Compatibility mapping: ${JSON.stringify(task.request.mappings)}.`
    : "";
  return {
    tags: [campaignId, kind, ...classificationTags(task.original_tags)].join(", "),
    notes: trim(`Current-source ${kind} created for original run(s) ${origins}. Original evidence remains immutable. ${mappings} Do not inherit old readiness reviews, stage assessments, or pass/fail claims.`, 10000),
  };
}
function evaluationChildSlots(evaluation, runs) {
  return (evaluation.folds || []).flatMap((fold) => [
    ...(fold.training || []).map((runId, slot) => {
      const research = runs.get(runId)?.input?.research || {};
      return {
        source_run_id: runId,
        fold: research.fold ?? fold.index,
        role: research.role || "Training",
        candidate: research.candidate ?? slot,
        scenario: research.scenario || "Training",
        slot,
        source_execution_source_hash: runHash(runs.get(runId)),
      };
    }),
    ...(fold.tests || []).map((runId, slot) => {
      const research = runs.get(runId)?.input?.research || {};
      return {
        source_run_id: runId,
        fold: research.fold ?? fold.index,
        role: research.role || "Test",
        candidate: research.candidate ?? null,
        scenario: research.scenario || evaluation.scenarios?.[slot] || null,
        slot,
        source_execution_source_hash: runHash(runs.get(runId)),
      };
    }),
  ]);
}

function archivePriorAttempt(task, run, kind, disposition, extra = {}) {
  const runId = run?.id || extra.run_id || null;
  const existing = task.prior_attempts || [];
  if (existing.some((entry) => entry.run_id === runId && entry.disposition === disposition)) return false;
  task.prior_attempts = [...existing, {
    at: stamp(),
    kind,
    disposition,
    run_id: runId,
    status: run?.status || extra.status || null,
    created_at: run?.created_at || extra.created_at || null,
    started_at: run?.started_at || extra.started_at || null,
    ended_at: run?.ended_at || extra.ended_at || null,
    app_build_hash: run?.input?.app_build_hash || extra.app_build_hash || null,
    execution_source_hash: runHash(run) || extra.execution_source_hash || null,
    snapshot_hash: run?.input?.snapshot_hash || extra.snapshot_hash || null,
    source_snapshot: run?.input?.source_snapshot || run?.input?.source_dir || extra.source_snapshot || null,
    hypothesis: run?.input?.hypothesis || extra.hypothesis || null,
    submitted_source: extra.submitted_source || task.submitted_source || null,
    artifact_verification: extra.artifact_verification || task.current_artifact_verification || task.reused_artifacts || null,
    reason: extra.reason || null,
  }];
  return true;
}
function resetForStableRuntimeRetry(task, kind, reason) {
  const previousAttempt = Number.isInteger(task.attempt) ? task.attempt : 1;
  delete task.new_run_ids;
  delete task.reused_run_id;
  delete task.reused_artifacts;
  delete task.current_artifact_verification;
  delete task.execution_status;
  delete task.submitted_at;
  delete task.submitted_source;
  delete task.intent_at;
  delete task.annotation_error;
  task.status = "planned";
  task.attempt = Math.max(2, previousAttempt + 1);
  task.events = [...(task.events || []), {
    at: stamp(),
    action: "superseded-runtime-fingerprint; reset-for-stable-retry",
    kind,
    reason,
    next_attempt: task.attempt,
  }];
}
function legacyScan(current) {
  const tasks = [
    ...campaign.direct.map((task) => ({ task, kind: "direct" })),
    ...campaign.extensions.map((task) => ({ task, kind: "extension" })),
  ];
  return tasks
    .map(({ task, kind }) => {
      const runs = legacyTaskRuns(current.runs, kind, task);
      return runs.length ? {
        task_id: task.id,
        kind,
        legacy_marker: legacyMarker(kind, task.id),
        run_ids: runs.map((run) => run.id),
        runs: runs.map((run) => ({
          id: run.id,
          status: run.status,
          created_at: run.created_at,
          started_at: run.started_at || null,
          ended_at: run.ended_at || null,
          app_build_hash: run.input?.app_build_hash || null,
          execution_source_hash: runHash(run),
          snapshot_hash: run.input?.snapshot_hash || null,
          source_snapshot: run.input?.source_snapshot || run.input?.source_dir || null,
          hypothesis: run.input?.hypothesis || null,
        })),
      } : null;
    })
    .filter(Boolean);
}
async function migrateRuntimeFingerprint() {
  const runtime = currentRuntimeIdentity();
  let changed = false;
  if (!campaign.runtime_identity) {
    campaign.runtime_identity = runtime;
    campaign.runtime_frozen_at = stamp();
    campaign.schema_version = Math.max(Number(campaign.schema_version) || 1, 2);
    changed = true;
  } else if (!same(campaign.runtime_identity, runtime)) {
    campaign.runtime_drift = { at: stamp(), expected: campaign.runtime_identity, actual: runtime };
    save();
    throw new Error("Current application build or Python dependency environment changed after the campaign was frozen. No further submissions were made.");
  }
  const current = await state();
  const entries = legacyScan(current);
  if (!campaign.legacy_migration) {
    campaign.legacy_migration = {
      started_at: stamp(),
      frozen_runtime_identity: campaign.runtime_identity,
      disposition: "superseded-runtime-fingerprint",
      tasks: [],
      anomalies: [],
    };
    changed = true;
  }
  const migration = campaign.legacy_migration;
  migration.last_scanned_at = stamp();
  migration.tasks = entries;
  migration.anomalies = entries
    .filter((entry) => entry.run_ids.length !== 1)
    .map((entry) => ({ task_id: entry.task_id, kind: entry.kind, reason: `Expected one legacy marker match, found ${entry.run_ids.length}`, run_ids: entry.run_ids }));
  const activeLegacy = entries.flatMap((entry) => entry.runs.filter((run) => activeStatuses.has(run.status)));
  migration.waiting_for_legacy_terminal = activeLegacy.length > 0;
  migration.active_run_ids = activeLegacy.map((run) => run.id);
  changed = true;
  if (activeLegacy.length) {
    migration.last_barrier_at = stamp();
    save();
    return { current, waiting: true };
  }
  if (!migration.completed_at) {
    const liveRuns = new Map(current.runs.map((run) => [run.id, run]));
    const taskById = new Map([
      ...campaign.direct.map((task) => [task.id, { task, kind: "direct" }]),
      ...campaign.extensions.map((task) => [task.id, { task, kind: "extension" }]),
    ]);
    for (const entry of entries) {
      const target = taskById.get(entry.task_id);
      if (!target) continue;
      for (const runId of entry.run_ids) {
        const run = liveRuns.get(runId);
        archivePriorAttempt(target.task, run, target.kind, "superseded-runtime-fingerprint", {
          run_id: runId,
          reason: "The first refresh attempt was created while mutable campaign state changed the application build fingerprint.",
          hypothesis: entry.legacy_marker,
        });
      }
      resetForStableRuntimeRetry(target.task, target.kind, "Legacy unversioned attempt did not use the stable frozen runtime fingerprint.");
    }
    for (const task of campaign.direct) {
      if (task.status !== "reused") continue;
      const run = task.reused_run_id ? liveRuns.get(task.reused_run_id) : null;
      if (run && runtimeMatchesInput(run.input, campaign.runtime_identity)) continue;
      archivePriorAttempt(task, run, "direct", "stale-runtime-reuse", {
        run_id: task.reused_run_id || null,
        reason: "A source-compatible pre-existing result did not match the frozen application build and dependency environment.",
        artifact_verification: task.reused_artifacts || null,
      });
      resetForStableRuntimeRetry(task, "direct", "Pre-existing reused result predates the frozen runtime fingerprint.");
    }
    migration.completed_at = stamp();
    migration.waiting_for_legacy_terminal = false;
    migration.active_run_ids = [];
    migration.replacement_retry_task_ids = entries.map((entry) => entry.task_id);
    changed = true;
  }
  if (changed) save();
  return { current, waiting: false };
}

async function initialize() {
  if (campaign) {
    if (existsSync(join(folder, "ORIGINAL_STATE.json"))) {
      const original = readJson(join(folder, "ORIGINAL_STATE.json"));
      if (!campaign.frozen_datasets) campaign.frozen_datasets = original.datasets.map(datasetIdentity);
      if (!campaign.limits) campaign.limits = original.limits || { concurrency: 2, maxBatch: 24 };
      const sourceRuns = new Map(original.runs.map((run) => [run.id, run]));
      for (const task of campaign.evaluations || []) {
        if (!task.source_child_slots) task.source_child_slots = evaluationChildSlots(task.original, sourceRuns);
        if (task.expected && !task.expected.dataset_checksum)
          task.expected.dataset_checksum = task.original?.candidates?.[0]?.dataset?.checksum || null;
      }
      save();
    }
    await migrateRuntimeFingerprint();
    return campaign;
  }
  await call("/discover", { method: "POST", body: {} });
  const snapshot = await state(true);
  if (active(snapshot.runs).length || active(snapshot.evaluations || []).length || active(snapshot.regimes || []).length)
    throw new Error("Wait for the current Workbench queue, evaluation coordinator, and regime analysis coordinator to become idle before freezing this campaign");
  const runtime = currentRuntimeIdentity();
  const strategies = new Map(snapshot.strategies.map((strategy) => [strategy.id, strategy]));
  const datasets = new Map(snapshot.datasets.map((dataset) => [dataset.id, dataset]));
  const sourceRuns = new Map(snapshot.runs.map((run) => [run.id, run]));
  const directCandidates = snapshot.runs.filter((run) =>
    run.status === "Succeeded" && !run.input.research && !run.input.portfolio_replay && run.input.stage !== "Tracking" && !currentRun(run, strategies.get(run.input.strategy.id), runtime),
  );
  const currentDirect = snapshot.runs.filter((run) =>
    run.status === "Succeeded" && !run.input.research && !run.input.portfolio_replay && run.input.stage !== "Tracking" && currentRun(run, strategies.get(run.input.strategy.id), runtime),
  );
  const blocked = [];
  const groups = new Map();
  for (const run of directCandidates) {
    const strategy = strategies.get(run.input.strategy.id);
    try {
      if (!strategy) throw new Error("Current strategy is no longer registered");
      if (!datasets.has(run.input.dataset.id)) throw new Error("Original dataset is no longer registered");
      if (!sourceFolder(run.input) || !existsSync(sourceFolder(run.input))) throw new Error("Preserved source snapshot is unavailable");
      if (!existsSync(join(artifactFolder(run.id), "manifest.json"))) throw new Error("Run manifest is unavailable");
      const request = makeRunRequest(run, strategy);
      const key = request.signature;
      if (!groups.has(key)) groups.set(key, { request, runs: [] });
      groups.get(key).runs.push(run);
    } catch (error) {
      blocked.push({ source_run_id: run.id, reason: String(error.message || error) });
    }
  }
  const direct = [];
  for (const [key, group] of groups) {
    const id = `direct-${key.slice(0, 16)}`;
    const matching = currentDirect.filter((run) => {
      const strategy = strategies.get(run.input.strategy.id);
      try { return strategy && currentRequest(run, strategy).signature === key; } catch { return false; }
    });
    const task = {
      id,
      source_run_ids: group.runs.map((run) => run.id),
      request: group.request,
      original_tags: [...new Set(group.runs.map((run) => run.tags || "").filter(Boolean))].join(","),
      original: group.runs.map((run) => ({
        id: run.id,
        created_at: run.created_at,
        status: run.status,
        metrics: metricSubset(run.result?.metrics),
        warnings: run.result?.warnings || [],
        hypothesis: run.input.hypothesis || "",
        criteria: run.input.criteria || "",
        baseline: baselineRun(run),
      })),
      status: "planned",
      attempt: 1,
    };
    if (matching.length === 1) {
      try {
        task.reused_run_id = matching[0].id;
        task.reused_artifacts = verifyManifest(matching[0].id, matching[0]);
        task.new_run_ids = [matching[0].id];
        task.status = "reused";
      } catch (error) {
        task.status = "blocked";
        task.blocker = `Existing current replacement could not be verified: ${String(error.message || error)}`;
      }
    } else if (matching.length > 1) {
      task.status = "blocked";
      task.blocker = `Multiple current replacement candidates: ${matching.map((run) => run.id).join(", ")}`;
    }
    direct.push(task);
  }
  const evaluations = [];
  for (const evaluation of snapshot.evaluations || []) {
    if (evaluation.status !== "Succeeded") continue;
    const candidate = evaluation.candidates?.[0];
    const strategy = candidate && strategies.get(candidate.strategy.id);
    if (!candidate || !strategy || currentEvaluation(evaluation, strategy, runtime)) continue;
    const task = { id: `evaluation-${evaluation.id}`, source_evaluation_id: evaluation.id, original: evaluation, status: "planned", attempt: 1, regimes: [] };
    try {
      if (evaluation.candidates.length !== 1) throw new Error("Only singleton saved candidate evaluations are automatically reconstructible");
      const base = makeRunRequest({ input: candidate }, strategy);
      const first = evaluation.folds[0];
      if (!first) throw new Error("Evaluation has no folds");
      const request = {
        name: trim(`${campaignId} | ${short(evaluation.id)} | ${evaluation.name || "saved evaluation"}`, 120),
        base: launchBody(base, "evaluation-base", task),
        sweep: {},
        train_days: inclusiveDays(first.train_start, first.train_end),
        test_days: inclusiveDays(first.test_start, first.test_end),
        folds: evaluation.folds.length,
        metric: evaluation.metric,
        min_trades: evaluation.min_trades,
        min_return: evaluation.min_return,
        max_drawdown: evaluation.max_drawdown,
        min_test_trades: evaluation.min_test_trades,
        stress_multiple: evaluation.stress_multiple,
        delay_bars: evaluation.delay_bars,
        hypothesis: markedHypothesis("evaluation", task.id, evaluation.hypothesis || "", submissionAttempt(task)),
      };
      task.request = request;
      task.expected = {
        jobs: evaluation.jobs,
        scenarios: evaluation.scenarios || [],
        folds: evaluation.folds.map(({ index, train_start, train_end, test_start, test_end }) => ({ index, train_start, train_end, test_start, test_end })),
        parameters: base.parameters,
        dataset_checksum: candidate.dataset.checksum,
      };
      task.source_child_slots = evaluationChildSlots(evaluation, sourceRuns);
      task.regimes = (snapshot.regimes || [])
        .filter((regime) => regime.status === "Succeeded" && regime.evaluation_id === evaluation.id)
        .map((regime) => ({
          id: `regime-${regime.id}`,
          source_regime_id: regime.id,
          request: { feature: regime.feature, window: regime.window, quantile: regime.quantile, seed: regime.seed },
          status: "planned",
        }));
    } catch (error) {
      task.status = "blocked";
      task.blocker = String(error.message || error);
    }
    evaluations.push(task);
  }
  const trackingPath = join(stateRoot, "collective", "tracking.json");
  const collectiveIndex = join(stateRoot, "collective", "index.json");
  const backupPath = "G:\\QuantBackups\\strategy-workbench\\current-source-refresh-2026-09-30\\BACKUP.json";
  campaign = {
    schema_version: 1,
    id: campaignId,
    created_at: stamp(),
    api,
    source_identity: sourceIdentity(snapshot.strategies),
    runtime_identity: runtime,
    runtime_frozen_at: stamp(),
    snapshot: {
      visible_runs: snapshot.runs.length,
      succeeded_runs: snapshot.runs.filter((run) => run.status === "Succeeded").length,
      datasets: snapshot.datasets.map((dataset) => ({ id: dataset.id, symbol: dataset.symbol, first: dataset.first, last: dataset.last, checksum: dataset.checksum })),
      archived_runs_excluded: 56,
      canceled_evaluation_children_excluded: snapshot.runs.filter((run) => run.status === "Succeeded" && run.input.research?.evaluation_id && (snapshot.evaluations || []).some((evaluation) => evaluation.id === run.input.research.evaluation_id && evaluation.status !== "Succeeded")).map((run) => run.id),
    },
    frozen_datasets: snapshot.datasets.map(datasetIdentity),
    limits: snapshot.limits || { concurrency: 2, maxBatch: 24 },
    compatibility_mappings: knownLegacyMappings,
    backup: existsSync(backupPath) ? readJson(backupPath) : { path: backupPath, status: "External backup manifest was unavailable during initialization" },
    portfolio_before: {
      tracking: existsSync(trackingPath) ? readJson(trackingPath) : null,
      index_path: collectiveIndex,
      named_combinations: "No named combinations were present in the audited Edge/Chrome local-storage profiles; browser storage is not written by this campaign.",
    },
    direct,
    evaluations,
    extensions: [],
    blocked,
    events: [{ at: stamp(), action: "initialized", direct_candidates: directCandidates.length, direct_tasks: direct.length, completed_evaluations: evaluations.length }],
  };
  writeJson("ORIGINAL_STATE.json", snapshot);
  if (existsSync(collectiveIndex)) writeJson("COLLECTIVE_INDEX_BEFORE.json", readJson(collectiveIndex));
  if (existsSync(trackingPath)) writeJson("PORTFOLIO_TRACKING_BEFORE.json", readJson(trackingPath));
  save();
  return campaign;
}

function assertPreview(task, preview) {
  assert.equal(preview.jobs, 1, `Expected one job for ${task.id}`);
  assert(same(preview.parameters?.[0], task.request.parameters), `Resolved parameter mismatch for ${task.id}`);
  const insufficient = (preview.warmup || []).filter((entry) => entry?.status === "insufficient");
  assert(!insufficient.length, `Warmup is insufficient for ${task.id}: ${JSON.stringify(insufficient)}`);
}
function blockTask(task, error, action) {
  task.status = "blocked";
  task.blocker = String(error.message || error);
  task.events = [...(task.events || []), { at: stamp(), action, error: task.blocker }];
  save();
}
async function reconcileUncertainRunSubmission(task, kind, error) {
  task.events = [...(task.events || []), { at: stamp(), action: "submission-response-error", error: String(error.message || error) }];
  save();
  const current = await state();
  await reconcileDirect(current, { preserveSubmitting: true });
  if (task.status !== "submitting") {
    save();
    return;
  }
  if (Number.isInteger(error.status) && error.status < 500) {
    blockTask(task, error, "submission-rejected");
    return;
  }
  task.status = "planned";
  task.events = [...(task.events || []), { at: stamp(), action: "submission-unconfirmed; reset-to-planned", kind }];
  save();
}
async function reconcileDirect(current, { preserveSubmitting = false } = {}) {
  if (legacyMigrationBarrier()) return;
  for (const task of [...campaign.direct, ...campaign.extensions]) {
    if (task.status === "reused" || task.status === "blocked") continue;
    const kind = task.extension ? "extension" : "direct";
    const found = taskByMarker(current.runs, kind, task);
    if (found.length === 1) {
      assertRuntimeInput(found[0].input, `${task.id} reconciliation`);
      task.new_run_ids = [found[0].id];
      task.status = found[0].status === "Succeeded" ? "succeeded" : terminalStatuses.has(found[0].status) ? "failed" : "submitted";
    } else if (found.length > 1) {
      task.status = "blocked";
      task.blocker = `Ambiguous submitted runs: ${found.map((run) => run.id).join(", ")}`;
    } else if (task.status === "submitting" && !preserveSubmitting) {
      task.status = "planned";
      task.events = [...(task.events || []), { at: stamp(), action: "submission-not-found; reset-to-planned" }];
    }
  }
}
async function launchRuns(tasks, kind, limit = Infinity) {
  if (legacyMigrationBarrier()) return 0;
  let submitted = 0;
  let current = await ensureStable({ allowCampaignActive: false, refreshDiscovery: true });
  for (const task of tasks.filter((task) => task.status === "planned")) frozenDataset(current, requestDatasetId(task, kind));
  await reconcileDirect(current);
  for (const task of tasks) {
    if (submitted >= limit) break;
    if (task.status !== "planned") continue;
    if (submitted % 12 === 0) {
      current = await ensureStable({ allowCampaignActive: false, refreshDiscovery: true });
      frozenDataset(current, requestDatasetId(task, kind));
      await reconcileDirect(current);
      if (task.status !== "planned") continue;
    }
    task.status = "submitting";
    task.intent_at = stamp();
    save();
    const body = launchBody(task.request, kind, task);
    let preview;
    try {
      preview = await call("/preview", { method: "POST", body });
      assertPreview(task, preview);
    } catch (error) {
      if (isSourceDrift(error)) throw error;
      if (isTransient(error)) retryTask(task, error, "preview-transient-error");
      else blockTask(task, error, "preview-rejected");
      continue;
    }
    task.preview = { at: stamp(), jobs: preview.jobs, parameters: preview.parameters, warmup: preview.warmup };
    save();
    current = await ensureStable({ allowCampaignActive: false, refreshDiscovery: true });
    frozenDataset(current, requestDatasetId(task, kind));
    await reconcileDirect(current, { preserveSubmitting: true });
    if (task.status !== "submitting") continue;
    let launched;
    try {
      launched = await call("/runs", { method: "POST", body });
    } catch (error) {
      if (isSourceDrift(error)) throw error;
      await reconcileUncertainRunSubmission(task, kind, error);
      continue;
    }
    assert(Array.isArray(launched), `Expected a run list while submitting ${task.id}`);
    assert.equal(launched.length, 1, `Expected one submitted run for ${task.id}`);
    const run = launched[0];
    const expected = campaign.source_identity[run.input.strategy.id]?.execution_source_hash;
    assert.equal(run.input.execution_source_hash || run.input.source_hash, expected, `Source drift while submitting ${task.id}`);
    assertRuntimeInput(run.input, `${task.id} (${run.id})`);
    task.new_run_ids = [run.id];
    task.status = "submitted";
    task.submitted_at = stamp();
    task.submitted_source = { execution_source_hash: run.input.execution_source_hash, snapshot_hash: run.input.snapshot_hash, app_build_hash: run.input.app_build_hash };
    save();
    try {
      await call(`/runs/${run.id}`, { method: "PATCH", body: annotation(task, kind === "extension" ? "exploratory-extension" : "current-source-retest") });
      task.annotation_at = stamp();
    } catch (error) {
      task.annotation_error = String(error.message || error);
      save();
    }
    submitted++;
  }
  campaign.events.push({ at: stamp(), action: `launch-${kind}`, submitted });
  save();
  return submitted;
}
async function retryRunAnnotations() {
  let changed = false;
  for (const task of [...campaign.direct, ...campaign.extensions]) {
    const runId = task.new_run_ids?.[0];
    if (!runId || !task.annotation_error) continue;
    const kind = task.extension ? "exploratory-extension" : "current-source-retest";
    try {
      await call(`/runs/${runId}`, { method: "PATCH", body: annotation(task, kind) });
      delete task.annotation_error;
      task.annotation_at = stamp();
      task.annotation_retry_count = (task.annotation_retry_count || 0) + 1;
      changed = true;
    } catch (error) {
      task.annotation_error = String(error.message || error);
      task.annotation_retry_count = (task.annotation_retry_count || 0) + 1;
      if (task.extension && ["succeeded", "reused"].includes(task.status)) {
        task.status = "blocked";
        task.blocker = `Required exploratory-extension label could not be applied: ${task.annotation_error}`;
      }
      changed = true;
    }
  }
  if (changed) save();
}

function assertEvaluationPreview(task, preview, body = evaluationLaunchBody(task)) {
  const base = body.base;
  const candidate = preview.candidates?.[0];
  assert.equal(preview.name, body.name, `Name changed for ${task.id}`);
  assert.equal(preview.jobs, task.expected.jobs, `Job count changed for ${task.id}`);
  assert(same(preview.scenarios || [], task.expected.scenarios), `Scenario set changed for ${task.id}`);
  assert(candidate, `No resolved candidate returned for ${task.id}`);
  assert.equal(candidate.strategy?.id, base.strategy_id, `Strategy changed for ${task.id}`);
  assert.equal(candidate.dataset?.id, base.dataset_id, `Dataset changed for ${task.id}`);
  assert.equal(candidate.dataset?.checksum, task.expected.dataset_checksum, `Dataset checksum changed for ${task.id}`);
  for (const field of ["start", "end", "timeframe", "session", "capital", "fee", "slippage", "warmup_days", "timeout", "delay_bars"])
    assert.equal(candidate[field], base[field], `${field} changed for ${task.id}`);
  assert.equal(candidate.stage, "Exploratory", `Evaluation candidate stage changed for ${task.id}`);
  assert.equal(candidate.development_end, "", `Evaluation candidate development boundary changed for ${task.id}`);
  assert.equal(candidate.criteria, "", `Evaluation candidate criteria changed for ${task.id}`);
  assert.equal(candidate.hypothesis, base.hypothesis, `Evaluation candidate hypothesis changed for ${task.id}`);
  assert(same(candidate.parameters, task.expected.parameters), `Candidate settings changed for ${task.id}`);
  const folds = preview.folds.map(({ index, train_start, train_end, test_start, test_end }) => ({ index, train_start, train_end, test_start, test_end }));
  assert(same(folds, task.expected.folds), `Fold dates changed for ${task.id}`);
  for (const field of ["metric", "min_trades", "min_return", "max_drawdown", "min_test_trades", "stress_multiple", "delay_bars", "hypothesis"])
    assert.equal(preview[field], body[field], `${field} changed for ${task.id}`);
}
async function reconcileEvaluations(current, { preserveSubmitting = false } = {}) {
  for (const task of campaign.evaluations) {
    if (["blocked", "reused"].includes(task.status)) continue;
    const prefix = `[${marker("evaluation", task.id, submissionAttempt(task))}]`;
    const found = (current.evaluations || []).filter((evaluation) => markedWithExactPrefix(evaluation.hypothesis, prefix));
    if (found.length === 1) {
      assertRuntimeInput(found[0], `${task.id} reconciliation`);
      task.new_evaluation_id = found[0].id;
      task.status = found[0].status === "Succeeded" ? "succeeded" : terminalStatuses.has(found[0].status) ? "failed" : "submitted";
    } else if (found.length > 1) {
      task.status = "blocked";
      task.blocker = `Ambiguous submitted evaluations: ${found.map((evaluation) => evaluation.id).join(", ")}`;
    } else if (task.status === "submitting" && !preserveSubmitting) {
      task.status = "planned";
    }
  }
}
function updateEvaluationIntegrity(task) {
  const invalid = (task.child_mappings || []).filter((mapping) =>
    mapping.status === "blocked" && ((mapping.validation_errors || []).length || mapping.reason || mapping.verification_error),
  );
  const unresolved = task.status === "succeeded"
    ? (task.child_mappings || []).filter((mapping) => mapping.status !== "succeeded")
    : [];
  task.integrity_blocker = invalid.length || unresolved.length
    ? `Replacement evaluation child lineage is incomplete or invalid: ${[...invalid, ...unresolved].map((mapping) => `${mapping.source_run_id}: ${(mapping.validation_errors || [mapping.verification_error || mapping.explicit_blocker || mapping.reason || mapping.status]).join("; ")}`).join(" | ")}`
    : null;
  if (task.integrity_blocker && (task.status === "succeeded" || task.execution_status === "Succeeded")) {
    task.status = "blocked";
    task.blocker = task.integrity_blocker;
  }
}
function reconcileEvaluationChildren(current) {
  const evaluations = new Map((current.evaluations || []).map((evaluation) => [evaluation.id, evaluation]));
  const runs = new Map(current.runs.map((run) => [run.id, run]));
  for (const task of campaign.evaluations) {
    if (!task.source_child_slots) continue;
    const previous = new Map((task.child_mappings || []).map((mapping) => [mapping.source_run_id, mapping]));
    if (!task.new_evaluation_id) {
      const parentTerminal = ["failed", "blocked"].includes(task.status);
      task.child_mappings = task.source_child_slots.map((slot) => {
        const prior = previous.get(slot.source_run_id);
        const reason = parentTerminal
          ? `Replacement evaluation ${task.status} before this source child could be recreated.`
          : "Replacement evaluation has not been created yet.";
        return {
          ...slot,
          source_candidate: slot.candidate,
          replacement_evaluation_id: null,
          replacement_run_id: null,
          status: parentTerminal ? "not-created" : "pending",
          reason,
          explicit_blocker: parentTerminal ? reason : null,
          original_artifact_verification: prior?.original_artifact_verification,
          current_artifact_verification: prior?.current_artifact_verification,
        };
      });
      task.child_mapping_summary = Object.fromEntries(
        ["succeeded", "failed", "blocked", "submitted", "pending", "not-created"]
          .map((status) => [status, task.child_mappings.filter((mapping) => mapping.status === status).length]),
      );
      updateEvaluationIntegrity(task);
      continue;
    }
    const replacement = evaluations.get(task.new_evaluation_id);
    const parentTerminal = terminalStatuses.has(replacement?.status);
    const expectedHash = campaign.source_identity[task.original?.candidates?.[0]?.strategy?.id]?.execution_source_hash;
    task.child_mappings = task.source_child_slots.map((slot) => {
      const fold = replacement?.folds?.find((candidate) => candidate.index === slot.fold);
      const ids = slot.role === "Training" ? fold?.training : fold?.tests;
      const replacementRunId = ids?.[slot.slot] || null;
      const replacementRun = replacementRunId ? runs.get(replacementRunId) : null;
      if (!replacementRunId) {
        return {
          ...slot,
          source_candidate: slot.candidate,
          replacement_evaluation_id: task.new_evaluation_id,
          replacement_run_id: null,
          status: parentTerminal ? "not-created" : "pending",
          reason: parentTerminal ? "Replacement evaluation became terminal before this child job was created." : "Replacement child job has not been created yet.",
          explicit_blocker: parentTerminal ? "Replacement evaluation became terminal before this child job was created." : null,
        };
      }
      if (!replacementRun) {
        return {
          ...slot,
          source_candidate: slot.candidate,
          replacement_evaluation_id: task.new_evaluation_id,
          replacement_run_id: replacementRunId,
          status: parentTerminal ? "blocked" : "pending",
          reason: "Replacement child run is not visible in the Workbench state.",
        };
      }
      const research = replacementRun.input.research || {};
      const errors = [];
      if (research.evaluation_id !== task.new_evaluation_id) errors.push("evaluation parent differs");
      if (research.fold !== slot.fold) errors.push("fold differs");
      if (research.role !== slot.role) errors.push("role differs");
      const replacementSelectedCandidate = fold?.selection?.candidate;
      if (slot.role === "Training" && slot.candidate !== null && research.candidate !== slot.candidate)
        errors.push("training candidate differs");
      if (slot.role === "Test") {
        if (!Number.isInteger(replacementSelectedCandidate)) errors.push("replacement fold has no selected candidate");
        else if (research.candidate !== replacementSelectedCandidate) errors.push("test candidate differs from replacement fold selection");
      }
      if (slot.scenario !== null && research.scenario !== slot.scenario) errors.push("scenario differs");
      if (expectedHash && runHash(replacementRun) !== expectedHash) errors.push("execution source differs");
      if (!runtimeMatchesInput(replacementRun.input, campaign.runtime_identity)) errors.push("runtime fingerprint differs");
      return {
        ...slot,
        source_candidate: slot.candidate,
        replacement_selected_candidate: Number.isInteger(replacementSelectedCandidate) ? replacementSelectedCandidate : null,
        replacement_evaluation_id: task.new_evaluation_id,
        replacement_run_id: replacementRunId,
        replacement_status: replacementRun.status,
        status: errors.length ? "blocked" : replacementRun.status === "Succeeded" ? "succeeded" : terminalStatuses.has(replacementRun.status) ? "failed" : "submitted",
        validation_errors: errors,
      };
    }).map((mapping) => {
      const prior = previous.get(mapping.source_run_id);
      const preserved = {
        original_artifact_verification: prior?.original_artifact_verification,
        current_artifact_verification: prior?.current_artifact_verification,
      };
      if (prior?.current_artifact_verification?.status === "failed") {
        return {
          ...mapping,
          ...preserved,
          status: "blocked",
          verification_error: `Replacement child artifact verification failed: ${prior.current_artifact_verification.error}`,
        };
      }
      return { ...mapping, ...preserved };
    });
    task.child_mapping_summary = Object.fromEntries(
      ["succeeded", "failed", "blocked", "submitted", "pending", "not-created"]
        .map((status) => [status, task.child_mappings.filter((mapping) => mapping.status === status).length]),
    );
    updateEvaluationIntegrity(task);
  }
}
async function reconcileUncertainEvaluationSubmission(task, error) {
  task.events = [...(task.events || []), { at: stamp(), action: "submission-response-error", error: String(error.message || error) }];
  save();
  const current = await state();
  await reconcileEvaluations(current, { preserveSubmitting: true });
  if (task.status !== "submitting") {
    save();
    return;
  }
  if (Number.isInteger(error.status) && error.status < 500) {
    blockTask(task, error, "evaluation-submission-rejected");
    return;
  }
  task.status = "planned";
  task.events = [...(task.events || []), { at: stamp(), action: "evaluation-submission-unconfirmed; reset-to-planned" }];
  save();
}
async function launchEvaluations(limit = Infinity) {
  let submitted = 0;
  let current = await ensureStable({ allowCampaignActive: false, refreshDiscovery: true });
  for (const task of campaign.evaluations.filter((task) => task.status === "planned")) frozenDataset(current, requestDatasetId(task, "evaluation"));
  await reconcileEvaluations(current);
  for (const task of campaign.evaluations) {
    if (submitted >= limit) break;
    if (task.status !== "planned") continue;
    if (submitted % 6 === 0) {
      current = await ensureStable({ allowCampaignActive: false, refreshDiscovery: true });
      frozenDataset(current, requestDatasetId(task, "evaluation"));
      await reconcileEvaluations(current);
      if (task.status !== "planned") continue;
    }
    task.status = "submitting";
    task.intent_at = stamp();
    save();
    const body = evaluationLaunchBody(task);
    let preview;
    try {
      preview = await call("/evaluations/preview", { method: "POST", body });
      assertEvaluationPreview(task, preview, body);
    } catch (error) {
      if (isSourceDrift(error)) throw error;
      if (isTransient(error)) retryTask(task, error, "evaluation-preview-transient-error");
      else blockTask(task, error, "evaluation-preview-rejected");
      continue;
    }
    task.preview = { at: stamp(), jobs: preview.jobs, scenarios: preview.scenarios, folds: preview.folds };
    save();
    current = await ensureStable({ allowCampaignActive: false, refreshDiscovery: true });
    frozenDataset(current, requestDatasetId(task, "evaluation"));
    await reconcileEvaluations(current, { preserveSubmitting: true });
    if (task.status !== "submitting") continue;
    let launched;
    try {
      launched = await call("/evaluations", { method: "POST", body });
    } catch (error) {
      if (isSourceDrift(error)) throw error;
      await reconcileUncertainEvaluationSubmission(task, error);
      continue;
    }
    assert(launched && Array.isArray(launched.candidates) && launched.candidates.length === 1, `Expected one submitted evaluation candidate for ${task.id}`);
    assertEvaluationPreview(task, launched, body);
    const expected = campaign.source_identity[launched.candidates[0].strategy.id]?.execution_source_hash;
    assert.equal(launched.execution_source_hash || launched.source_hash, expected, `Source drift while submitting ${task.id}`);
    assertRuntimeInput(launched, `${task.id} (${launched.id})`);
    task.new_evaluation_id = launched.id;
    task.status = "submitted";
    task.submitted_at = stamp();
    task.submitted_source = { execution_source_hash: launched.execution_source_hash, snapshot_hash: launched.snapshot_hash, app_build_hash: launched.app_build_hash };
    save();
    submitted++;
  }
  campaign.events.push({ at: stamp(), action: "launch-evaluations", submitted });
  save();
  return submitted;
}

async function advanceOriginalWork(limit) {
  const migration = await migrateRuntimeFingerprint();
  if (migration.waiting || legacyMigrationBarrier())
    return { launched_direct: 0, launched_evaluations: 0, waiting: true, waiting_for_legacy_terminal: true };
  let current = await ensureStable({ allowCampaignActive: false });
  await reconcileDirect(current);
  await reconcileEvaluations(current);
  let activity = campaignActivity(current);
  if (activity.runs.length || activity.evaluations.length || activity.regimes.length)
    return { launched_direct: 0, launched_evaluations: 0, waiting: true };
  const direct = await launchRuns(campaign.direct, "direct", limit);
  if (direct)
    return { launched_direct: direct, launched_evaluations: 0, waiting: false };
  current = await ensureStable({ allowCampaignActive: false });
  await reconcileDirect(current);
  await reconcileEvaluations(current);
  activity = campaignActivity(current);
  if (activity.runs.length || activity.evaluations.length || activity.regimes.length)
    return { launched_direct: 0, launched_evaluations: 0, waiting: true };
  const evaluations = await launchEvaluations(limit);
  return { launched_direct: 0, launched_evaluations: evaluations, waiting: false };
}

async function syncStatus() {
  const migration = await migrateRuntimeFingerprint();
  const current = migration.current;
  if (legacyMigrationBarrier()) {
    campaign.last_status = {
      at: stamp(),
      active_runs: active(current.runs).length,
      active_evaluations: active(current.evaluations || []).length,
      active_regimes: active(current.regimes || []).length,
      waiting_for_legacy_terminal: true,
      legacy_active_run_ids: campaign.legacy_migration.active_run_ids || [],
    };
    save();
    return current;
  }
  await reconcileDirect(current);
  await reconcileEvaluations(current);
  const byId = new Map(current.runs.map((run) => [run.id, run]));
  for (const task of [...campaign.direct, ...campaign.extensions]) {
    const run = task.new_run_ids?.[0] && byId.get(task.new_run_ids[0]);
    if (!run || task.status === "reused" || task.status === "blocked") continue;
    task.execution_status = run.status;
    if (run.status === "Succeeded") task.status = "succeeded";
    else if (terminalStatuses.has(run.status)) task.status = "failed";
  }
  const evaluationById = new Map((current.evaluations || []).map((evaluation) => [evaluation.id, evaluation]));
  for (const task of campaign.evaluations) {
    const evaluation = task.new_evaluation_id && evaluationById.get(task.new_evaluation_id);
    if (!evaluation || task.status === "blocked") continue;
    task.execution_status = evaluation.status;
    if (evaluation.status === "Succeeded") task.status = "succeeded";
    else if (terminalStatuses.has(evaluation.status)) task.status = "failed";
  }
  await reconcileRegimes(current);
  reconcileEvaluationChildren(current);
  campaign.last_status = {
    at: stamp(),
    active_runs: active(current.runs).length,
    active_evaluations: active(current.evaluations || []).length,
    active_regimes: active(current.regimes || []).length,
    direct: Object.fromEntries(["planned", "submitting", "submitted", "succeeded", "failed", "reused", "blocked"].map((status) => [status, campaign.direct.filter((task) => task.status === status).length])),
    evaluations: Object.fromEntries(["planned", "submitting", "submitted", "succeeded", "failed", "blocked"].map((status) => [status, campaign.evaluations.filter((task) => task.status === status).length])),
  };
  save();
  return current;
}
function originalTerminal() {
  if (legacyMigrationBarrier()) return false;
  return [...campaign.direct, ...campaign.evaluations].every((task) => ["succeeded", "failed", "reused", "blocked"].includes(task.status));
}
function extensionTerminal() {
  return campaign.extensions.every((task) => ["succeeded", "failed", "reused", "blocked", "unavailable"].includes(task.status));
}
function regimesTerminal() {
  return campaign.evaluations
    .flatMap((task) => task.regimes)
    .every((task) => ["succeeded", "failed", "blocked"].includes(task.status));
}
async function createExtensions() {
  if (campaign.extensions.length) return 0;
  const current = await ensureStable({ allowCampaignActive: false });
  const strategies = new Map(current.strategies.map((strategy) => [strategy.id, strategy]));
  const frozen = new Map((campaign.frozen_datasets || []).map((dataset) => [dataset.id, dataset]));
  const extensions = [];
  const groups = new Map();
  for (const direct of campaign.direct) {
    if (!direct.original.some((run) => run.baseline)) continue;
    const unavailable = () => ({
      id: `extension-${direct.id}`,
      source_task_ids: [direct.id],
      source_task_id: direct.id,
      source_run_ids: direct.new_run_ids?.[0] ? [direct.new_run_ids[0]] : [],
      source_run_id: direct.new_run_ids?.[0] || null,
      extension: true,
      status: "planned",
      attempt: 1,
      original_tags: direct.original_tags || "",
    });
    if (!direct.new_run_ids?.[0] || !["succeeded", "reused"].includes(direct.status)) {
      const task = unavailable();
      task.status = "blocked";
      task.blocker = `No verified current-source original-window baseline is available because direct task ${direct.id} is ${direct.status}: ${direct.blocker || direct.execution_status || "no replacement run"}`;
      direct.extension_task_id = task.id;
      extensions.push(task);
      continue;
    }
    const run = await call(`/runs/${direct.new_run_ids[0]}`);
    const strategy = strategies.get(run.input.strategy.id);
    let task;
    try {
      if (!strategy) throw new Error("Current strategy is no longer registered");
      const requiredFirst = dateOffset(run.input.start, -Math.max(0, Number(run.input.warmup_days) || 0));
      const compatibleFrozen = current.datasets
        .map((dataset) => ({ dataset, frozen: frozen.get(dataset.id) }))
        .filter((candidate) => candidate.frozen && compatibleDataset(run.input.dataset, candidate.dataset));
      const mutatedFrozen = compatibleFrozen.filter((candidate) => !same(datasetIdentity(candidate.dataset), candidate.frozen));
      if (mutatedFrozen.length)
        throw new Error(`Compatible frozen dataset identity changed after the campaign freeze: ${mutatedFrozen.map((candidate) => candidate.dataset.id).join(", ")}`);
      const candidates = current.datasets
        .map((dataset) => ({ dataset, frozen: frozen.get(dataset.id) }))
        .filter((candidate) => candidate.frozen && same(datasetIdentity(candidate.dataset), candidate.frozen))
        .filter((candidate) => compatibleDataset(run.input.dataset, candidate.dataset) && candidate.dataset.first.slice(0, 10) <= requiredFirst)
        .map(({ dataset }) => ({ dataset, through: completedUtcThrough(dataset.last) }))
        .filter((candidate) => candidate.through)
        .sort((left, right) => right.through.localeCompare(left.through) || String(right.dataset.registered_at).localeCompare(String(left.dataset.registered_at)));
      const latest = candidates[0];
      task = unavailable();
      if (!latest || latest.through <= run.input.end) {
        task.status = "unavailable";
        task.blocker = latest ? `No newer complete data after ${run.input.end}; newest compatible frozen cutoff is ${latest.through}` : `No frozen compatible dataset covers required warmup start ${requiredFirst}`;
        direct.extension_task_id = task.id;
        extensions.push(task);
      } else {
        const request = makeRunRequest(run, strategy, { extension: true, dataset: latest.dataset, end: latest.through });
        const key = extensionKey(request);
        task = groups.get(key);
        if (task) {
          task.source_task_ids.push(direct.id);
          task.source_run_ids.push(run.id);
          task.original_tags = [task.original_tags, direct.original_tags || ""].filter(Boolean).join(",");
        } else {
          task = {
            ...unavailable(),
            id: `extension-${key.slice(0, 16)}`,
            request,
            extension_key: key,
            data: {
              id: latest.dataset.id,
              symbol: latest.dataset.symbol,
              cutoff: latest.through,
              required_first: requiredFirst,
              original_end: run.input.end,
              frozen_dataset: frozen.get(latest.dataset.id),
            },
          };
          groups.set(key, task);
          extensions.push(task);
        }
        direct.extension_task_id = task.id;
      }
    } catch (error) {
      task = unavailable();
      task.status = "blocked";
      task.blocker = String(error.message || error);
      direct.extension_task_id = task.id;
      extensions.push(task);
    }
  }
  campaign.extensions = extensions;
  campaign.events.push({ at: stamp(), action: "planned-extensions", tasks: extensions.length, launchable: extensions.filter((task) => task.status === "planned").length, deduplicated: [...groups.values()].reduce((count, task) => count + Math.max(0, task.source_task_ids.length - 1), 0) });
  save();
  return extensions.length;
}
async function reconcileRegimes(current, { preserveSubmitting = false } = {}) {
  for (const evaluationTask of campaign.evaluations) {
    if (["failed", "blocked"].includes(evaluationTask.status)) {
      for (const regime of evaluationTask.regimes) {
        if (["succeeded", "failed", "blocked"].includes(regime.status)) continue;
        regime.status = "blocked";
        regime.blocker = `Replacement evaluation ${evaluationTask.status}; a regime study cannot be recreated.`;
      }
      continue;
    }
    if (evaluationTask.status !== "succeeded" || !evaluationTask.new_evaluation_id) continue;
    for (const regime of evaluationTask.regimes) {
      if (["succeeded", "failed", "blocked"].includes(regime.status)) continue;
      const found = (current.regimes || []).filter((candidate) => candidate.evaluation_id === evaluationTask.new_evaluation_id && same({ feature: candidate.feature, window: candidate.window, quantile: candidate.quantile, seed: candidate.seed }, regime.request));
      if (found.length === 1) {
        regime.new_regime_id = found[0].id;
        regime.status = terminalStatuses.has(found[0].status) ? found[0].status === "Succeeded" ? "succeeded" : "failed" : "submitted";
      } else if (found.length > 1) {
        regime.status = "blocked";
        regime.blocker = `Ambiguous matching regimes: ${found.map((candidate) => candidate.id).join(", ")}`;
      } else if (regime.status === "submitting" && !preserveSubmitting) {
        regime.status = "planned";
      }
    }
  }
}
async function launchRegimes() {
  const current = await ensureStable({ allowCampaignActive: false, refreshDiscovery: true });
  await reconcileRegimes(current);
  let submitted = 0;
  const evaluations = new Map((current.evaluations || []).map((evaluation) => [evaluation.id, evaluation]));
  for (const evaluationTask of campaign.evaluations.filter((task) => task.status === "succeeded" && task.new_evaluation_id)) {
    const evaluation = evaluations.get(evaluationTask.new_evaluation_id);
    for (const regime of evaluationTask.regimes) {
      if (regime.status !== "planned") continue;
      if (evaluationTask.integrity_blocker) {
        regime.status = "blocked";
        regime.blocker = evaluationTask.integrity_blocker;
        save();
        continue;
      }
      if (!evaluation?.result || evaluation.outcome === "Inconclusive") {
        regime.status = "blocked";
        regime.blocker = "Replacement evaluation is inconclusive and has no completed result for a regime investigation.";
        save();
        continue;
      }
      regime.status = "submitting";
      regime.intent_at = stamp();
      save();
      let launched;
      try {
        launched = await call(`/evaluations/${evaluationTask.new_evaluation_id}/regimes`, { method: "POST", body: regime.request });
      } catch (error) {
        if (isSourceDrift(error)) throw error;
        regime.events = [...(regime.events || []), { at: stamp(), action: "submission-response-error", error: String(error.message || error) }];
        save();
        const after = await state();
        await reconcileRegimes(after, { preserveSubmitting: true });
        if (regime.status === "submitting") {
          if (Number.isInteger(error.status) && error.status < 500) {
            regime.status = "blocked";
            regime.blocker = String(error.message || error);
          } else {
            regime.status = "planned";
            regime.events = [...(regime.events || []), { at: stamp(), action: "submission-unconfirmed; reset-to-planned" }];
          }
          save();
        }
        continue;
      }
      regime.new_regime_id = launched.id;
      regime.status = "submitted";
      regime.submitted_at = stamp();
      save();
      submitted++;
    }
  }
  if (submitted) {
    campaign.events.push({ at: stamp(), action: "launch-regimes", submitted });
    save();
  }
  return submitted;
}
async function verifyCurrentRuns(tasks) {
  const current = await state();
  const runs = new Map(current.runs.map((run) => [run.id, run]));
  let changed = false;
  for (const task of tasks) {
    if (!task.new_run_ids?.[0] || !["succeeded", "reused"].includes(task.status)) continue;
    if (task.current_artifact_verification?.status === "verified") continue;
    const run = runs.get(task.new_run_ids[0]) || await call(`/runs/${task.new_run_ids[0]}`);
    const audit = auditManifest(run.id, run);
    task.current_artifact_verification = audit;
    changed = true;
    if (audit.status !== "verified") {
      task.status = "blocked";
      task.blocker = `Replacement run artifact verification failed: ${audit.error}`;
    }
  }
  if (changed) save();
}
async function verifyEvaluationChildren() {
  const current = await state();
  const currentRuns = new Map(current.runs.map((run) => [run.id, run]));
  const original = readJson(join(folder, "ORIGINAL_STATE.json"));
  const originalRuns = new Map(original.runs.map((run) => [run.id, run]));
  let changed = false;
  for (const evaluation of campaign.evaluations) {
    if (!evaluation.source_child_slots)
      evaluation.source_child_slots = evaluationChildSlots(evaluation.original, originalRuns);
    if (!evaluation.child_mappings?.length) {
      evaluation.child_mappings = evaluation.source_child_slots.map((slot) => ({
        ...slot,
        source_candidate: slot.candidate,
        replacement_evaluation_id: evaluation.new_evaluation_id || null,
        replacement_run_id: null,
        status: ["failed", "blocked"].includes(evaluation.status) ? "not-created" : "pending",
        reason: "Replacement child mapping was not created.",
        explicit_blocker: ["failed", "blocked"].includes(evaluation.status) ? "Replacement child mapping was not created because the parent evaluation is terminal." : null,
      }));
      changed = true;
    }
    for (const mapping of evaluation.child_mappings || []) {
      const source = originalRuns.get(mapping.source_run_id);
      if (!mapping.original_artifact_verification) {
        mapping.original_artifact_verification = source
          ? auditManifest(mapping.source_run_id, source)
          : { status: "failed", error: "Original child run record is unavailable for artifact verification" };
        if (!source) {
          mapping.status = "blocked";
          mapping.explicit_blocker = mapping.original_artifact_verification.error;
        }
        changed = true;
      }
      if (mapping.status !== "succeeded" || !mapping.replacement_run_id) continue;
      if (mapping.current_artifact_verification?.status === "verified") continue;
      const replacement = currentRuns.get(mapping.replacement_run_id) || await call(`/runs/${mapping.replacement_run_id}`);
      const audit = auditManifest(mapping.replacement_run_id, replacement);
      mapping.current_artifact_verification = audit;
      changed = true;
      if (audit.status !== "verified") {
        mapping.status = "blocked";
        mapping.verification_error = `Replacement child artifact verification failed: ${audit.error}`;
      }
    }
    updateEvaluationIntegrity(evaluation);
  }
  if (changed) save();
}
function delta(oldValue, newValue) {
  return typeof oldValue === "number" && typeof newValue === "number" ? newValue - oldValue : null;
}
async function writeComparisons() {
  const originalState = readJson(join(folder, "ORIGINAL_STATE.json"));
  const originalRuns = new Map(originalState.runs.map((run) => [run.id, run]));
  const current = await state();
  const currentRuns = new Map(current.runs.map((run) => [run.id, run]));
  const audits = new Map();
  const audit = (runId, run) => {
    if (!runId || !run) return { status: "failed", error: "Run record is unavailable for artifact verification" };
    if (!audits.has(runId)) audits.set(runId, auditManifest(runId, run));
    return audits.get(runId);
  };
  const rows = [];
  for (const task of campaign.direct) {
    const runId = task.new_run_ids?.[0];
    const newRun = runId ? currentRuns.get(runId) || await call(`/runs/${runId}`) : null;
    const newMetrics = metricSubset(newRun?.result?.metrics);
    const verification = newRun?.status === "Succeeded" ? audit(newRun.id, newRun) : task.current_artifact_verification || null;
    task.current_artifact_verification = verification;
    if (newRun?.status === "Succeeded" && verification?.status !== "verified") {
      task.status = "blocked";
      task.blocker = `Replacement run artifact verification failed: ${verification?.error || "unknown error"}`;
    }
    for (const original of task.original) {
      const sourceRun = originalRuns.get(original.id);
      const sourceVerification = audit(original.id, sourceRun);
      rows.push({
        original_run_id: original.id,
        replacement_run_id: runId || null,
        replacement_status: newRun?.status || task.status,
        reused: task.status === "reused",
        comparison_scope: "Original versus current-source original-window result: execution/source change effect; no newer-data window is included.",
        original_metrics: original.metrics,
        current_metrics: newMetrics,
        delta: Object.fromEntries(Object.keys(original.metrics).map((key) => [key, delta(original.metrics[key], newMetrics[key])])),
        original_warnings: original.warnings,
        current_warnings: newRun?.result?.warnings || [],
        compatibility_mappings: task.request.mappings || [],
        original_artifact_verification: sourceVerification,
        current_artifact_verification: verification,
      });
    }
  }
  const extensions = [];
  for (const task of campaign.extensions) {
    const runId = task.new_run_ids?.[0];
    const run = runId ? currentRuns.get(runId) || await call(`/runs/${runId}`) : null;
    const verification = run?.status === "Succeeded" ? audit(run.id, run) : task.current_artifact_verification || null;
    task.current_artifact_verification = verification;
    if (run?.status === "Succeeded" && verification?.status !== "verified") {
      task.status = "blocked";
      task.blocker = `Extension run artifact verification failed: ${verification?.error || "unknown error"}`;
    }
    const sourceTaskIds = task.source_task_ids || [task.source_task_id].filter(Boolean);
    const sourceComparisons = sourceTaskIds.map((sourceTaskId) => {
      const sourceTask = campaign.direct.find((candidate) => candidate.id === sourceTaskId);
      const sourceRunId = sourceTask?.new_run_ids?.[0] || null;
      const sourceRun = sourceRunId ? currentRuns.get(sourceRunId) : null;
      const sourceMetrics = metricSubset(sourceRun?.result?.metrics);
      const extensionMetrics = metricSubset(run?.result?.metrics);
      return {
        source_task_id: sourceTaskId,
        current_original_window_run_id: sourceRunId,
        current_original_window_metrics: sourceMetrics,
        extension_vs_current_original: Object.fromEntries(Object.keys(sourceMetrics).map((key) => [key, delta(sourceMetrics[key], extensionMetrics[key])])),
      };
    });
    extensions.push({
      task_id: task.id,
      source_task_ids: sourceTaskIds,
      source_run_ids: task.source_run_ids || [task.source_run_id].filter(Boolean),
      extension_run_id: runId || null,
      status: task.status === "blocked" ? "blocked" : run?.status || task.status,
      data: task.data || null,
      metrics: metricSubset(run?.result?.metrics),
      comparison_scope: "Current-source newer-data extension versus the current-source original-window result: newer-data/window effect; it does not change the original-window execution comparison.",
      source_comparisons: sourceComparisons,
      artifact_verification: verification,
      blocker: task.blocker || null,
    });
  }
  writeJson("COMPARISON.json", { generated_at: stamp(), original_window: rows, extensions });
  writeJson("EVALUATION_LINEAGE.json", {
    generated_at: stamp(),
    evaluations: campaign.evaluations.map((task) => ({
      source_evaluation_id: task.source_evaluation_id,
      replacement_evaluation_id: task.new_evaluation_id || null,
      status: task.status,
      integrity_blocker: task.integrity_blocker || null,
      expected: task.expected,
      child_mappings: task.child_mappings || [],
      regimes: task.regimes,
    })),
  });
  save();
  return { rows, extensions };
}
async function refreshPortfolio() {
  if (campaign.portfolio_refresh?.completed_at) return campaign.portfolio_refresh;
  const refresh = campaign.portfolio_refresh || {
    started_at: stamp(),
    requests: [],
    imports: [],
    named_combination_copies: "No named browser-local combinations existed at campaign start; no copies were created.",
  };
  campaign.portfolio_refresh = refresh;
  save();
  const waitForCollective = async (status) => {
    while (status.running) {
      await new Promise((resolveDone) => setTimeout(resolveDone, 2000));
      status = await call("/collective/status");
    }
    return status;
  };
  const failedStatus = (status) => status?.error || status?.evidence_error || "";
  let status = await call("/collective/status");
  if (status.running) {
    refresh.requests.push({ at: stamp(), action: "wait-for-existing-collective-refresh", observed: status });
    save();
    status = await waitForCollective(status);
    if (failedStatus(status)) {
      refresh.status = status;
      refresh.error = `An existing collective refresh failed: ${failedStatus(status)}`;
      refresh.completed_at = stamp();
      save();
      return refresh;
    }
  }
  const fullIntent = { at: stamp(), action: "full-collective-refresh", intent: "Rebuild portfolio evidence from verified current-source research." };
  refresh.requests.push(fullIntent);
  save();
  try {
    status = await call("/collective/refresh", { method: "POST", body: {} });
  } catch (error) {
    refresh.requests.push({ at: stamp(), action: "full-collective-refresh-response-error", error: String(error.message || error) });
    save();
    try {
      status = await call("/collective/status");
      status = await waitForCollective(status);
    } catch (statusError) {
      refresh.status = { error: String(statusError.message || statusError) };
      refresh.error = `Collective refresh submission was unconfirmed: ${String(error.message || error)}`;
      refresh.completed_at = stamp();
      save();
      return refresh;
    }
    if (String(status.started_at || "") < fullIntent.at) {
      refresh.status = status;
      refresh.error = `Collective refresh submission was unconfirmed: ${String(error.message || error)}`;
      refresh.completed_at = stamp();
      save();
      return refresh;
    }
  }
  status = await waitForCollective(status);
  if (failedStatus(status)) {
    refresh.status = status;
    refresh.error = `Collective evidence refresh failed: ${failedStatus(status)}`;
    refresh.completed_at = stamp();
    save();
    return refresh;
  }
  const current = await state();
  const currentRuns = new Map(current.runs.map((run) => [run.id, run]));
  const extensionById = new Map(campaign.extensions.map((task) => [task.id, task]));
  const verified = (task) => task?.new_run_ids?.[0] && ["succeeded", "reused"].includes(task.status) && task.current_artifact_verification?.status === "verified";
  const sourceReplacement = new Map();
  for (const direct of campaign.direct) {
    const extension = extensionById.get(direct.extension_task_id);
    for (const original of direct.original) {
      const preferred = original.baseline && verified(extension) ? extension : direct;
      if (verified(preferred)) {
        sourceReplacement.set(original.id, {
          replacement_run_id: preferred.new_run_ids[0],
          source_task_id: direct.id,
          replacement_task_id: preferred.id,
          evidence: preferred.extension ? "newer-data-extension" : "current-source-original-window",
        });
      }
    }
  }
  for (const evaluation of campaign.evaluations) {
    if (evaluation.integrity_blocker) continue;
    for (const mapping of evaluation.child_mappings || []) {
      if (mapping.status !== "succeeded" || !mapping.replacement_run_id || mapping.current_artifact_verification?.status !== "verified") continue;
      sourceReplacement.set(mapping.source_run_id, {
        replacement_run_id: mapping.replacement_run_id,
        source_task_id: evaluation.id,
        replacement_task_id: evaluation.id,
        evidence: "recreated-evaluation-child",
      });
    }
  }
  const catalogSupportsRun = (item, run) => {
    if (!item || !run || item.research_integrity_error || item.symbol !== run.input.dataset.symbol || item.timeframe !== run.input.timeframe || item.session !== run.input.session)
      return false;
    if (!same(item.parameters || {}, run.input.parameters || {})) return false;
    if (Number.isFinite(item.capital) && item.capital !== run.input.capital) return false;
    const coverage = item.coverage || [{ start: item.start, end: item.end }];
    return coverage.some((segment) => segment.start <= run.input.start && segment.end >= run.input.end);
  };
  const exactItemIds = (catalog, runId) => {
    const run = currentRuns.get(runId);
    return (catalog.items || [])
      // Match the server's durable exact-run import predicate. A combined
      // history or a replay can contain this run ID without representing the
      // single replacement history that Portfolio Add must expose.
      .filter((item) => item.source_run_ids?.length === 1
        && item.source_run_ids[0] === runId
        && item.coverage?.length === 1
        && item.coverage[0].start === run?.input.start
        && item.coverage[0].end === run?.input.end
        && !item.latest_replay
        && !item.research_integrity_error)
      .map((item) => item.id);
  };
  let catalog = await call("/collective");
  const selectedBaselines = campaign.direct
    .filter((direct) => direct.original.some((run) => run.baseline))
    .map((direct) => {
      const extension = extensionById.get(direct.extension_task_id);
      const preferred = verified(extension) ? extension : verified(direct) ? direct : null;
      return { direct, extension, preferred };
    });
  const pendingImports = new Map();
  for (const selection of selectedBaselines) {
    if (!selection.preferred) continue;
    const runId = selection.preferred.new_run_ids[0];
    if (!pendingImports.has(runId)) pendingImports.set(runId, { run_id: runId, task_ids: [] });
    pendingImports.get(runId).task_ids.push(selection.direct.id);
  }
  for (const pending of pendingImports.values()) {
    const existing = exactItemIds(catalog, pending.run_id);
    if (existing.length) {
      refresh.imports.push({ at: stamp(), run_id: pending.run_id, task_ids: pending.task_ids, status: "already-linked", collective_item_ids: existing });
      save();
      continue;
    }
    let priorStatus = await call("/collective/status");
    if (priorStatus.running) {
      refresh.requests.push({ at: stamp(), action: "wait-before-pinned-import", run_id: pending.run_id, observed: priorStatus });
      save();
      priorStatus = await waitForCollective(priorStatus);
    }
    if (failedStatus(priorStatus)) {
      refresh.imports.push({ at: stamp(), run_id: pending.run_id, task_ids: pending.task_ids, status: "blocked", error: failedStatus(priorStatus) });
      save();
      continue;
    }
    const entry = { at: stamp(), run_id: pending.run_id, task_ids: pending.task_ids, status: "submitting", intent: "Pin an exact verified replacement baseline for portfolio evidence." };
    refresh.imports.push(entry);
    save();
    try {
      const started = await call("/collective/import", { method: "POST", body: { runId: pending.run_id } });
      const completed = await waitForCollective(started);
      entry.collective_status = completed;
      if (failedStatus(completed)) {
        entry.status = "failed";
        entry.error = failedStatus(completed);
      } else {
        catalog = await call("/collective");
        const linked = exactItemIds(catalog, pending.run_id);
        entry.collective_item_ids = linked;
        entry.status = linked.length ? "imported" : "failed";
        if (!linked.length) entry.error = "Pinned import completed without an exact, integrity-verified source-run link.";
      }
    } catch (error) {
      entry.response_error = String(error.message || error);
      try {
        let reconciled = await call("/collective/status");
        reconciled = await waitForCollective(reconciled);
        entry.collective_status = reconciled;
        catalog = await call("/collective");
        const linked = exactItemIds(catalog, pending.run_id);
        entry.collective_item_ids = linked;
        if (linked.length && !failedStatus(reconciled)) entry.status = "imported-after-response-error";
        else {
          entry.status = "failed";
          entry.error = failedStatus(reconciled) || entry.response_error;
        }
      } catch (reconcileError) {
        entry.status = "failed";
        entry.error = `${entry.response_error}; reconciliation failed: ${String(reconcileError.message || reconcileError)}`;
      }
    }
    save();
  }
  catalog = await call("/collective");
  writeJson("COLLECTIVE_INDEX_AFTER.json", catalog);
  const runToItem = new Map();
  for (const item of catalog.items || []) {
    if (item.research_integrity_error) continue;
    for (const runId of item.source_run_ids || []) {
      if (!runToItem.has(runId)) runToItem.set(runId, []);
      runToItem.get(runId).push(item.id);
    }
  }
  const baselineSelections = selectedBaselines.map(({ direct, extension, preferred }) => {
    if (!preferred) {
      const attempted = [extension, direct].filter(Boolean);
      return {
        source_task_id: direct.id,
        source_run_ids: direct.source_run_ids,
        selected_run_id: null,
        status: attempted.some((task) => task.current_artifact_verification?.status === "failed") ? "unverified" : "no-replacement",
        evidence: null,
      };
    }
    const runId = preferred.new_run_ids[0];
    const exact = exactItemIds(catalog, runId);
    return {
      source_task_id: direct.id,
      source_run_ids: direct.source_run_ids,
      selected_run_id: runId,
      selected_task_id: preferred.id,
      evidence: preferred.extension ? "newer-data-extension" : "current-source-original-window",
      status: exact.length === 1 ? "mapped" : exact.length > 1 ? "ambiguous" : "not-imported",
      collective_item_ids: exact,
    };
  });
  const prior = existsSync(join(folder, "COLLECTIVE_INDEX_BEFORE.json"))
    ? readJson(join(folder, "COLLECTIVE_INDEX_BEFORE.json"))
    : { items: [] };
  const itemMappings = (prior.items || [])
    .filter((item) => Array.isArray(item.source_run_ids) && item.source_run_ids.length)
    .map((item) => {
      const replacements = item.source_run_ids.map((sourceRunId) => ({ source_run_id: sourceRunId, ...sourceReplacement.get(sourceRunId) }));
      const unmapped = replacements.filter((mapping) => !mapping.replacement_run_id).map((mapping) => mapping.source_run_id);
      if (unmapped.length) return {
        source_collective_item_id: item.id,
        replacement_collective_item_ids: [],
        status: "unmapped-constituents",
        unmapped_source_run_ids: unmapped,
        constituents: replacements,
      };
      const replacementRunIds = [...new Set(replacements.map((mapping) => mapping.replacement_run_id))];
      const exact = (catalog.items || [])
        .filter((candidate) => !candidate.research_integrity_error && replacementRunIds.every((runId) => (candidate.source_run_ids || []).includes(runId) && catalogSupportsRun(candidate, currentRuns.get(runId))))
        .map((candidate) => candidate.id);
      return {
        source_collective_item_id: item.id,
        replacement_collective_item_ids: exact,
        status: exact.length === 1 ? "mapped" : exact.length > 1 ? "ambiguous" : "not-imported",
        constituents: replacements,
      };
    });
  const runMappings = [];
  for (const task of [...campaign.direct, ...campaign.extensions]) {
    const runId = task.new_run_ids?.[0];
    if (!runId) continue;
    const items = exactItemIds(catalog, runId);
    runMappings.push({
      task_id: task.id,
      run_id: runId,
      artifact_verified: task.current_artifact_verification?.status === "verified",
      collective_item_ids: items,
      status: items.length === 1 ? "mapped" : items.length ? "ambiguous" : "not-imported",
    });
  }
  refresh.status = status;
  refresh.run_mappings = runMappings;
  refresh.baseline_selections = baselineSelections;
  refresh.item_mappings = itemMappings;
  refresh.completed_at = stamp();
  save();
  return refresh;
}
function writeDeliverables() {
  const direct = campaign.direct.flatMap((task) => task.original.map((original) => ({
    source_run_id: original.id,
    replacement_run_id: task.new_run_ids?.[0] || null,
    task_id: task.id,
    status: task.status,
    reused: Boolean(task.reused_run_id),
    prior_attempts: task.prior_attempts || [],
    artifact_verification: task.current_artifact_verification || task.reused_artifacts || null,
    blocker: task.blocker || null,
  })));
  const evaluations = campaign.evaluations.map((task) => ({
    source_evaluation_id: task.source_evaluation_id,
    replacement_evaluation_id: task.new_evaluation_id || null,
    status: task.status,
    integrity_blocker: task.integrity_blocker || null,
    children: task.child_mappings || [],
    regimes: task.regimes,
  }));
  const extensions = campaign.extensions.map((task) => ({
    task_id: task.id,
    source_task_ids: task.source_task_ids || [task.source_task_id].filter(Boolean),
    source_run_ids: task.source_run_ids || [task.source_run_id].filter(Boolean),
    extension_run_id: task.new_run_ids?.[0] || null,
    status: task.status,
    cutoff: task.data?.cutoff || null,
    artifact_verification: task.current_artifact_verification || null,
    blocker: task.blocker || null,
  }));
  const blockers = [
    ...campaign.blocked.map((item) => ({ type: "preflight", ...item })),
    ...campaign.direct.filter((task) => ["failed", "blocked"].includes(task.status)).map((task) => ({ type: "direct", task_id: task.id, status: task.status, blocker: task.blocker || task.execution_status || null })),
    ...campaign.evaluations.filter((task) => ["failed", "blocked"].includes(task.status) || task.integrity_blocker).map((task) => ({ type: "evaluation", task_id: task.id, status: task.status, blocker: task.integrity_blocker || task.blocker || task.execution_status || null })),
    ...campaign.evaluations.flatMap((task) => (task.child_mappings || [])
      .filter((mapping) => mapping.status !== "succeeded")
      .map((mapping) => ({ type: "evaluation-child", task_id: task.id, source_run_id: mapping.source_run_id, status: mapping.status, blocker: mapping.explicit_blocker || mapping.verification_error || mapping.reason || (mapping.validation_errors || []).join("; ") || null }))),
    ...campaign.evaluations.flatMap((task) => task.regimes.filter((regime) => ["failed", "blocked"].includes(regime.status)).map((regime) => ({ type: "regime", task_id: regime.id, status: regime.status, blocker: regime.blocker || regime.error || null }))),
    ...campaign.extensions.filter((task) => ["failed", "blocked", "unavailable"].includes(task.status)).map((task) => ({ type: "extension", task_id: task.id, status: task.status, blocker: task.blocker || task.execution_status || null })),
    ...(campaign.portfolio_refresh?.error ? [{ type: "portfolio-refresh", status: "failed", blocker: campaign.portfolio_refresh.error }] : []),
    ...((campaign.portfolio_refresh?.imports || []).filter((entry) => ["failed", "blocked"].includes(entry.status)).map((entry) => ({ type: "portfolio-import", run_id: entry.run_id, status: entry.status, blocker: entry.error || null }))),
    ...((campaign.portfolio_refresh?.baseline_selections || []).filter((entry) => entry.status !== "mapped").map((entry) => ({ type: "portfolio-baseline", task_id: entry.source_task_id, status: entry.status, blocker: "No single exact, integrity-verified catalog link exists for the selected replacement." }))),
    ...((campaign.portfolio_refresh?.item_mappings || []).filter((entry) => entry.status !== "mapped").map((entry) => ({ type: "portfolio-item", source_collective_item_id: entry.source_collective_item_id, status: entry.status, blocker: entry.unmapped_source_run_ids?.length ? `Unmapped source runs: ${entry.unmapped_source_run_ids.join(", ")}` : "No exact, integrity-verified replacement catalog link exists." }))),
  ];
  writeJson("OLD_TO_NEW_MAPPING.json", { generated_at: stamp(), direct, evaluations, extensions });
  writeJson("BLOCKED_OR_FAILED.json", { generated_at: stamp(), blockers });
  writeJson("CAMPAIGN_MANIFEST.json", {
    generated_at: stamp(),
    id: campaign.id,
    created_at: campaign.created_at,
    completed_at: campaign.completed_at || null,
    api: campaign.api,
    limits: campaign.limits,
    backup: campaign.backup,
    source_identity: campaign.source_identity,
    runtime_identity: campaign.runtime_identity,
    runtime_frozen_at: campaign.runtime_frozen_at || null,
    runtime_drift: campaign.runtime_drift || campaign.runtime_violation || null,
    legacy_migration: campaign.legacy_migration || null,
    frozen_datasets: campaign.frozen_datasets,
    snapshot: campaign.snapshot,
    compatibility_mappings: campaign.compatibility_mappings,
    counts: { direct: direct.length, evaluations: evaluations.length, extensions: extensions.length, blockers: blockers.length },
  });
  return { direct, evaluations, extensions, blockers };
}
async function finalizeIfReady() {
  await syncStatus();
  if (!originalTerminal()) return false;
  await verifyEvaluationChildren();
  await launchRegimes();
  const afterRegimeLaunch = await state();
  await reconcileRegimes(afterRegimeLaunch);
  save();
  if (!regimesTerminal()) return false;
  await verifyCurrentRuns(campaign.direct);
  if (!campaign.extensions.length) await createExtensions();
  const activity = campaignActivity(await state());
  if (activity.runs.length || activity.evaluations.length) return false;
  if (campaign.extensions.some((task) => task.status === "planned")) {
    await launchRuns(campaign.extensions, "extension", limitFromEnvironment());
    return false;
  }
  if (!extensionTerminal()) return false;
  await retryRunAnnotations();
  const comparisons = await writeComparisons();
  await refreshPortfolio();
  const deliverables = writeDeliverables();
  const regimeTasks = campaign.evaluations.flatMap((task) => task.regimes);
  const summary = {
    completed_at: stamp(),
    direct: Object.fromEntries(["succeeded", "failed", "reused", "blocked"].map((status) => [status, campaign.direct.filter((task) => task.status === status).length])),
    evaluations: Object.fromEntries(["succeeded", "failed", "blocked"].map((status) => [status, campaign.evaluations.filter((task) => task.status === status).length])),
    regimes: Object.fromEntries(["succeeded", "failed", "blocked", "submitted", "planned"].map((status) => [status, regimeTasks.filter((task) => task.status === status).length])),
    extensions: Object.fromEntries(["succeeded", "failed", "unavailable", "blocked"].map((status) => [status, campaign.extensions.filter((task) => task.status === status).length])),
    comparison_rows: comparisons.rows.length,
    blockers: deliverables.blockers.length,
    portfolio: campaign.portfolio_refresh,
  };
  campaign.summary = summary;
  campaign.completed_at = stamp();
  save();
  const lines = [
    "# Current-source research refresh",
    "",
    `Completed: ${campaign.completed_at}`,
    "",
    "## Result",
    "",
    ...Object.entries(summary.direct).map(([status, count]) => `- Direct original-window tests ${status}: ${count}`),
    ...Object.entries(summary.evaluations).map(([status, count]) => `- Recreated evaluations ${status}: ${count}`),
    ...Object.entries(summary.regimes).map(([status, count]) => `- Recreated regime studies ${status}: ${count}`),
    ...Object.entries(summary.extensions).map(([status, count]) => `- Newer-data extensions ${status}: ${count}`),
    `- Explicit failed or blocked items: ${summary.blockers}`,
    "",
    "Original runs, evaluations, regimes, manifests, and source snapshots were preserved. `COMPARISON.json` separates original-window execution/source effects from newer-data extension effects. `OLD_TO_NEW_MAPPING.json`, `EVALUATION_LINEAGE.json`, and `BLOCKED_OR_FAILED.json` provide the durable linkage and exceptions.",
    "",
    "No named browser-local portfolio combinations existed at campaign start, so there were no saved combinations to duplicate. The server-active portfolio selection was preserved in `PORTFOLIO_TRACKING_BEFORE.json`.",
    "",
  ];
  writeFileSync(join(folder, "RESULTS.md"), lines.join("\n"));
  return true;
}
async function waitForCompletion() {
  for (;;) {
    await retryTransient(
      () => advanceOriginalWork(limitFromEnvironment()),
      "advance-original-work",
    );
    const done = await retryTransient(
      () => finalizeIfReady(),
      "finalize-refresh",
    );
    if (done) return;
    await new Promise((resolveDone) => setTimeout(resolveDone, 15000));
  }
}
function limitFromEnvironment() {
  const maximum = campaign?.limits?.maxBatch || 24;
  const raw = process.env.REFRESH_LAUNCH_LIMIT;
  if (!raw) return maximum;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < 1) throw new Error("REFRESH_LAUNCH_LIMIT must be a positive integer");
  if (parsed > maximum) throw new Error(`REFRESH_LAUNCH_LIMIT must not exceed the frozen batch limit of ${maximum}`);
  return parsed;
}

try {
  if (mode === "preflight") {
    await initialize();
    console.log(JSON.stringify({ campaign: campaign.id, direct: campaign.direct.length, reused: campaign.direct.filter((task) => task.status === "reused").length, blocked: campaign.blocked.length + campaign.direct.filter((task) => task.status === "blocked").length, evaluations: campaign.evaluations.length }, null, 2));
  } else {
    await initialize();
    if (mode === "launch" || mode === "run") {
      const limit = limitFromEnvironment();
      const advanced = await retryTransient(
        () => advanceOriginalWork(limit),
        "initial-advance",
      );
      console.log(JSON.stringify({ ...advanced, campaign: campaign.id }, null, 2));
    }
    if (mode === "continue" || mode === "run") {
      await retryTransient(
        () => advanceOriginalWork(limitFromEnvironment()),
        "initial-continue",
      );
      await retryTransient(
        () => finalizeIfReady(),
        "initial-finalize",
      );
      if (mode === "run" && !campaign.completed_at) await waitForCompletion();
      else console.log(JSON.stringify(campaign.last_status || { active_runs: 0 }, null, 2));
    }
    if (mode === "status") {
      await syncStatus();
      console.log(JSON.stringify(campaign.last_status, null, 2));
    }
  }
} catch (error) {
  if (campaign) {
    campaign.last_error = { at: stamp(), message: String(error.stack || error) };
    save();
  }
  console.error(error.stack || error);
  process.exitCode = 1;
}
