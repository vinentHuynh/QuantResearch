import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import type { Dataset, Input, Run } from "../../core/contracts.ts";
import type { CollectiveCatalog, CollectiveItem } from "../../../shared/ts/portfolio.ts";
import { latestEsNqItems } from "../../../shared/ts/collective.ts";

export type TrackingStatus =
  | "up-to-date"
  | "waiting-for-data"
  | "queued"
  | "running"
  | "publishing"
  | "failed"
  | "manual-update-required";

export type TrackingItem = {
  status: TrackingStatus;
  dataset_last?: string;
  target_end?: string;
  simulated_through?: string;
  error?: string;
  run_id?: string;
};

type Job = {
  key: string;
  mode: "run" | "overnight";
  status: TrackingStatus;
  dataset_id: string;
  dataset_checksum: string;
  target_end: string;
  simulated_through: string;
  source_run_id?: string;
  run_id?: string;
  error?: string;
  updated_at: string;
};

type Saved = { version: 1; selection: string[]; jobs: Record<string, Job> };

type Dependencies = {
  root: string;
  state: string;
  python: string;
  cleanEnvironment: () => NodeJS.ProcessEnv;
  catalog: () => CollectiveCatalog | null;
  datasets: () => Dataset[];
  runs: () => Run[];
  datasetFile: (dataset: Dataset) => string;
  runDataset: (dataset: Dataset, protocol: number) => Dataset;
  sourceAvailable: (input: Input) => boolean;
  enqueue: (input: Input) => Run;
  pump: () => void;
  now?: () => string;
};

const DAY = 86400000;
const overnightKeys = new Set([
  "overnight-session__ES__1m__globex-overnight",
  "overnight-session__NQ__1m__globex-overnight",
]);
const legacyNqMomentum = {
  id: "f095fc8e4b66ac71d82d",
  key: "multi-speed-momentum__NQ__1h",
  sourceRunId: "0e7f5f5c-37e1-4fc4-9619-8d999ba3fcdd",
};

function canReplayLegacyNqMomentum(item: CollectiveItem): boolean {
  return item.id === legacyNqMomentum.id && item.key === legacyNqMomentum.key &&
    item.source === "Workbench" && item.symbol === "NQ" && item.timeframe === "1h" &&
    item.source_run_ids?.length === 1 && item.source_run_ids[0] === legacyNqMomentum.sourceRunId;
}

/** The dataset's final observed date is safe only after its 23:59 UTC bar. */
export function completeUtcThrough(last: string): string {
  const instant = new Date(last);
  if (!Number.isFinite(instant.getTime())) return "";
  const utc = instant.toISOString();
  const date = utc.slice(0, 10);
  if (utc.slice(11, 16) === "23:59") return date;
  return new Date(Date.parse(date + "T00:00:00Z") - DAY).toISOString().slice(0, 10);
}

function sourceRun(item: CollectiveItem, runs: Run[]): Run | undefined {
  const ids = new Set(item.source_run_ids || []);
  return runs
    .filter(run => ids.has(run.id) && run.status === "Succeeded" && !run.input.portfolio_replay &&
      run.input.dataset.symbol === item.symbol && run.input.start <= item.end)
    .sort((a, b) => b.input.end.localeCompare(a.input.end) || b.created_at.localeCompare(a.created_at))[0];
}

