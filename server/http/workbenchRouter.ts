import { createServer } from "node:http";
import type { IncomingMessage, ServerResponse } from "node:http";
import { DatabaseSync } from "node:sqlite";
import { execFileSync, spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  createReadStream,
  statSync,
} from "node:fs";
import { resolve, join, relative, sep } from "node:path";
import { createResearch } from "../features/evaluations/research.ts";
import type { Evaluation } from "../features/evaluations/research.ts";
import { createRunDeletion } from "../features/runs/runDeletion.ts";
import { createResearchArchive } from "../features/runs/researchArchive.ts";
import { createDashboard } from "../features/scorecards/dashboard.ts";
import { createCollective } from "../features/portfolio/collective.ts";
import { createPortfolioRisk } from "../features/portfolio/portfolioRisk.ts";
import { createPortfolioTracking } from "../features/portfolio/portfolioTracking.ts";
import { createScriptArchive } from "../features/scripts/scriptArchive.ts";
import { createDiscoveryChangeGate } from "../features/scripts/discoveryChangeGate.ts";
import { visibleMonthlyCsv, visibleMonthlyReport } from "../features/scripts/archiveVisibility.ts";
import type { EvaluationView } from "../../shared/ts/workbenchModels.ts";
import { strategyStageStatuses } from "../../shared/ts/stageStatus.ts";
import { runConfigurationKey } from "../../shared/ts/evidence.ts";
import { createReadinessReview } from "../../shared/ts/readiness.ts";
import { createStageAssessment } from "../../shared/ts/stageAssessments.ts";
import { createDatasets } from "../features/datasets/datasets.ts";
import { createRevisionedRunSummaries } from "../infra/revisionedRunSummaries.ts";
import { previewWarmup } from "../core/warmup.ts";
import { createEventStudies } from "../features/event-studies/eventStudies.ts";
import { createRecordRepository } from "../infra/recordRepository.ts";
import {
  createSourceSnapshots,
  executionSourceFingerprint,
} from "../infra/sourceSnapshots.ts";
import { loadWorkbenchLayout } from "../layout.ts";
import { createEvidenceRegistry } from "../infra/evidenceRegistry.ts";
import type {
  Dataset,
  Input,
  RecordValue,
  Run,
  Strategy,
} from "../core/contracts.ts";
import {
  date,
  numeric,
  parameters,
} from "../core/validation.ts";
import { readJsonBody as body, sendJson as json } from "./responses.ts";
import { createRunQueue } from "../core/runQueue.ts";
import { stopProcess } from "../core/processSupervisor.ts";
import { createContractValidation } from "../core/contractValidation.ts";
import { startSupervisorHeartbeat } from "../core/supervisorHeartbeat.ts";

export type { Input, Run } from "../core/contracts.ts";

// Node 24 executes TypeScript directly. No shell commands contain UI input.
const root = resolve(import.meta.dirname, "../..");
const layout = loadWorkbenchLayout(root);
const contractValidation = createContractValidation(layout.contractsRoot);
const state = layout.stateRoot;
const python =
  process.env.WORKBENCH_PYTHON ||
  join(
    root,
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python",
  );
const port = Number(process.env.WORKBENCH_PORT || 8001);
const concurrency = Math.max(
  1,
  Math.min(8, Number(process.env.WORKBENCH_CONCURRENCY) || 2),
);
const maxBatch = Math.max(
  1,
  Math.min(100, Number(process.env.WORKBENCH_MAX_BATCH) || 24),
);
mkdirSync(state, { recursive: true });
const supervisorFile = join(state, "supervisor.json");
const supervisorToken = randomUUID();
const supervisorHeartbeat = await startSupervisorHeartbeat(
  supervisorFile,
  supervisorToken,
  process.pid,
  error => {
    console.error("Supervisor heartbeat failed:", error);
    shutdown(1);
  },
);
const db = new DatabaseSync(join(state, "workbench.sqlite3"));
db.exec("PRAGMA journal_mode=WAL");
const projectedRuns = createRevisionedRunSummaries(db);
const records = createRecordRepository(db);
const put = records.put;
const get = records.get;
const all = records.all;
const rawRecord = records.raw;
const scriptArchive = createScriptArchive(root);
scriptArchive.list(); // Complete any interrupted archive move before discovery starts.
const now = () => new Date().toISOString();
const hash = (value: string | Buffer) =>
  createHash("sha256").update(value).digest("hex");
