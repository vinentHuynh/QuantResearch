import { createServer } from "node:http";
import { DatabaseSync } from "node:sqlite";
import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  readdirSync,
  createReadStream,
  statSync,
} from "node:fs";
import { resolve, join, relative, sep } from "node:path";
import { createResearch } from "../features/evaluations/research.ts";
import { createRunDeletion } from "../features/runs/runDeletion.ts";
import { createDashboard } from "../features/scorecards/dashboard.ts";
import { createCollective } from "../features/portfolio/collective.ts";
import { createDatasets } from "../features/datasets/datasets.ts";
import { runSummaries } from "../infra/stateSummary.ts";
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
writeFileSync(
  supervisorFile,
  JSON.stringify({ token: supervisorToken, pid: process.pid }),
);
setInterval(
  () =>
    writeFileSync(
      supervisorFile,
      JSON.stringify({ token: supervisorToken, pid: process.pid }),
    ),
  2000,
).unref();
const db = new DatabaseSync(join(state, "workbench.sqlite3"));
db.exec("PRAGMA journal_mode=WAL");
const records = createRecordRepository(db);
const put = records.put;
const get = records.get;
const all = records.all;
const rawRecord = records.raw;
const now = () => new Date().toISOString();
const hash = (value: string | Buffer) =>
  createHash("sha256").update(value).digest("hex");
const runDir = (id: string) => join(state, "runs", id);
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
let discoveryTask: Promise<void> | null = null;
function refreshCatalog(): Promise<void> {
  if (discoveryTask) return discoveryTask;
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
      } catch (e) {
        catalog.errors = [{ error: String(e) }];
      }
      discoveryTask = null;
      resolveDone();
    });
  });
  return discoveryTask;
}
const datasetService = createDatasets({
  root,
  state,
  python,
  cleanEnvironment,
  put,
  raw: rawRecord,
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
  const strategy = catalog.strategies.find((s) => s.id === body.strategy_id);
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
});
const { enqueue, pump, cancel } = runQueue;
runQueue.recoverInterrupted();
const deletion = createRunDeletion({
  db,
  state,
  all,
  put,
  raw: rawRecord,
  active: runQueue.isActive,
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
  all,
  strategies: () => catalog.strategies,
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
);
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
      if (req.method === 'GET' && parts[3] === 'status') return json(res, collective.status());
      if (req.method === 'GET') return json(res, collective.catalog());
      if (req.method === 'POST' && parts[3] === 'series') return json(res, collective.series((await body(req)).ids));
      if (req.method === 'POST' && parts[3] === 'refresh') return json(res, collective.rebuild());
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
    if (req.method === "GET" && action === "state") {
      datasetService.register();
      const summary = url.searchParams.get("view") === "summary";
      const payload = {
        ...catalog,
        datasets: all("dataset"),
        runs: summary ? runSummaries(db) : all("run"),
        experiments: all("experiment"),
        presets: all("preset"),
        watchlist: all("watch"),
        evaluations: all("evaluation"),
        regimes: all("regime"),
        views: all("view"),
        import: datasetService.job(),
        limits: { concurrency, maxBatch },
      };
      if (!summary) return json(res, payload);
      const encoded = JSON.stringify(payload);
      const etag = `"${hash(encoded)}"`;
      res.setHeader("ETag", etag);
      res.setHeader("Cache-Control", "private, no-cache");
      if (req.headers["if-none-match"] === etag) {
        res.writeHead(304);
        return res.end();
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(encoded);
    }
    if (req.method === "POST" && action === "discover") {
      await refreshCatalog();
      return json(res, catalog);
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
      if (req.method === "POST" && parts[4] === "cancel")
        return json(res, cancel(id));
      if (req.method === "POST" && parts[4] === "retry") {
        const retry = enqueue({ ...run.input, retry_of: id }, run.watch_id);
        pump();
        return json(res, retry, 201);
      }
      if (req.method === "PATCH") {
        const edits = await body(req);
        run.notes = String(edits.notes ?? run.notes ?? "").slice(0, 10000);
        run.tags = String(edits.tags ?? run.tags ?? "").slice(0, 1000);
        saveRun(run);
        return json(res, run);
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
  void refreshCatalog();
}, 5000).unref();
server.listen(port, "127.0.0.1", () => {
  console.log(
    `Strategy Workbench: http://127.0.0.1:${port} (${concurrency} workers, max ${maxBatch} runs/batch)`,
  );
  pump();
});
function shutdown() {
  stopping = true;
  eventStudies.stop();
  research.stop();
  runQueue.stop();
  server.close();
  setTimeout(() => process.exit(0), 500).unref();
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
