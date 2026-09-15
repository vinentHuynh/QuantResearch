import { createServer } from "node:http";
import { DatabaseSync } from "node:sqlite";
import { spawn, execFileSync, type ChildProcess } from "node:child_process";
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
import { resolve, join, relative, dirname, sep } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import { createResearch } from "./research.ts";
import { createRunDeletion } from "./runDeletion.ts";
import { createDashboard } from "./dashboard.ts";

// Node 24 executes TypeScript directly. No shell commands contain UI input.
type RecordValue = Record<string, unknown>;
type Parameter = {
  type: string;
  default: unknown;
  minimum?: number;
  maximum?: number;
  choices?: string[];
  required_when?: RecordValue;
};
type Strategy = {
  id: string;
  name: string;
  file: string;
  file_hash: string;
  timeframes: string[];
  parameters: Record<string, Parameter>;
  execution_model?: string;
  required_session?: string;
};
type Dataset = {
  id: string;
  symbol: string;
  first: string;
  last: string;
  path: string;
  checksum: string;
  registered_at: string;
  currency: string;
};
export type Run = {
  id: string;
  status: string;
  created_at: string;
  input: Input;
  started_at?: string;
  ended_at?: string;
  error?: string;
  result?: RecordValue;
  notes?: string;
  tags?: string;
  watch_id?: string;
};
export type Input = {
  protocol: number;
  id: string;
  experiment_id: string;
  strategy: Strategy;
  dataset: Dataset;
  parameters: RecordValue;
  start: string;
  end: string;
  timeframe: string;
  session: string;
  stage: string;
  capital: number;
  fee: number;
  slippage: number;
  warmup_days: number;
  timeout: number;
  source_dir: string;
  source_hash: string;
  configuration_id: string;
  development_end: string;
  selection_time: string;
  hypothesis: string;
  retry_of?: string;
  criteria: string;
  delay_bars?: number;
  research?: {
    evaluation_id: string;
    fold: number;
    role: string;
    candidate: number;
    scenario: string;
  };
};
const root = resolve(import.meta.dirname, "..");
const state = resolve(
  process.env.WORKBENCH_HOME || join(root, "data/workbench"),
);
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
db.exec(
  "PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(kind,id))",
);
function put(kind: string, id: string, body: unknown) {
  db.prepare(
    "INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
  ).run(kind, id, JSON.stringify(body));
}
function get<T>(kind: string, id: string): T {
  const row = db
    .prepare("SELECT body FROM records WHERE kind=? AND id=?")
    .get(kind, id);
  if (!row) throw new Error(`${kind} not found`);
  return JSON.parse(String(row.body));
}
function all<T>(kind: string): T[] {
  return db
    .prepare("SELECT body FROM records WHERE kind=? ORDER BY rowid DESC")
    .all(kind)
    .map((r) => JSON.parse(String(r.body)));
}
const now = () => new Date().toISOString();
const hash = (value: string | Buffer) =>
  createHash("sha256").update(value).digest("hex");
const runDir = (id: string) => join(state, "runs", id);
function saveRun(run: Run) {
  put("run", run.id, run);
}
let stopping = false;
const active = new Map<string, ChildProcess>();
const stoppingJobs = new Set<string>();
const deletion = createRunDeletion({
  db,
  state,
  all,
  active: (id) => active.has(id),
});
let importJob: { status: string; log: string; error?: string } = {
  status: "Idle",
  log: "",
};
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
  return { ...env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" };
};
function stopProcess(child: ChildProcess) {
  if (!child.pid) return;
  if (process.platform === "win32")
    spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], {
      windowsHide: true,
      stdio: "ignore",
    });
  else {
    try {
      process.kill(-child.pid, "SIGKILL");
    } catch {
      child.kill("SIGKILL");
    }
  }
}

// Workers monitor the supervisor lease and exit when its token changes or its
// heartbeat stops. A restarted supervisor never promotes partial artifacts.
for (const run of all<Run>("run")) {
  if (run.status === "Running") {
    run.status = "Interrupted";
    run.ended_at = now();
    run.error =
      "Supervisor restarted; completion was not confirmed. Retry creates a new attempt.";
    saveRun(run);
  }
}