const runDir = (id: string) => join(state, "runs", id);
const activeEvaluations = () => {
  const archived = scriptArchive.archivedIds();
  return all<Evaluation>("evaluation").filter(evaluation =>
    !archived.has(evaluation.candidates?.[0]?.strategy.id || ""));
};
const activeRegimes = () => {
  const visibleEvaluations = new Set(activeEvaluations().map(evaluation => evaluation.id));
  const hiddenEvaluations = new Set(all<Evaluation>("evaluation").map(evaluation => evaluation.id).filter(id => !visibleEvaluations.has(id)));
  return all<{ evaluation_id: string }>("regime").filter(regime => !hiddenEvaluations.has(regime.evaluation_id));
};
const activeDashboardRecords = <T,>(kind: string): T[] => {
  if (kind === "run") {
    const archived = scriptArchive.archivedIds();
    return projectedRuns.read()
      .filter(run => !archived.has(run.input.strategy.id)) as T[];
  }
  if (kind === "evaluation") return activeEvaluations() as T[];
  if (kind === "regime") return activeRegimes() as T[];
  return all<T>(kind);
};
function saveRun(run: Run) {
  put("run", run.id, run);
}
let stopping = false;
const cleanEnvironment = () => {
  const env: NodeJS.ProcessEnv = {};
  for (const key of [
    "PATH",
    "Path",
    "SYSTEMROOT",
    "SystemRoot",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "LANG",
  ])
    if (process.env[key]) env[key] = process.env[key];
  return {
    ...env,
    WORKBENCH_HOME: state,
    WORKBENCH_ARTIFACTS: layout.artifactsRoot,
    PYTHONUNBUFFERED: "1",
    PYTHONIOENCODING: "utf-8",
  };
};
let catalog: {
  strategies: Strategy[];
  errors: RecordValue[];
  library?: {
    entries: {
      id: string;
      source_id?: string;
      aliases?: string[];
      path_aliases?: string[];
      path: string;
      file_hash: string;
    }[];
  };
} = {
  strategies: [],
  errors: [],
};
let catalogRevision = 0;
let cachedSummary: { key: string; encoded: string; etag: string } | null = null;
function sendSummary(req: IncomingMessage, res: ServerResponse, encoded: string, etag: string) {
  res.setHeader("ETag", etag);
  res.setHeader("Cache-Control", "private, no-cache");
  if (req.headers["if-none-match"] === etag) {
    res.writeHead(304);
    return res.end();
  }
  res.writeHead(200, { "Content-Type": "application/json" });
  return res.end(encoded);
}
let discoveryTask: Promise<void> | null = null;
let activeDiscoverySnapshot: string | null = null;
let queuedDiscoveryTask: Promise<void> | null = null;
const discoveryGate = createDiscoveryChangeGate(root);
function refreshCatalog(force = false): Promise<void> {
  if (discoveryTask) {
    if (!force || discoveryGate.snapshot() === activeDiscoverySnapshot) return discoveryTask;
    if (!queuedDiscoveryTask) {
      queuedDiscoveryTask = discoveryTask.then(() => {
        queuedDiscoveryTask = null;
        return refreshCatalog(true);
      });
    }
    return queuedDiscoveryTask;
  }
  const snapshot = discoveryGate.snapshot();
  if (!force && !discoveryGate.needsScan(snapshot)) return Promise.resolve();
  activeDiscoverySnapshot = snapshot;
  discoveryTask = new Promise((resolveDone) => {
    const child = spawn(python, ["-m", "workbench.contract", root], {
      cwd: root,
      env: cleanEnvironment(),
      windowsHide: true,
    });
    let output = "",
      error = "";
    child.stdout.on("data", (x) => {
      output += x;
    });
    child.stderr.on("data", (x) => {
      error += x;
    });
    child.on("error", (e) => {
      error = e.message;
    });
    child.on("close", (code) => {
      try {
        if (code !== 0) throw new Error(error);
        const discovered = JSON.parse(output) as typeof catalog;
        const fingerprintErrors: RecordValue[] = [];
        discovered.strategies = discovered.strategies.filter((strategy) => {
          try {
            strategy.execution_source_hash = executionSourceFingerprint(
              root,
              strategy,
            );
            return true;
          } catch (fingerprintError) {
            fingerprintErrors.push({
              file: strategy.file,
              error: fingerprintError instanceof Error
                ? fingerprintError.message
                : String(fingerprintError),
            });
            return false;
          }
        });
        discovered.errors = [...discovered.errors, ...fingerprintErrors];
        catalog = discovered;
        catalogRevision += 1;
      } catch (e) {
        catalog.errors = [{ error: String(e) }];
        catalogRevision += 1;
      }
      // A failed discovery is still an attempt for these bytes. Retry when the
      // files change or the user explicitly scans, not on every idle tick.
      discoveryGate.markScanned(snapshot);
      activeDiscoverySnapshot = null;
      discoveryTask = null;
      resolveDone();
    });
  });
  return discoveryTask;
}
// Assigned after the run queue is built; each side has a terminal callback to
// the other, so construction cannot be expressed as one const initializer.
// eslint-disable-next-line prefer-const
let portfolioTracking: ReturnType<typeof createPortfolioTracking> | undefined;
const datasetService = createDatasets({
  root,
  state,
  python,
  cleanEnvironment,
  put,
  raw: rawRecord,
  onRegister: () => {
    try { portfolioTracking?.reconcile(); }
    catch (error) { console.error("Portfolio tracking reconciliation failed:", error); }
  },
});

