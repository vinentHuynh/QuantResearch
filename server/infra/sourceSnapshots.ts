import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

export type StrategySource = {
  file: string;
  file_hash: string;
  source_files?: string[];
};

type SnapshotDependencies = {
  root: string;
  state: string;
  python: string;
  cleanEnvironment: () => NodeJS.ProcessEnv;
  sourceRoots?: readonly string[];
};

export type SourceSnapshot = {
  folder: string;
  sourceSnapshot: string;
  executionSourceHash: string;
  snapshotHash: string;
  appBuildHash: string;
  // Transitional aliases used by the existing evaluation coordinator.
  digest: string;
};

type SourceFile = {
  absolute: string;
  path: string;
  bytes: Buffer;
  sha256: string;
  role: "adapter" | "execution_dependency" | "research";
};

const sha256 = (value: string | Buffer) =>
  createHash("sha256").update(value).digest("hex");

const normalizedRelative = (root: string, value: string) => {
  if (
    !value ||
    value.includes("\\") ||
    value.startsWith("/") ||
    /^[A-Za-z]:/.test(value)
  )
    throw new Error(`Invalid source_files path: ${value}`);
  const absolute = resolve(root, value);
  const fromRoot = relative(root, absolute);
  if (
    fromRoot === ".." ||
    fromRoot.startsWith(`..${sep}`) ||
    isAbsolute(fromRoot)
  )
    throw new Error(`Source dependency escapes the workspace: ${value}`);
  if (!existsSync(absolute) || !statSync(absolute).isFile())
    throw new Error(`Source dependency is unavailable: ${value}`);
  return { absolute, path: fromRoot.split(sep).join("/") };
};

function walkFiles(folder: string, accept: (path: string) => boolean) {
  const output: string[] = [];
  if (!existsSync(folder)) return output;
  for (const item of readdirSync(folder, { withFileTypes: true })) {
    if (["__pycache__", "node_modules", "dist"].includes(item.name)) continue;
    const path = join(folder, item.name);
    if (item.isDirectory()) output.push(...walkFiles(path, accept));
    else if (item.isFile() && accept(path)) output.push(path);
  }
  return output;
}

function canonicalHash(value: unknown) {
  return sha256(JSON.stringify(value));
}

function collectExecutionSources(root: string, strategy: StrategySource) {
  const executionRuntime = [
    "workbench/__init__.py",
    "workbench/worker.py",
    "workbench/contract.py",
    "workbench/dataset_reference.py",
    "workbench/layout.py",
    "workbench/metrics.py",
    "workbench/warmup.py",
    "workbench/events.py",
    // worker.py imports strategy_engine.data/sessions. Importing a package
    // submodule also executes __init__.py, which imports catalog.py.
    "strategy_engine/__init__.py",
    "strategy_engine/catalog.py",
    "strategy_engine/data.py",
    "strategy_engine/sessions.py",
  ];
  // Evaluation orchestration must be replayable from the same snapshot, but
  // it is not part of strategy execution identity. Its bytes are protected by
  // snapshot_hash while edits leave execution_source_hash unchanged.
  const researchRuntime = [
    "workbench/research.py",
    "workbench/supervision.py",
  ];
  const adapter = strategy.file.split("\\").join("/");
  const declared = strategy.source_files?.length
    ? strategy.source_files
    : [adapter];
  if (!declared.includes(adapter))
    throw new Error("source_files must include the runnable strategy adapter");

  const roles = new Map<string, SourceFile["role"]>();
  roles.set(adapter, "adapter");
  for (const path of [...executionRuntime, ...declared])
    if (!roles.has(path)) roles.set(path, "execution_dependency");
  for (const path of researchRuntime)
    if (!roles.has(path)) roles.set(path, "research");
  const contents: SourceFile[] = [...roles]
    .map(([path, role]) => {
      const located = normalizedRelative(root, path);
      const bytes = readFileSync(located.absolute);
      return {
        ...located,
        bytes,
        sha256: sha256(bytes),
        role,
      };
    })
    .sort((a, b) => a.path.localeCompare(b.path));

  const adapterFile = contents.find((file) => file.path === adapter)!;
  if (adapterFile.sha256 !== strategy.file_hash)
    throw new Error(
      "Strategy changed since discovery. Refresh the scripts and preview again.",
    );
  return contents;
}