let catalog: {
  strategies: Strategy[];
  errors: RecordValue[];
  library?: { entries: { id: string; path: string; file_hash: string }[] };
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
        catalog = JSON.parse(output);
      } catch (e) {
        catalog.errors = [{ error: String(e) }];
      }
      discoveryTask = null;
      resolveDone();
    });
  });
  return discoveryTask;
}
function registerDatasets() {
  const path = join(state, "datasets/catalog.json");
  if (!existsSync(path)) return;
  const imported = JSON.parse(readFileSync(path, "utf8"));
  for (const dataset of imported.datasets) put("dataset", dataset.id, dataset);
  if (imported.errors.length) importJob.error = JSON.stringify(imported.errors);
}
registerDatasets();
function importDatasets() {
  if (importJob.status === "Running") return;
  importJob = { status: "Running", log: "Scanning local data ZIP archives…\n" };
  const child = spawn(
    python,
    ["-m", "workbench.datasets", root, join(state, "datasets")],
    { cwd: root, env: cleanEnvironment(), windowsHide: true },
  );
  child.stdout.on("data", (x) => {
    importJob.log = (importJob.log + x).slice(-30000);
  });
  child.stderr.on("data", (x) => {
    importJob.log = (importJob.log + x).slice(-30000);
  });
  child.on("error", (e) => {
    importJob.error = e.message;
  });
  child.on("close", (code) => {
    registerDatasets();
    importJob.status = code === 0 && !importJob.error ? "Succeeded" : "Failed";
  });
}