const sourceSnapshots = createSourceSnapshots({
  root,
  state,
  python,
  cleanEnvironment,
  sourceRoots: layout.sourceRoots,
});
function snapshot(strategy: Strategy) {
  return sourceSnapshots.create(strategy);
}
function buildInputs(body: RecordValue) {
  const strategy = catalog.strategies.find((s) => s.id === body.strategy_id && !scriptArchive.archivedIds().has(s.id));
  if (!strategy) throw new Error("Select a discovered strategy");
  const dataset = get<Dataset>("dataset", String(body.dataset_id));
  const start = date(body.start, "Start"),
    end = date(body.end, "End");
  if (
    start > end ||
    start < dataset.first.slice(0, 10) ||
    end > dataset.last.slice(0, 10)
  )
    throw new Error(
      "Date interval must be ordered and within dataset coverage",
    );
  const timeframe = String(body.timeframe),
    stage = String(body.stage || "Exploratory"),
    session = String(body.session || "new-york-rth");
  if (strategy.required_session && session !== strategy.required_session)
    throw new Error(
      `This strategy requires session ${strategy.required_session}`,
    );
  if (strategy.execution_model === "event-v1" && Number(body.delay_bars || 0))
    throw new Error("Event strategies do not support execution-delay stress");
  if (!strategy.timeframes.includes(timeframe))
    throw new Error("Unsupported timeframe");
  if (!["new-york-rth", "full-trading-day", "london", "asia"].includes(session))
    throw new Error("Unsupported session");
  if (!["Exploratory", "Evaluation"].includes(stage))
    throw new Error("Use the watchlist for frozen Tracking runs");
  const development_end = body.development_end
    ? date(body.development_end, "Development end")
    : "";
  if (development_end && development_end >= start)
    throw new Error("Development must end before the scored interval");
  if (
    stage === "Evaluation" &&
    (!development_end || !String(body.criteria || "").trim())
  )
    throw new Error(
      "Evaluation requires prior development boundary and recorded criteria",
    );
  const base = parameters(strategy, (body.parameters || {}) as RecordValue);
  const sweep = (body.sweep || {}) as Record<string, unknown[]>;
  if (!sweep || typeof sweep !== "object" || Array.isArray(sweep))
    throw new Error("Sweep must map parameter names to arrays");
  let variants = [base];
  for (const [key, values] of Object.entries(sweep)) {
    if (
      !(key in strategy.parameters) ||
      !Array.isArray(values) ||
      !values.length
    )
      throw new Error(`Invalid sweep dimension: ${key}`);
    if (values.length * variants.length > maxBatch)
      throw new Error(`Batch exceeds limit of ${maxBatch}`);
    variants = variants.flatMap((v) =>
      values.map((value) => parameters(strategy, { ...v, [key]: value })),
    );
  }
  const ids = body.dataset_ids ?? [dataset.id];
  const frames = body.timeframes ?? [timeframe];
  if (
    !Array.isArray(ids) ||
    !ids.length ||
    !Array.isArray(frames) ||
    !frames.length ||
    ids.some((id) => typeof id !== "string") ||
    frames.some((tf) => typeof tf !== "string")
  )
    throw new Error(
      "Dataset and timeframe grids must be nonempty string arrays",
    );
  const datasets = [...new Set(ids)].map((id) =>
    get<Dataset>("dataset", String(id)),
  );
  const timeframes = [...new Set(frames)] as string[];
  if (
    datasets.some(
      (d) => start < d.first.slice(0, 10) || end > d.last.slice(0, 10),
    )
  )
    throw new Error("Every selected dataset must cover the scored interval");
  if (timeframes.some((tf) => !strategy.timeframes.includes(tf)))
    throw new Error("Unsupported timeframe in grid");
  if (datasets.length * timeframes.length * variants.length > maxBatch)
    throw new Error(`Batch exceeds limit of ${maxBatch}`);
  return datasets.flatMap((dataset) =>
    timeframes.flatMap((timeframe) =>
      variants.map((params) => ({
        protocol: 2,
        strategy,
        dataset: datasetService.protocol(dataset),
        parameters: params,
        start,
        end,
        timeframe,
        session,
        stage,
        capital: numeric(body.capital ?? 100000, "Capital", 1, 1e9),
        fee: numeric(body.fee ?? 1.25, "Fee", 0, 1000),
        slippage: numeric(body.slippage ?? 1, "Slippage", 0, 100),
        delay_bars: numeric(
          body.delay_bars ?? 0,
          "Additional execution delay",
          0,
          20,
          true,
        ),
        timeout: numeric(body.timeout ?? 300, "Timeout", 1, 3600, true),
        warmup_days: numeric(body.warmup_days ?? strategy.default_warmup_days ?? 60, "Warmup", 0, 1000, true),
        development_end,
        selection_time: now(),
        hypothesis: String(body.hypothesis || "").slice(0, 2000),
        criteria: String(body.criteria || "").slice(0, 2000),
      })),
    ),
  );
}
const runQueue = createRunQueue({
  all,
  get,
  saveRun,
  dataRevision: projectedRuns.revision,
  runDir,
  python,
  concurrency,
  cleanEnvironment,
  sourceFolder: sourceSnapshots.resolve,
  supervisorFile,
  supervisorToken,
  hash,
  now,
  validateInput: (input) => {
    if (input.protocol === 2) contractValidation.runInput(input);
  },
  onTerminal: (run) => portfolioTracking?.onRunTerminal(run),
});
const { enqueue: queueRun, pump, cancel } = runQueue;
function enqueue(input: Input, watchId?: string) {
  if (scriptArchive.archivedIds().has(input.strategy.id))
    throw new Error("Restore this script before starting another run");
  return queueRun(input, watchId);
}
runQueue.recoverInterrupted();
const deletion = createRunDeletion({
  db,
  state,
  all,
  put,
  raw: rawRecord,
  active: runQueue.isActive,
});
const researchArchive = createResearchArchive({
  db,
  records,
  runs: projectedRuns.read,
  active: runQueue.isActive,
  now,
});
function launch(body: RecordValue) {
  const variants = buildInputs(body);
  const source = snapshot(variants[0].strategy);
  if (
    variants.some(
      (v) =>
        hash(readFileSync(join(source.folder, v.strategy.file))) !==
        v.strategy.file_hash,
    )
  )
    throw new Error(
      "Strategy changed since discovery. Refresh the scripts and preview again.",
    );
  const experiment_id = randomUUID();
  db.exec("BEGIN");
  try {
    const runs = variants.map((v) => {
      const configuration_id = hash(
        JSON.stringify({
          source: source.executionSourceHash,
          strategy: v.strategy.id,
          parameters: v.parameters,
          timeframe: v.timeframe,
          session: v.session,
          capital: v.capital,
          fee: v.fee,
          slippage: v.slippage,
          delay_bars: v.delay_bars,
          symbol: v.dataset.symbol,
        }),
      );
      return enqueue({
        ...v,
        id: "",
        experiment_id,
        source_dir: source.sourceSnapshot,
        source_snapshot: source.sourceSnapshot,
        source_hash: source.executionSourceHash,
        execution_source_hash: source.executionSourceHash,
        snapshot_hash: source.snapshotHash,
        app_build_hash: source.appBuildHash,
        configuration_id,
      });
    });
    put("experiment", experiment_id, {
      id: experiment_id,
      created_at: now(),
      hypothesis: variants[0].hypothesis,
      attempted_variants: runs.length,
      run_ids: runs.map((r) => r.id),
    });
    db.exec("COMMIT");
    pump();
    return runs;
  } catch (e) {
    db.exec("ROLLBACK");
    throw e;
  }
}
const research = createResearch({
  all,
  get,
  put,
  buildInputs,
  snapshot,
  resolveSnapshot: sourceSnapshots.resolve,
  enqueue,
  cancel,
  pump,
  state,
  python,
  cleanEnvironment: () => ({
    ...cleanEnvironment(),
    WORKBENCH_SUPERVISOR_FILE: supervisorFile,
    WORKBENCH_SUPERVISOR_TOKEN: supervisorToken,
  }),
  stopProcess,
  runDir,
  hash,
});
setInterval(() => {
  if (!stopping) research.advance();
}, 1000).unref();