function savedState(file: string): Saved | null {
  if (!existsSync(file)) return null;
  const value: unknown = JSON.parse(readFileSync(file, "utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Portfolio tracking state is invalid");
  const data = value as Saved;
  if (data.version !== 1 || !Array.isArray(data.selection) ||
      data.selection.some(id => typeof id !== "string") ||
      !data.jobs || typeof data.jobs !== "object" || Array.isArray(data.jobs))
    throw new Error("Portfolio tracking state is invalid");
  return data;
}

export function createPortfolioTracking(d: Dependencies) {
  const folder = join(d.state, "collective");
  const file = join(folder, "tracking.json");
  const now = d.now || (() => new Date().toISOString());
  let saved = savedState(file);
  const activeHelpers = new Set<string>();
  const helperQueue: { id: string; job: Job }[] = [];
  let helperRunning = false;
  let reconciling = false;

  function persist() {
    if (!saved) return;
    mkdirSync(folder, { recursive: true });
    const partial = join(folder, `tracking.${randomUUID()}.tmp`);
    writeFileSync(partial, JSON.stringify(saved, null, 2));
    renameSync(partial, file);
  }

  function seed(catalog: CollectiveCatalog | null) {
    if (saved || !catalog) return;
    const defaults = latestEsNqItems(catalog);
    saved = {
      version: 1,
      selection: (defaults.length ? defaults : catalog.items.filter(item => item.working && !item.benchmark))
        .map(item => item.id),
      jobs: {},
    };
    persist();
  }

  function change(id: string, edits: Partial<Job>) {
    const job = saved?.jobs[id];
    if (!job) return;
    Object.assign(job, edits, { updated_at: now() });
    persist();
  }

  function fail(id: string, error: string) {
    change(id, { status: "failed", error: error.slice(-12000) });
  }

  function catalogItem(id: string) {
    return d.catalog()?.items.find(item => item.id === id);
  }

  function published(id: string, job: Job) {
    const item = catalogItem(id);
    const verified = (item as CollectiveItem & { verified_replay?: {
      dataset_checksum?: string;
      end?: string;
      source_run_id?: string;
    } } | undefined)?.verified_replay;
    return Boolean(item && verified &&
      verified.dataset_checksum === job.dataset_checksum &&
      verified.end === item.end &&
      verified.end <= job.target_end &&
      (!job.run_id || verified.source_run_id === job.run_id));
  }

  function pumpHelpers() {
    if (helperRunning || !helperQueue.length) return;
    helperRunning = true;
    const { id, job } = helperQueue.shift()!;
    change(id, { status: job.mode === "run" ? "publishing" : "running" });
    const args = job.mode === "run"
      ? [join(d.root, "scripts/portfolio-replay.py"), "publish-run", "--item-id", id, "--run-id", job.run_id!]
      : [join(d.root, "scripts/portfolio-replay.py"), "run-overnight", "--item-id", id,
        "--dataset-id", job.dataset_id, "--end", job.target_end];
    let output = "";
    let finished = false;
    const finish = (error?: string) => {
      if (finished) return;
      finished = true;
      activeHelpers.delete(id);
      helperRunning = false;
      const response = !error ? (() => {
        try { return JSON.parse(output.trim()) as {
          item_id?: string;
          no_new_session?: boolean;
          end?: string;
          dataset_id?: string;
        }; }
        catch { return null; }
      })() : null;
      if (error) fail(id, error);
      else if (response?.no_new_session && response.item_id === id &&
          response.dataset_id === job.dataset_id &&
          response.end === catalogItem(id)?.end)
        change(id, { status: "waiting-for-data", error: undefined });
      else if (!published(id, job))
        fail(id, "Replay helper finished but the verified catalog entry was not published.");
      else change(id, { status: "up-to-date", error: undefined });
      reconcile();
      pumpHelpers();
    };
    try {
      const child = spawn(d.python, args, {
        cwd: d.root,
        env: d.cleanEnvironment(),
        windowsHide: true,
      });
      child.stdout?.on("data", chunk => { output = (output + chunk).slice(-12000); });
      child.stderr?.on("data", chunk => { output = (output + chunk).slice(-12000); });
      child.on("error", error => finish(error.message));
      child.on("close", code => finish(code === 0 ? undefined : output || `Replay helper exited ${code}`));
    } catch (error) {
      finish(String(error));
    }
  }

  function helper(id: string, job: Job) {
    if (activeHelpers.has(id)) return;
    activeHelpers.add(id);
    change(id, { status: job.mode === "run" ? "publishing" : "queued", error: undefined });
    helperQueue.push({ id, job });
    pumpHelpers();
  }

  function enqueueRun(id: string, job: Job, source: Run, dataset: Dataset) {
    try {
      if (!d.sourceAvailable(source.input))
        throw new Error("The preserved source snapshot is unavailable; manual update required.");
      const original: Input = { ...source.input };
      delete original.research;
      delete original.retry_of;
      delete original.portfolio_replay;
      const input: Input = {
        ...original,
        id: "",
        dataset: d.runDataset(dataset, source.input.protocol),
        start: source.input.start,
        end: job.target_end,
        stage: "Tracking",
        selection_time: now(),
        portfolio_replay: {
          item_id: id,
          source_run_id: source.id,
          anchor_start: source.input.start,
        },
      };
      const run = d.enqueue(input);
      change(id, { status: "queued", run_id: run.id, error: undefined });
      d.pump();
    } catch (error) {
      fail(id, String(error));
    }
  }

  function resume(id: string, job: Job, source: Run | undefined, dataset: Dataset) {
    if (job.mode === "overnight") {
      if (published(id, job)) change(id, { status: "up-to-date", error: undefined });
      else helper(id, job);
      return;
    }
    const frozenSource = job.source_run_id
      ? d.runs().find(candidate => candidate.id === job.source_run_id)
      : source;
    if (!frozenSource) {
      fail(id, "The saved baseline run is unavailable; manual update required.");
      return;
    }
    const run = d.runs().find(candidate => candidate.id === job.run_id);
    if (!run || run.status === "Interrupted") {
      enqueueRun(id, job, frozenSource, dataset);
    } else if (run.status === "Queued" || run.status === "Running") {
      if (job.status !== run.status.toLowerCase())
        change(id, { status: run.status.toLowerCase() as TrackingStatus });
    } else if (run.status === "Succeeded") {
      if (published(id, job)) change(id, { status: "up-to-date", error: undefined });
      else helper(id, job);
    } else {
      fail(id, run.error || `Replay run ${run.status.toLowerCase()}.`);
    }
  }

  function newJob(id: string, mode: Job["mode"], item: CollectiveItem, dataset: Dataset,
      target: string, source?: Run) {
    if (!saved) return;
    const job: Job = {
      key: JSON.stringify([id, dataset.checksum, target]),
      mode,
      status: "queued",
      dataset_id: dataset.id,
      dataset_checksum: dataset.checksum,
      target_end: target,
      simulated_through: item.end,
      source_run_id: source?.id,
      updated_at: now(),
    };
    saved.jobs[id] = job;
    persist();
    if (mode === "overnight") helper(id, job);
    else enqueueRun(id, job, source!, dataset);
  }

  function jobView(job: Job, datasetLast: string, simulated: string): TrackingItem {
    return {
      status: job.status,
      ...(datasetLast ? { dataset_last: datasetLast } : {}),
      target_end: job.target_end,
      simulated_through: simulated,
      ...(job.error ? { error: job.error } : {}),
      ...(job.run_id ? { run_id: job.run_id } : {}),
    };
  }

  function evaluate(catalog: CollectiveCatalog, id: string, datasets: Dataset[], runs: Run[]): TrackingItem {
    const item = catalog.items.find(candidate => candidate.id === id);
    if (!item) return { status: "manual-update-required", error: "This book is no longer in the portfolio catalog." };
    const simulated = item.end;
    const sameSymbol = datasets.filter(dataset => dataset.symbol === item.symbol);
    const dataLast = sameSymbol.map(dataset => completeUtcThrough(dataset.last)).sort().at(-1) || "";
    const base: TrackingItem = {
      status: "up-to-date",
      ...(dataLast ? { dataset_last: dataLast } : {}),
      simulated_through: simulated,
    };
    const mode: Job["mode"] | null = overnightKeys.has(item.key) &&
        item.source === "Expanded" && item.latest_replay
      ? "overnight"
      : item.source === "Current workbench" && !item.key.includes("__pinned__") && item.source_run_ids?.length
        ? "run"
        : item.source === "Workbench" && item.source_run_ids?.length &&
            (item.latest_replay || canReplayLegacyNqMomentum(item))
          ? "run" : null;
    const source = mode === "run" ? sourceRun(item, runs) : undefined;
    if (!mode || (mode === "run" && !source))
      return { ...base, status: "manual-update-required",
        error: mode ? "The saved baseline run needed for a replay is unavailable."
          : "This older campaign or pinned history requires a manual update." };
    const anchor = mode === "run"
      ? source!.input.start
      : item.coverage.at(-1)?.start || item.start;
    const lookbackDays = mode === "run"
      ? Math.max(0, Number(source!.input.warmup_days) || 0) : 4;
    const requiredFirst = new Date(Date.parse(anchor + "T00:00:00Z") -
      lookbackDays * DAY).toISOString().slice(0, 10);
    const available = sameSymbol
      .filter(dataset => {
        if (!dataset.checksum || dataset.first.slice(0, 10) > requiredFirst) return false;
        try { return existsSync(d.datasetFile(dataset)); }
        catch { return false; }
      })
      .map(dataset => ({ dataset, through: completeUtcThrough(dataset.last) }))
      .filter(candidate => candidate.through)
      .sort((a, b) => b.through.localeCompare(a.through) ||
        b.dataset.registered_at.localeCompare(a.dataset.registered_at));
    const newest = available[0];
    if (!newest) return {
      ...base,
      status: dataLast > simulated ? "manual-update-required" : "waiting-for-data",
      ...(dataLast > simulated ? { error: "Newer data does not cover the preserved replay start." } : {}),
    };
    if (newest.through <= simulated) return {
      ...base,
      status: newest.through < simulated ? "waiting-for-data" : "up-to-date",
    };
    const target = newest.through;
    const key = JSON.stringify([id, newest.dataset.checksum, target]);
    const existing = saved?.jobs[id];
    if (existing && ["queued", "running", "publishing"].includes(existing.status)) {
      const existingDataset = datasets.find(dataset => dataset.id === existing.dataset_id);
      if (existingDataset) resume(id, existing, source, existingDataset);
      else fail(id, "The dataset for the pending replay is unavailable.");
      return jobView(saved!.jobs[id], dataLast, simulated);
    }
    if (existing?.key === key && existing.status === "failed")
      return jobView(existing, dataLast, simulated);
    if (existing?.key === key && existing.status === "waiting-for-data")
      return jobView(existing, dataLast, simulated);
    if (existing?.key === key && existing.status === "up-to-date" && published(id, existing))
      return jobView(existing, dataLast, simulated);
    newJob(id, mode, item, newest.dataset, target, source);
    return jobView(saved!.jobs[id], dataLast, simulated);
  }

  function reconcile() {
    if (reconciling) return statusSnapshot();
    reconciling = true;
    try {
      const catalog = d.catalog();
      seed(catalog);
      if (!catalog || !saved) return statusSnapshot();
      const datasets = d.datasets();
      const runs = d.runs();
      const items: Record<string, TrackingItem> = {};
      for (const id of saved.selection)
        items[id] = evaluate(catalog, id, datasets, runs);
      return { selection: [...saved.selection], items };
    } finally {
      reconciling = false;
    }
  }

  function statusSnapshot() {
    const items: Record<string, TrackingItem> = {};
    for (const id of saved?.selection || []) {
      const job = saved?.jobs[id];
      items[id] = job ? {
        status: job.status,
        target_end: job.target_end,
        simulated_through: job.simulated_through,
        ...(job.run_id ? { run_id: job.run_id } : {}),
        ...(job.error ? { error: job.error } : {}),
      } : { status: "waiting-for-data" };
    }
    return { selection: [...(saved?.selection || [])], items };
  }

  function selection(ids: unknown) {
    const catalog = d.catalog();
    if (!catalog) throw new Error("Portfolio catalog is unavailable.");
    if (!Array.isArray(ids) || ids.length > 100 || ids.some(id => typeof id !== "string") ||
        new Set(ids).size !== ids.length || ids.some(id => !catalog.items.some(item => item.id === id)))
      throw new Error("Choose up to 100 distinct portfolio book IDs.");
    seed(catalog);
    saved!.selection = [...ids];
    persist();
    return reconcile();
  }

  function retry(id: string) {
    if (!saved?.selection.includes(id)) throw new Error("Select this book before retrying.");
    const job = saved.jobs[id];
    if (!job || job.status !== "failed") throw new Error("Only failed portfolio updates can be retried.");
    delete saved.jobs[id];
    persist();
    return reconcile();
  }

  function onRunTerminal(run: Run) {
    const id = run.input.portfolio_replay?.item_id;
    if (!id || !saved) return;
    const job = saved.jobs[id];
    if (!job || job.run_id !== run.id) return;
    if (run.status === "Succeeded") helper(id, job);
    else fail(id, run.error || `Replay run ${run.status.toLowerCase()}.`);
  }

  return { reconcile, selection, retry, onRunTerminal };
}