export function executionSourceFingerprint(
  root: string,
  strategy: StrategySource,
) {
  const contents = collectExecutionSources(root, strategy);
  return canonicalHash(
    contents
      .filter((file) => file.role !== "research")
      .map((file) => [file.path, file.sha256]),
  );
}

export function createSourceSnapshots(d: SnapshotDependencies) {

  function applicationBuildHash() {
    const files = [
      ...(d.sourceRoots ?? ["server", "src", "shared"].map((path) => join(d.root, path))).flatMap((folder) =>
        walkFiles(folder, (path) => /\.(?:ts|tsx|json|css)$/.test(path)),
      ),
      ...["package.json", "package-lock.json", "config/workbench-layout.json"]
        .map((path) => join(d.root, path))
        .filter((path) => existsSync(path)),
    ];
    return canonicalHash(
      [...new Set(files)]
        .sort()
        .map((file) => [relative(d.root, file).split(sep).join("/"), sha256(readFileSync(file))]),
    );
  }

  function create(strategy: StrategySource): SourceSnapshot {
    const contents = collectExecutionSources(d.root, strategy);

    const executionSourceHash = canonicalHash(
      contents
        .filter((file) => file.role !== "research")
        .map((file) => [file.path, file.sha256]),
    );
    const dependencies = JSON.parse(
      execFileSync(
        d.python,
        ["-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
        {
          encoding: "utf8",
          windowsHide: true,
          env: d.cleanEnvironment(),
        },
      ),
    );
    const environment = {
      python: execFileSync(d.python, ["--version"], {
        encoding: "utf8",
        windowsHide: true,
        env: d.cleanEnvironment(),
      }).trim(),
      node: process.version,
      platform: process.platform,
      dependencies,
    };
    const appBuildHash = applicationBuildHash();
    const snapshotHash = canonicalHash({
      execution_source_hash: executionSourceHash,
      app_build_hash: appBuildHash,
      files: contents.map((file) => [file.path, file.sha256, file.bytes.length]),
      environment,
    });
    const sourceSnapshot = `sources/${snapshotHash}`;
    const folder = join(d.state, "sources", snapshotHash);
    const manifestPath = join(folder, "snapshot.json");
    if (!existsSync(manifestPath)) {
      for (const file of contents) {
        const target = join(folder, ...file.path.split("/"));
        mkdirSync(dirname(target), { recursive: true });
        writeFileSync(target, file.bytes);
      }
      mkdirSync(folder, { recursive: true });
      writeFileSync(
        join(folder, "environment.json"),
        JSON.stringify(environment, null, 2),
      );
      writeFileSync(
        join(folder, "sources.json"),
        JSON.stringify(
          Object.fromEntries(contents.map((file) => [file.path, file.sha256])),
          null,
          2,
        ),
      );
      writeFileSync(
        manifestPath,
        JSON.stringify(
          {
            schema_version: 2,
            created_at: new Date().toISOString(),
            execution_source_hash: executionSourceHash,
            snapshot_hash: snapshotHash,
            app_build_hash: appBuildHash,
            files: contents.map((file) => ({
              path: file.path,
              sha256: file.sha256,
              bytes: file.bytes.length,
              role: file.role,
            })),
            environment,
          },
          null,
          2,
        ),
      );
    }
    return {
      folder,
      sourceSnapshot,
      executionSourceHash,
      snapshotHash,
      appBuildHash,
      digest: executionSourceHash,
    };
  }

  function resolveSnapshot(reference: string) {
    if (isAbsolute(reference)) return resolve(reference);
    const folder = resolve(d.state, reference);
    const stateRoot = resolve(d.state);
    if (!folder.startsWith(`${stateRoot}${sep}`))
      throw new Error("Source snapshot reference escapes WORKBENCH_HOME");
    return folder;
  }

  return { create, resolve: resolveSnapshot, applicationBuildHash };
}
