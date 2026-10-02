import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";

import type { Input, Run } from "./contracts.ts";
import { stopProcess } from "./processSupervisor.ts";

type Dependencies = {
  all: <T>(kind: string) => T[];
  get: <T>(kind: string, id: string) => T;
  saveRun: (run: Run) => void;
  runDir: (id: string) => string;
  python: string;
  concurrency: number;
  cleanEnvironment: () => NodeJS.ProcessEnv;
  sourceFolder: (reference: string) => string;
  supervisorFile: string;
  supervisorToken: string;
  hash: (value: string | Buffer) => string;
  now: () => string;
  validateInput?: (input: Input) => void;
  dataRevision?: () => string;
  onTerminal?: (run: Run) => void;
};

export function createRunQueue(d: Dependencies) {
  let stopping = false;
  const active = new Map<string, ChildProcess>();
  const stoppingJobs = new Set<string>();
  let pending: Run[] | null = null;
  let observedRevision: string | undefined;

  function queuedRuns() {
    const revision = d.dataRevision?.();
    if (pending === null || revision !== observedRevision) {
      // all() returns newest first. Persisted queued jobs must resume oldest first.
      pending = d.all<Run>("run").filter(run => run.status === "Queued").reverse();
      observedRevision = revision;
    }
    return pending;
  }

  function enqueue(input: Input, watchId?: string) {
    const id = randomUUID();
    input = { ...input, id };
    d.validateInput?.(input);
    const folder = d.runDir(id);
    mkdirSync(folder, { recursive: true });
    writeFileSync(join(folder, "input.json"), JSON.stringify(input, null, 2));
    const run: Run = {
      id,
      status: "Queued",
      created_at: d.now(),
      input,
      watch_id: watchId,
    };
    d.saveRun(run);
    pending?.push(run);
    return run;
  }

  function pump() {
    if (stopping || active.size >= d.concurrency) return;
    const queued = queuedRuns();
    while (active.size < d.concurrency && queued.length) execute(queued.shift()!);
  }

  function execute(run: Run) {
    run.status = "Running";
    run.started_at = d.now();
    d.saveRun(run);
    const inputFile = join(d.runDir(run.id), "input.json");
    const sourceFolder = d.sourceFolder(
      run.input.source_snapshot || run.input.source_dir,
    );
    const child = spawn(d.python, ["-m", "workbench.worker", inputFile], {
      cwd: sourceFolder,
      env: {
        ...d.cleanEnvironment(),
        WORKBENCH_SOURCE_DIR: sourceFolder,
        WORKBENCH_SUPERVISOR_FILE: d.supervisorFile,
        WORKBENCH_SUPERVISOR_TOKEN: d.supervisorToken,
        PYTHONPATH: [sourceFolder, join(sourceFolder, "strategies")].join(
          process.platform === "win32" ? ";" : ":",
        ),
      },
      windowsHide: true,
      detached: process.platform !== "win32",
    });
    active.set(run.id, child);
    const processLog = join(d.runDir(run.id), "process.log");
    writeFileSync(processLog, "");
    const logData = (chunk: Buffer) => appendFileSync(processLog, chunk);
    child.stdout?.on("data", logData);
    child.stderr?.on("data", logData);
    child.on("error", (error) => logData(Buffer.from(error.message)));
    const timeout = setTimeout(() => {
      stoppingJobs.add(run.id);
      const current = d.get<Run>("run", run.id);
      current.status = "Failed";
      current.error = `Timeout after ${run.input.timeout}s`;
      current.ended_at = d.now();
      d.saveRun(current);
      stopProcess(child);
    }, run.input.timeout * 1000);
    child.on("close", (code) => {
      clearTimeout(timeout);
      active.delete(run.id);
      const current = d.get<Run>("run", run.id);
      if (!stoppingJobs.delete(run.id) && current.status === "Running") {
        current.ended_at = d.now();
        try {
          if (code !== 0)
            throw new Error(`Python exited ${code}. Inspect process log.`);
          const manifestPath = join(d.runDir(run.id), "manifest.json");
          const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
          if (
            ![1, 2].includes(manifest.protocol) ||
            manifest.protocol !== run.input.protocol ||
            manifest.run_id !== run.id ||
            !Number.isFinite(manifest.metrics?.net_return) ||
            !manifest.artifacts?.length
          )
            throw new Error("Invalid result manifest");
          if (
            run.input.protocol === 2 &&
            (manifest.execution_source_hash !== run.input.execution_source_hash ||
              manifest.snapshot_hash !== run.input.snapshot_hash ||
              manifest.app_build_hash !== run.input.app_build_hash)
          )
            throw new Error("Result provenance does not match the run input");
          const artifactNames = new Set<string>();
          for (const artifact of manifest.artifacts) {
            if (
              ![
                "equity.csv",
                "trades.csv",
                "positions.csv",
                "signals.csv",
              ].includes(artifact.name) ||
              artifactNames.has(artifact.name) ||
              d.hash(readFileSync(join(d.runDir(run.id), artifact.name))) !==
                artifact.checksum
            )
              throw new Error("Artifact checksum mismatch");
            artifactNames.add(artifact.name);
          }
          const completed = {
            ...manifest,
            artifacts: [
              ...manifest.artifacts,
              {
                name: "process.log",
                checksum: d.hash(readFileSync(processLog)),
                bytes: statSync(processLog).size,
                rows: 0,
              },
            ],
          };
          const partial = join(
            d.runDir(run.id),
            `manifest.${randomUUID()}.partial`,
          );
          try {
            writeFileSync(partial, JSON.stringify(completed, null, 2));
            renameSync(partial, manifestPath);
          } catch (error) {
            if (existsSync(partial)) unlinkSync(partial);
            throw error;
          }
          current.status = "Succeeded";
          current.result = completed;
        } catch (error) {
          current.status = "Failed";
          current.error = String(error);
        }
        d.saveRun(current);
        try {
          d.onTerminal?.(current);
        } catch (error) {
          console.error("Tracking notification failed:", error);
        }
      }
      pump();
    });
  }

  function cancel(id: string) {
    const run = d.get<Run>("run", id);
    if (!["Queued", "Running"].includes(run.status))
      throw new Error("Run is already terminal");
    run.status = "Canceled";
    run.ended_at = d.now();
    d.saveRun(run);
    if (pending) pending = pending.filter(candidate => candidate.id !== id);
    const child = active.get(id);
    if (child) {
      stoppingJobs.add(id);
      stopProcess(child);
    }
    return run;
  }

  function recoverInterrupted() {
    const persisted = d.all<Run>("run");
    for (const run of persisted) {
      if (run.status !== "Running") continue;
      run.status = "Interrupted";
      run.ended_at = d.now();
      run.error =
        "Supervisor restarted; completion was not confirmed. Retry creates a new attempt.";
      d.saveRun(run);
    }
    pending = persisted.filter(run => run.status === "Queued").reverse();
    observedRevision = d.dataRevision?.();
  }

  function stop() {
    stopping = true;
    for (const [id, child] of active) {
      const run = d.get<Run>("run", id);
      run.status = "Interrupted";
      run.ended_at = d.now();
      run.error = "Supervisor stopped";
      d.saveRun(run);
      stopProcess(child);
    }
  }

  return {
    enqueue,
    pump,
    cancel,
    recoverInterrupted,
    stop,
    isActive: (id: string) => active.has(id),
  };
}