function safeArtifact(id: string, name: string) {
  const run = get<Run>("run", id);
  if (
    ![
      "input.json",
      "manifest.json",
      "process.log",
      "equity.csv",
      "trades.csv",
      "positions.csv",
      "signals.csv",
    ].includes(name)
  )
    throw new Error("Unknown artifact");
  const path = join(runDir(id), name);
  if (run.status === "Succeeded") {
    if (name === "manifest.json") {
      if (JSON.stringify(JSON.parse(readFileSync(path, "utf8"))) !==
          JSON.stringify(run.result))
        throw new Error("Result manifest changed after publication");
    } else if (name !== "input.json") {
      const artifacts = (run.result?.artifacts || []) as
        { name: string; checksum: string }[];
      const entry = artifacts.find((artifact) => artifact.name === name);
      // Old runs have no process.log entry; keep those diagnostic logs readable.
      if (!entry && name !== "process.log")
        throw new Error("Artifact was not recorded in the result manifest");
      if (entry && hash(readFileSync(path)) !== entry.checksum)
        throw new Error("Artifact checksum mismatch");
    }
  }
  return path;
}
const dashboard = createDashboard({
  all: activeDashboardRecords,
  strategies: () => catalog.strategies.filter(strategy => !scriptArchive.archivedIds().has(strategy.id)),
  runDir,
});
const evidence = createEvidenceRegistry(
  layout.evidenceRoot,
  layout.artifactsRoot,
);
const collectiveEvidenceCampaigns = [
  "all-strategies-all-charts-2026-09-16",
  "expanded-search-2026-09-16",
  "snd-fresh-backtest-2026-09-16",
  "combined-es-nq-refresh-2026-09-29",
] as const;
const collectiveEvidenceStatus = () => {
  try {
    for (const campaignId of collectiveEvidenceCampaigns)
      evidence.campaign(campaignId, "collective-catalog");
    return "";
  } catch (error) {
    return String(error instanceof Error ? error.message : error);
  }
};
const collective = createCollective(
  root,
  state,
  python,
  collectiveEvidenceStatus,
  () => ({ strategies: catalog.strategies.filter(strategy => !scriptArchive.archivedIds().has(strategy.id)), runs: projectedRuns.read(), evaluations: all<EvaluationView>("evaluation") }),
  () => scriptArchive.archivedIds(),
);
const portfolioRisk = createPortfolioRisk(state, () => projectedRuns.read(), () => scriptArchive.archivedIds());
portfolioTracking = createPortfolioTracking({
  root,
  state,
  python,
  cleanEnvironment,
  catalog: () => {
    const index = join(state, "collective", "index.json");
    return existsSync(index) ? JSON.parse(readFileSync(index, "utf8")) : null;
  },
  datasets: () => all<Dataset>("dataset"),
  // Tracking needs complete inputs and terminal status, but never the large
  // equity/trade previews. Reuse the revision-aware projection so the
  // five-second reconciliation does not parse every full run record again.
  runs: () => projectedRuns.read() as unknown as Run[],
  datasetFile: datasetService.file,
  runDataset: (dataset, protocol) => protocol === 2
    ? datasetService.protocol(dataset) : datasetService.legacy(dataset),
  sourceAvailable: input => existsSync(sourceSnapshots.resolve(input.source_snapshot || input.source_dir)),
  enqueue,
  pump,
});
portfolioTracking.reconcile();
setInterval(() => {
  if (stopping) return;
  try {
    datasetService.register();
    portfolioTracking?.reconcile();
  } catch (error) {
    console.error("Portfolio tracking reconciliation failed:", error);
  }
}, 5000).unref();
const eventStudies = createEventStudies(
  root,
  state,
  python,
  () => all<Dataset>("dataset"),
  cleanEnvironment,
);
const server = createServer(async (req, res) => {
  // Same-origin browser writes only. Bind loopback; reject cross-site form posts.
  const origin = req.headers.origin;
  if (
    origin &&
    ![
      `http://127.0.0.1:${port}`,
      "http://127.0.0.1:5173",
      "http://localhost:5173",
      `http://localhost:${port}`,
    ].includes(origin)
  )
    return json(res, { error: "Origin denied" }, 403);
  const url = new URL(req.url || "/", `http://127.0.0.1:${port}`);
  const parts = url.pathname.split("/").filter(Boolean);
  try {
    if (parts[0] !== "api" || parts[1] !== "workbench") {
      const webRoot = join(root, "dist"),
        asset = resolve(webRoot, "." + url.pathname);
      const file =
        asset.startsWith(webRoot + sep) &&
        existsSync(asset) &&
        statSync(asset).isFile()
          ? asset
          : join(webRoot, "index.html");
      if (!existsSync(file))
        return json(
          res,
          { error: "Use npm run dev:full or npm run build" },
          404,
        );
      const type = file.endsWith(".js")
        ? "text/javascript"
        : file.endsWith(".css")
          ? "text/css"
          : "text/html";
      res.writeHead(200, { "Content-Type": type });
      createReadStream(file).pipe(res);
      return;
    }
    const action = parts[2];
    if (action === 'event-studies') {
      if (req.method === 'GET' && !parts[3]) return json(res, { studies: eventStudies.list(), defaults: eventStudies.defaults, limits: eventStudies.limits });
      if (req.method === 'POST' && parts[3] === 'preview') return json(res, await eventStudies.preview(await body(req)));
      if (req.method === 'POST' && !parts[3]) return json(res, eventStudies.create(await body(req)), 201);
      if (req.method === 'GET' && parts[4] === 'artifacts') {
        const file = eventStudies.artifact(parts[3], parts[5], parts[6]);
        res.writeHead(200, { 'Content-Type': file.endsWith('.json') ? 'application/json' : file.endsWith('.csv') ? 'text/csv' : 'text/plain', ...(url.searchParams.has('download') ? { 'Content-Disposition': `attachment; filename="${parts[6]}"` } : {}) });
        createReadStream(file).pipe(res); return;
      }
      if (req.method === 'GET' && parts[3]) return json(res, eventStudies.read(parts[3]));
      if (req.method === 'POST' && parts[4] === 'run') return json(res, eventStudies.launch(parts[3], String((await body(req)).phase)));
      if (req.method === 'POST' && parts[4] === 'review') return json(res, eventStudies.review(parts[3], await body(req)));
      if (req.method === 'POST' && parts[4] === 'freeze') return json(res, eventStudies.freeze(parts[3]));
      if (req.method === 'POST' && parts[4] === 'cancel') return json(res, eventStudies.cancel(parts[3]));
      return json(res, { error: 'Unknown event-study operation' }, 404);
    }
    if (action === 'collective') {
      if (parts[3] === 'tracking') {
        if (req.method === 'GET' && parts.length === 4) {
          datasetService.register();
          return json(res, portfolioTracking!.reconcile());
        }
        if (req.method === 'PUT' && parts.length === 4)
          return json(res, portfolioTracking!.selection((await body(req)).ids));
        if (req.method === 'POST' && parts[5] === 'retry' && parts.length === 6)
          return json(res, portfolioTracking!.retry(parts[4]));
        return json(res, { error: 'Unknown portfolio tracking operation' }, 404);
      }
      if (req.method === 'GET' && parts[3] === 'status') return json(res, collective.status());
      if (req.method === 'GET') return json(res, collective.catalog());
      if (req.method === 'POST' && parts[3] === 'series') return json(res, collective.series((await body(req)).ids));
      if (req.method === 'POST' && parts[3] === 'risk') return json(res, portfolioRisk.risk((await body(req)).runIds));
      if (req.method === 'POST' && parts[3] === 'refresh') return json(res, collective.rebuild());
      if (req.method === 'POST' && parts[3] === 'import') return json(res, collective.importRun(String((await body(req)).runId || '')));
    }
    if (req.method === "GET" && action === "dashboard")
      return json(res, dashboard(url.searchParams.get("symbol") || undefined));
    if (req.method === "GET" && action === "nq-monthly") {
      const asset = parts[3] || "app-data.json";
      const contentTypes: Record<string, string> = {
        "app-data.json": "application/json; charset=utf-8",
        "report.csv": "text/csv; charset=utf-8",
        "monthly-pnl.csv": "text/csv; charset=utf-8",
        "monthly-heatmap.png": "image/png",
      };
      if (parts.length > 4 || !contentTypes[asset])
        return json(res, { error: "Unknown NQ comparison artifact" }, 404);
      const roles: Record<string, string> = {
        "app-data.json": "app-data",
        "report.csv": "report-data",
        "monthly-pnl.csv": "monthly-pnl",
        "monthly-heatmap.png": "monthly-heatmap",
      };
      const file = evidence
        .campaign("nq-monthly-2026-09-29", "workbench-nq-monthly-api")
        .file(roles[asset]);
      const archived = scriptArchive.archivedIds();
      if (archived.size && asset === "app-data.json") {
        res.setHeader("Cache-Control", "private, no-cache");
        return json(res, visibleMonthlyReport(JSON.parse(readFileSync(file, "utf8")), archived));
      }
      if (archived.size && asset.endsWith(".csv")) {
        res.writeHead(200, {
          "Content-Type": "text/csv; charset=utf-8",
          "Cache-Control": "private, no-cache",
          "Content-Disposition": `attachment; filename="${asset}"`,
        });
        return res.end(visibleMonthlyCsv(readFileSync(file, "utf8"), archived));
      }
      res.writeHead(200, {
        "Content-Type": contentTypes[asset],
        "Cache-Control": "private, no-cache",
        ...(asset.endsWith(".csv")
          ? { "Content-Disposition": `attachment; filename="${asset}"` }
          : {}),
      });
      createReadStream(file).pipe(res);
      return;
    }
    if (
      req.method === "POST" &&
      action === "runs" &&
      parts[3] === "delete-preview"
    )
      return json(res, deletion.preview((await body(req)).ids));
    if (req.method === "POST" && action === "runs" && parts[3] === "delete") {
      const payload = await body(req);
      return json(res, deletion.remove(payload.ids, payload.token));
    }
    if (req.method === "POST" && action === "runs" && parts[3] === "restore") {
      const payload = await body(req);
      return json(res, deletion.restore(payload.deletion_id));
    }
    if (req.method === "POST" && action === "runs" && parts.length === 4 &&
        ["archive", "unarchive"].includes(parts[3])) {
      const payload = await body(req);
      return json(res, parts[3] === "archive"
        ? researchArchive.archiveRuns(payload.ids)
        : researchArchive.unarchiveRuns(payload.ids));
    }
    if (req.method === "POST" && action === "configurations" && parts.length === 4 &&
        ["archive", "unarchive"].includes(parts[3])) {
      const payload = await body(req);
      return json(res, parts[3] === "archive"
        ? researchArchive.archiveConfiguration(payload.run_id)
        : researchArchive.unarchiveConfiguration(payload.run_id));
    }
    if (req.method === "GET" && action === "library" && parts[4] === "source") {
      const requested = decodeURIComponent(parts[3]);
      const entry = catalog.library?.entries.find(
        (item) =>
          item.id === requested ||
          item.source_id === requested ||
          item.aliases?.includes(requested) ||
          item.path_aliases?.includes(requested),
      );
      if (!entry)
        return json(res, { error: "Source is not in the Python library" }, 404);
      const file = resolve(root, entry.path);
      if (!file.startsWith(root + sep) || !/\.(py|pine)$/.test(file))
        throw new Error("Invalid library path");
      const bytes = readFileSync(file);
      if (createHash("sha256").update(bytes).digest("hex") !== entry.file_hash)
        throw new Error(
          "Source changed since discovery; scan scripts and reopen this entry",
        );
      return json(res, {
        source: bytes.toString("utf8"),
        file_hash: entry.file_hash,
      });
    }
    if (req.method === "POST" && action === "scripts" && parts[3] === "archive") {
      await refreshCatalog();
      const id = (await body(req)).id;
      if (typeof id !== "string") throw new Error("Choose a script to archive");
      const strategy = catalog.strategies.find(candidate => candidate.id === id);
      if (!strategy) throw new Error("Script is not available; scan scripts and try again");
      if (all<Run>("run").some(run => run.input.strategy.id === id && ["Queued", "Running"].includes(run.status)) ||
          all<Evaluation>("evaluation").some(evaluation => evaluation.candidates?.[0]?.strategy.id === id && ["Queued", "Running"].includes(evaluation.status)))
        throw new Error("Wait for this script's active research to finish before archiving it");
      const archived = scriptArchive.archive(strategy, catalog.strategies);
      await refreshCatalog();
      return json(res, archived);
    }
    if (req.method === "POST" && action === "scripts" && parts[3] === "restore") {
      const id = (await body(req)).id;
      if (typeof id !== "string") throw new Error("Choose a script to restore");
      await refreshCatalog();
      if (catalog.strategies.some(strategy => strategy.id === id))
        throw new Error("A runnable script already uses this strategy ID");
      const restored = scriptArchive.restore(id, entry => {
        const output = execFileSync(python, ["-m", "workbench.contract", root], {
          cwd: root,
          env: cleanEnvironment(),
          encoding: "utf8",
          windowsHide: true,
        });
        const discovered = JSON.parse(output) as {
          strategies: Strategy[];
          errors: { file?: string; error: string }[];
        };
        const strategy = discovered.strategies.find(candidate => candidate.id === id && candidate.file === entry.original_path);
        if (!strategy) {
          const filename = entry.original_path.split("/").at(-1);
          const reason = discovered.errors.find(error => error.file === filename)?.error || "the adapter was not rediscovered";
          throw new Error(`Cannot restore this script: ${reason}`);
        }
        executionSourceFingerprint(root, strategy);
      });
      await refreshCatalog();
      return json(res, restored);
    }
    if (req.method === "GET" && action === "state") {
      datasetService.register();
      const summary = url.searchParams.get("view") === "summary";
      const archivedScripts = scriptArchive.list();
      const archived = new Set(archivedScripts.map(script => script.id));
      const importJob = datasetService.job();
      const databaseRevision = summary ? projectedRuns.revision() : "";
      const cacheKey = summary
        ? JSON.stringify([databaseRevision, catalogRevision, archivedScripts, importJob])
        : "";
      if (summary && cachedSummary?.key === cacheKey)
        return sendSummary(req, res, cachedSummary.encoded, cachedSummary.etag);
      const allRuns = summary ? projectedRuns.read(databaseRevision) : all<Run>("run");
      const runs = allRuns.filter(run => !archived.has(run.input.strategy.id));
      const visibleRunIds = new Set(runs.map(run => run.id));
      const knownRunIds = new Set(allRuns.map(run => run.id));
      const allEvaluations = all<Evaluation>("evaluation");
      const evaluations = allEvaluations.filter(evaluation =>
        !archived.has(evaluation.candidates?.[0]?.strategy.id || ""));
      const visibleEvaluationIds = new Set(evaluations.map(evaluation => evaluation.id));
      const hiddenEvaluationIds = new Set(allEvaluations
        .filter(evaluation => !visibleEvaluationIds.has(evaluation.id))
        .map(evaluation => evaluation.id));
      const payload = {
        ...catalog,
        strategies: catalog.strategies.filter(strategy => !archived.has(strategy.id)),
        archived_scripts: archivedScripts,
        research_archive: researchArchive.read(),
        datasets: all("dataset"),
        runs,
        experiments: all<{ run_ids?: string[] }>("experiment").filter(experiment => !experiment.run_ids?.length || experiment.run_ids.some(id => visibleRunIds.has(id)) || experiment.run_ids.every(id => !knownRunIds.has(id))),
        presets: all<{ input?: { strategy_id?: string } }>("preset").filter(preset => !archived.has(preset.input?.strategy_id || "")),
        watchlist: all<{ run_id: string }>("watch").filter(watch => visibleRunIds.has(watch.run_id)),
        evaluations,
        regimes: all<{ evaluation_id: string }>("regime").filter(regime =>
          !hiddenEvaluationIds.has(regime.evaluation_id)),
        views: all("view"),
        import: importJob,
        limits: { concurrency, maxBatch },
      };
      if (!summary) return json(res, payload);
      const encoded = JSON.stringify(payload);
      const etag = `"${hash(encoded)}"`;
      cachedSummary = { key: cacheKey, encoded, etag };
      return sendSummary(req, res, encoded, etag);
    }
    if (req.method === "POST" && action === "discover") {
      await refreshCatalog(true);
      const archived = scriptArchive.archivedIds();
      return json(res, { ...catalog, strategies: catalog.strategies.filter(strategy => !archived.has(strategy.id)), archived_scripts: scriptArchive.list() });
    }
    if (req.method === "POST" && action === "import") {
      return json(res, datasetService.importLocal(), 202);
    }
    if (req.method === "POST" && action === "preview") {
      const inputs = buildInputs(await body(req));
      return json(res, {
        jobs: inputs.length,
        parameters: inputs.map((i) => i.parameters),
        warmup: await previewWarmup(python, root, cleanEnvironment(), inputs as Input[]),
      });
    }
    if (action === "evaluations") {
      if (req.method === "POST" && parts[3] === "preview")
        return json(res, research.preview(await body(req)));
      if (req.method === "POST" && !parts[3])
        return json(res, research.launch(await body(req)), 201);
      if (req.method === "POST" && parts[4] === "cancel")
        return json(res, research.abort(parts[3]));
      if (req.method === "POST" && parts[4] === "regimes")
        return json(res, research.regime(parts[3], await body(req)), 201);
      if (req.method === "GET" && parts[3])
        return json(res, research.detail(parts[3]));
    }
    if (req.method === "GET" && action === "research-artifact") {
      const file = research.artifact(
        String(url.searchParams.get("id")),
        String(url.searchParams.get("name")),
        String(url.searchParams.get("kind")),
      );
      res.writeHead(200, {
        "Content-Type": file.endsWith(".json")
          ? "application/json"
          : "text/csv",
        "Content-Disposition": `attachment; filename="${file.split(/[\\/]/).pop()}"`,
      });
      createReadStream(file).pipe(res);
      return;
    }
    if (req.method === "POST" && action === "runs" && parts.length === 3)
      return json(res, launch(await body(req)), 201);
    if (action === "runs" && parts[3]) {
      const id = parts[3],
        run = get<Run>("run", id);
      if (req.method === "POST" && parts[4] === "stage-assessments") {
        if (run.input.portfolio_replay)
          throw new Error("Portfolio tracking runs cannot receive research stage assessments");
        if (scriptArchive.archivedIds().has(run.input.strategy.id))
          throw new Error("Restore this script before recording a stage assessment");
        const payload = await body(req);
        await refreshCatalog();
        const freshRun = get<Run>("run", id);
        const runs = projectedRuns.read();
        const evaluations = all<EvaluationView>("evaluation");
        const statuses = strategyStageStatuses(catalog.strategies, runs, evaluations);
        const seed = runs.find(candidate => candidate.id === id);
        if (!seed || !catalog.strategies.some(strategy => strategy.id === seed.input.strategy.id)) throw new Error("Current strategy source is unavailable");
        const matching = runs.filter(candidate => !candidate.input.portfolio_replay && candidate.input.strategy.id === seed.input.strategy.id && runConfigurationKey(candidate) === runConfigurationKey(seed));
        const status = statuses.byRun.get(id)!;
        if (status.kind === "retest-required") throw new Error("Retest the current execution source before assessing it");
        const assessment = createStageAssessment(payload, seed, status, matching, evaluations, now(), randomUUID());
        freshRun.stage_assessments = [...(freshRun.stage_assessments || []), assessment];
        saveRun(freshRun);
        return json(res, assessment, 201);
      }
      if (req.method === "POST" && parts[4] === "readiness") {
        if (run.input.portfolio_replay)
          throw new Error("Portfolio tracking runs cannot receive research readiness reviews");
        if (scriptArchive.archivedIds().has(run.input.strategy.id))
          throw new Error("Restore this script before recording readiness");
        const payload = await body(req);
        await refreshCatalog();
        const freshRun = get<Run>("run", id);
        const runs = projectedRuns.read();
        const evaluations = all<EvaluationView>("evaluation");
        const statuses = strategyStageStatuses(catalog.strategies, runs, evaluations);
        const seed = runs.find(candidate => candidate.id === id)!;
        const key = runConfigurationKey(seed);
        const matching = runs.filter(candidate => !candidate.input.portfolio_replay && candidate.input.strategy.id === seed.input.strategy.id && runConfigurationKey(candidate) === key);
        const review = createReadinessReview(payload, seed, statuses.byRun.get(id)!, matching, evaluations, key, now(), randomUUID());
        freshRun.readiness_reviews = [...(freshRun.readiness_reviews || []), review];
        saveRun(freshRun);
        return json(res, review, 201);
      }
      if (req.method === "POST" && parts[4] === "cancel")
        return json(res, cancel(id));
      if (req.method === "POST" && parts[4] === "retry") {
        if (run.input.portfolio_replay)
          throw new Error("Retry portfolio updates from the portfolio tracking controls");
        const retry = enqueue({ ...run.input, retry_of: id }, run.watch_id);
        pump();
        return json(res, retry, 201);
      }
      if (req.method === "PATCH") {
        const edits = await body(req);
        const editableRun = get<Run>("run", id);
        editableRun.notes = String(edits.notes ?? editableRun.notes ?? "").slice(0, 10000);
        editableRun.tags = String(edits.tags ?? editableRun.tags ?? "").slice(0, 1000);
        saveRun(editableRun);
        return json(res, editableRun);
      }
      if (req.method === "GET" && parts[4] === "artifact") {
        const name = url.searchParams.get("name") || "manifest.json",
          path = safeArtifact(id, name);
        if (!existsSync(path)) throw new Error("Artifact is not available yet");
        res.writeHead(200, {
          "Content-Type": name.endsWith(".json")
            ? "application/json"
            : "text/plain",
          "Content-Disposition": `attachment; filename="${name}"`,
        });
        createReadStream(path).pipe(res);
        return;
      }
      if (req.method === "GET" && parts[4] === "export") {
        const sourceFolder = sourceSnapshots.resolve(
          run.input.source_snapshot || run.input.source_dir,
        );
        return json(res, {
          run,
          environment: JSON.parse(
            readFileSync(
              join(sourceFolder, "environment.json"),
              "utf8",
            ),
          ),
          source_files: sourceExport(sourceFolder),
        });
      }
      if (req.method === "GET") {
        const path = safeArtifact(id, "process.log");
        return json(res, {
          ...run,
          log: existsSync(path) ? readFileSync(path, "utf8") : "",
        });
      }
    }
    if (req.method === "POST" && action === "presets") {
      const b = await body(req);
      buildInputs(b.input as RecordValue);
      const id = randomUUID();
      const value = {
        id,
        name: String(b.name || "Preset").slice(0, 100),
        input: b.input,
      };
      put("preset", id, value);
      return json(res, value, 201);
    }
    if (req.method === "POST" && action === "views") {
      const b = await body(req),
        id = randomUUID();
      const value = {
        id,
        name: String(b.name || "View"),
        filter: String(b.filter || ""),
        stage: String(b.stage || ""),
        status: String(b.status || ""),
      };
      put("view", id, value);
      return json(res, value, 201);
    }
    if (req.method === "POST" && action === "watchlist" && !parts[3]) {
      const b = await body(req),
        run = get<Run>("run", String(b.run_id));
      if (run.input.portfolio_replay)
        throw new Error("Portfolio tracking runs cannot be frozen as research runs");
      if (scriptArchive.archivedIds().has(run.input.strategy.id))
        throw new Error("Restore this script before freezing a run");
      if (run.status !== "Succeeded")
        throw new Error("Only successful runs can be frozen");
      if (!String(b.reason || "").trim())
        throw new Error("Record a reason for freezing");
      const id = randomUUID(),
        value = {
          id,
          run_id: run.id,
          frozen_at: now(),
          reason: String(b.reason).slice(0, 2000),
          configuration_id: run.input.configuration_id,
          source: "Updated historical replay",
        };
      put("watch", id, value);
      return json(res, value, 201);
    }
    if (
      req.method === "POST" &&
      action === "watchlist" &&
      parts[4] === "update"
    ) {
      const watch = get<{ run_id: string }>("watch", parts[3]),
        original = get<Run>("run", watch.run_id);
      if (original.input.portfolio_replay)
        throw new Error("Portfolio tracking runs update through the portfolio controls");
      if (
        all<Run>("run").some(
          (r) =>
            r.watch_id === parts[3] && ["Queued", "Running"].includes(r.status),
        )
      )
        throw new Error("A tracking update is already pending");
      const latest = all<Dataset>("dataset")
        .filter((d) => d.symbol === original.input.dataset.symbol)
        .sort(
          (a, b) =>
            b.last.localeCompare(a.last) ||
            b.registered_at.localeCompare(a.registered_at),
        )[0];
      if (!latest || latest.first.slice(0, 10) > original.input.start)
        throw new Error("Latest version does not cover the original start");
      const history = all<Run>("run").filter(
        (r) => r.watch_id === parts[3] && r.status === "Succeeded",
      );
      const previous = history[0] || original;
      if (
        latest.id === previous.input.dataset.id &&
        latest.last.slice(0, 10) <= previous.input.end
      )
        return json(res, { status: "No new data" });
      const run = enqueue(
        {
          ...original.input,
          dataset:
            original.input.protocol === 2
              ? datasetService.protocol(latest)
              : datasetService.legacy(latest),
          end: latest.last.slice(0, 10),
          stage: "Tracking",
          retry_of: undefined,
        },
        parts[3],
      );
      pump();
      return json(res, run, 201);
    }
    if (req.method === "POST" && action === "compare") {
      const b = await body(req),
        ids = b.ids as string[];
      if (!Array.isArray(ids) || ids.length < 2 || ids.length > 8)
        throw new Error("Select 2–8 runs");
      const runs = ids.map((id) => get<Run>("run", id));
      if (runs.some((r) => r.status !== "Succeeded"))
        throw new Error("Comparisons require successful runs");
      if (b.mode === "aligned") return json(res, await aligned(runs));
      return json(res, { mode: "As run", runs });
    }
    json(res, { error: "Route not found" }, 404);
  } catch (e) {
    json(res, { error: e instanceof Error ? e.message : String(e) }, 400);
  }
});
function sourceExport(folder: string): Record<string, string> {
  const output: Record<string, string> = {};
  function walk(dir: string) {
    for (const item of readdirSync(dir, { withFileTypes: true })) {
      const file = join(dir, item.name);
      if (item.isDirectory() && item.name !== "__pycache__") walk(file);
      else if (item.isFile() && /\.(py|pine|ts|json)$/.test(file))
        output[relative(folder, file)] = readFileSync(file, "utf8");
    }
  }
  walk(folder);
  return output;
}
function aligned(runs: Run[]): Promise<unknown> {
  const fields = [
    "capital",
    "fee",
    "slippage",
    "session",
    "timeframe",
  ] as const;
  if (
    runs.some(
      (r) =>
        (r.input.strategy.execution_model || "signals-v1") !==
          (runs[0].input.strategy.execution_model || "signals-v1") ||
        fields.some((k) => r.input[k] !== runs[0].input[k]) ||
        (r.input.delay_bars || 0) !== (runs[0].input.delay_bars || 0) ||
        r.input.dataset.currency !== runs[0].input.dataset.currency,
    )
  )
    throw new Error(
      "Aligned comparison requires matching capital, costs, execution delay, session, timeframe and currency. Launch comparable runs.",
    );
  return new Promise((resolveDone, reject) => {
    const child = spawn(
      python,
      [
        "-m",
        "workbench.compare",
        ...runs.map((r) => join(runDir(r.id), "input.json")),
      ],
      { cwd: root, env: cleanEnvironment(), windowsHide: true },
    );
    let result = "",
      error = "";
    child.stdout.on("data", (d) => {
      result += d;
    });
    child.stderr.on("data", (d) => {
      error += d;
    });
    child.on("error", reject);
    child.on("close", (code) => {
      try {
        if (code !== 0) throw new Error(error);
        resolveDone(JSON.parse(result));
      } catch (e) {
        reject(e);
      }
    });
  });
}
await refreshCatalog();
setInterval(() => {
  void Promise.resolve().then(() => refreshCatalog()).catch(error => {
    catalog.errors = [{ error: String(error) }];
    catalogRevision += 1;
  });
}, 5000).unref();
server.listen(port, "127.0.0.1", () => {
  console.log(
    `Strategy Workbench: http://127.0.0.1:${port} (${concurrency} workers, max ${maxBatch} runs/batch)`,
  );
  pump();
});
function shutdown(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  void supervisorHeartbeat.stop();
  eventStudies.stop();
  research.stop();
  runQueue.stop();
  server.close();
  setTimeout(() => process.exit(exitCode), 500).unref();
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