function snapshot() {
  const files: string[] = [];
  function walk(folder: string) {
    for (const item of readdirSync(folder, { withFileTypes: true })) {
      const p = join(folder, item.name);
      if (item.isDirectory() && item.name !== "__pycache__") walk(p);
      else if (
        item.isFile() &&
        (p.endsWith(".py") ||
          p.endsWith(".pine") ||
          (folder.startsWith(join(root, "server")) && /\.(ts|json)$/.test(p)))
      )
        files.push(p);
    }
  }
  for (const folder of [
    "strategies",
    "workbench",
    "strategy_engine",
    "scripts",
    "server",
    "pine",
  ])
    walk(join(root, folder));
  files.push(
    ...readdirSync(root)
      .filter((name) => name.endsWith(".pine"))
      .map((name) => join(root, name)),
  );
  files.push(join(root, "package.json"), join(root, "package-lock.json"));
  const dependencies = execFileSync(
    python,
    ["-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
    { encoding: "utf8", windowsHide: true, env: cleanEnvironment() },
  );
  const environment = {
    python: execFileSync(python, ["--version"], {
      encoding: "utf8",
      windowsHide: true,
    }).trim(),
    platform: process.platform,
    dependencies: JSON.parse(dependencies),
  };
  const contents = files
    .sort()
    .map((file) => ({ file, bytes: readFileSync(file) }));
  const digest = hash(
    Buffer.concat([
      Buffer.from(JSON.stringify(environment)),
      ...contents.flatMap((x) => [
        Buffer.from(relative(root, x.file)),
        x.bytes,
      ]),
    ]),
  );
  const folder = join(state, "sources", digest);
  if (!existsSync(join(folder, "environment.json"))) {
    for (const { file, bytes } of contents) {
      const target = join(folder, relative(root, file));
      mkdirSync(dirname(target), { recursive: true });
      writeFileSync(target, bytes);
    }
    writeFileSync(
      join(folder, "environment.json"),
      JSON.stringify(environment, null, 2),
    );
    writeFileSync(
      join(folder, "sources.json"),
      JSON.stringify(
        Object.fromEntries(
          contents.map((x) => [relative(root, x.file), hash(x.bytes)]),
        ),
        null,
        2,
      ),
    );
  }
  return { folder, digest };
}
function date(value: unknown, label: string) {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
    !Number.isFinite(Date.parse(value)) ||
    new Date(value).toISOString().slice(0, 10) !== value
  )
    throw new Error(`${label}: expected valid YYYY-MM-DD`);
  return value;
}
function numeric(
  value: unknown,
  label: string,
  minimum: number,
  maximum: number,
  integer = false,
) {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < minimum ||
    value > maximum ||
    (integer && !Number.isInteger(value))
  )
    throw new Error(
      `${label}: expected ${integer ? "integer" : "number"} from ${minimum} to ${maximum}`,
    );
  return value;
}
function parameters(strategy: Strategy, supplied: RecordValue) {
  if (!supplied || typeof supplied !== "object" || Array.isArray(supplied))
    throw new Error("Parameters must be an object");
  for (const key of Object.keys(supplied))
    if (!(key in strategy.parameters))
      throw new Error(`Unknown parameter: ${key}`);
  const resolved: RecordValue = {};
  for (const [key, field] of Object.entries(strategy.parameters)) {
    const value = supplied[key] ?? field.default;
    if (["integer", "number"].includes(field.type))
      numeric(
        value,
        key,
        field.minimum ?? -1e10,
        field.maximum ?? 1e10,
        field.type === "integer",
      );
    else if (field.type === "boolean" && typeof value !== "boolean")
      throw new Error(`${key}: expected boolean`);
    else if (
      ["string", "enum"].includes(field.type) &&
      (typeof value !== "string" || value.length > 2000)
    )
      throw new Error(`${key}: expected string`);
    if (field.type === "enum" && !field.choices?.includes(String(value)))
      throw new Error(`${key}: unsupported choice`);
    resolved[key] = value;
  }
  for (const [key, field] of Object.entries(strategy.parameters))
    if (
      field.required_when &&
      Object.entries(field.required_when).every(
        ([k, v]) => resolved[k] === v,
      ) &&
      resolved[key] === ""
    )
      throw new Error(`${key}: required for this configuration`);
  return resolved;
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
        protocol: 1,
        strategy,
        dataset,
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
        warmup_days: numeric(body.warmup_days ?? 60, "Warmup", 0, 1000, true),
        development_end,
        selection_time: now(),
        hypothesis: String(body.hypothesis || "").slice(0, 2000),
        criteria: String(body.criteria || "").slice(0, 2000),
      })),
    ),
  );
}
function enqueue(input: Input, watchId?: string) {
  const id = randomUUID();
  input = { ...input, id };
  mkdirSync(runDir(id), { recursive: true });
  writeFileSync(join(runDir(id), "input.json"), JSON.stringify(input, null, 2));
  const run: Run = {
    id,
    status: "Queued",
    created_at: now(),
    input,
    watch_id: watchId,
  };
  saveRun(run);
  return run;
}
function launch(body: RecordValue) {
  const variants = buildInputs(body);
  const source = snapshot();
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
          source: source.digest,
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
        source_dir: source.folder,
        source_hash: source.digest,
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
function pump() {
  if (stopping) return;
  const queued = all<Run>("run")
    .filter((r) => r.status === "Queued")
    .reverse();
  while (active.size < concurrency && queued.length) execute(queued.shift()!);
}
function execute(run: Run) {
  run.status = "Running";
  run.started_at = now();
  saveRun(run);
  const inputFile = join(runDir(run.id), "input.json");
  const child = spawn(python, ["-m", "workbench.worker", inputFile], {
    cwd: run.input.source_dir,
    env: {
      ...cleanEnvironment(),
      WORKBENCH_SUPERVISOR_FILE: supervisorFile,
      WORKBENCH_SUPERVISOR_TOKEN: supervisorToken,
      PYTHONPATH: [
        run.input.source_dir,
        join(run.input.source_dir, "strategies"),
      ].join(process.platform === "win32" ? ";" : ":"),
    },
    windowsHide: true,
    detached: process.platform !== "win32",
  });
  active.set(run.id, child);
  let log = "";
  const logData = (chunk: Buffer) => {
    log = (log + chunk.toString()).slice(-100000);
    writeFileSync(join(runDir(run.id), "process.log"), log);
  };
  child.stdout?.on("data", logData);
  child.stderr?.on("data", logData);
  child.on("error", (e) => logData(Buffer.from(e.message)));
  const timeout = setTimeout(() => {
    stoppingJobs.add(run.id);
    const current = get<Run>("run", run.id);
    current.status = "Failed";
    current.error = `Timeout after ${run.input.timeout}s`;
    current.ended_at = now();
    saveRun(current);
    stopProcess(child);
  }, run.input.timeout * 1000);
  child.on("close", (code) => {
    clearTimeout(timeout);
    active.delete(run.id);
    const current = get<Run>("run", run.id);
    if (!stoppingJobs.delete(run.id) && current.status === "Running") {
      current.ended_at = now();
      try {
        if (code !== 0)
          throw new Error(`Python exited ${code}. Inspect process log.`);
        const manifest = JSON.parse(
          readFileSync(join(runDir(run.id), "manifest.json"), "utf8"),
        );
        if (
          manifest.protocol !== 1 ||
          manifest.run_id !== run.id ||
          !Number.isFinite(manifest.metrics?.net_return) ||
          !manifest.artifacts?.length
        )
          throw new Error("Invalid result manifest");
        for (const artifact of manifest.artifacts) {
          if (
            !["equity.csv", "trades.csv", "positions.csv"].includes(
              artifact.name,
            ) ||
            hash(readFileSync(join(runDir(run.id), artifact.name))) !==
              artifact.checksum
          )
            throw new Error("Artifact checksum mismatch");
        }
        current.status = "Succeeded";
        current.result = manifest;
      } catch (e) {
        current.status = "Failed";
        current.error = String(e);
      }
      saveRun(current);
    }
    pump();
  });
}
function cancel(id: string) {
  const run = get<Run>("run", id);
  if (!["Queued", "Running"].includes(run.status))
    throw new Error("Run is already terminal");
  run.status = "Canceled";
  run.ended_at = now();
  saveRun(run);
  const child = active.get(id);
  if (child) {
    stoppingJobs.add(id);
    stopProcess(child);
  }
  return run;
}

const research = createResearch({
  all,
  get,
  put,
  buildInputs,
  snapshot,
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

async function body(req: IncomingMessage): Promise<RecordValue> {
  let raw = "";
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > 1000000) throw new Error("Request too large");
  }
  return raw ? JSON.parse(raw) : {};
}
function json(res: ServerResponse, data: unknown, status = 200) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
}
function safeArtifact(id: string, name: string) {
  get<Run>("run", id);
  if (
    ![
      "input.json",
      "manifest.json",
      "process.log",
      "equity.csv",
      "trades.csv",
      "positions.csv",
    ].includes(name)
  )
    throw new Error("Unknown artifact");
  return join(runDir(id), name);
}
const dashboard = createDashboard({
  all,
  strategies: () => catalog.strategies,
  runDir,
});
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
    if (req.method === "GET" && action === "dashboard")
      return json(res, dashboard(url.searchParams.get("symbol") || undefined));
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
    if (req.method === "GET" && action === "library" && parts[4] === "source") {
      const entry = catalog.library?.entries.find(
        (item) => item.id === parts[3],
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
      registerDatasets();
      return json(res, {
        ...catalog,
        datasets: all("dataset"),
        runs: all("run"),
        experiments: all("experiment"),
        presets: all("preset"),
        watchlist: all("watch"),
        evaluations: all("evaluation"),
        regimes: all("regime"),
        views: all("view"),
        import: importJob,
        limits: { concurrency, maxBatch },
      });
    }
    if (req.method === "POST" && action === "discover") {
      await refreshCatalog();
      return json(res, catalog);
    }
    if (req.method === "POST" && action === "import") {
      importDatasets();
      return json(res, importJob, 202);
    }
    if (req.method === "POST" && action === "preview") {
      const inputs = buildInputs(await body(req));
      return json(res, {
        jobs: inputs.length,
        parameters: inputs.map((i) => i.parameters),
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
      if (req.method === "GET" && parts[4] === "export")
        return json(res, {
          run,
          environment: JSON.parse(
            readFileSync(
              join(run.input.source_dir, "environment.json"),
              "utf8",
            ),
          ),
          source_files: sourceExport(run.input.source_dir),
        });
      if (req.method === "GET") {
        const path = join(runDir(id), "process.log");
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
          dataset: latest,
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
  research.stop();
  for (const [id, child] of active) {
    const run = get<Run>("run", id);
    run.status = "Interrupted";
    run.ended_at = now();
    run.error = "Supervisor stopped";
    saveRun(run);
    stopProcess(child);
  }
  server.close();
  setTimeout(() => process.exit(0), 500).unref();
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
