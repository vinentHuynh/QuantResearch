import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  createSourceSnapshots,
  executionSourceFingerprint,
} from "../../server/infra/sourceSnapshots.ts";

const runtimeFiles = [
  "workbench/__init__.py",
  "workbench/worker.py",
  "workbench/contract.py",
  "workbench/dataset_reference.py",
  "workbench/layout.py",
  "workbench/metrics.py",
  "workbench/research.py",
  "workbench/supervision.py",
  "workbench/warmup.py",
  "workbench/events.py",
  "strategy_engine/__init__.py",
  "strategy_engine/catalog.py",
  "strategy_engine/data.py",
  "strategy_engine/sessions.py",
];

const sha256 = (value) =>
  createHash("sha256").update(value).digest("hex");

async function put(root, relative, value) {
  const path = join(root, ...relative.split("/"));
  await mkdir(join(path, ".."), { recursive: true });
  await writeFile(path, value);
}

test("execution identity ignores unrelated UI and research edits", async () => {
  const root = await mkdtemp(join(tmpdir(), "workbench-source-hash-"));
  try {
    await Promise.all(
      runtimeFiles.map((path) => put(root, path, `# ${path}\n`)),
    );
    const adapter = "STRATEGY = {'id': 'fixture'}\n";
    await put(root, "strategies/fixture.py", adapter);
    await put(root, "research/declared.py", "VALUE = 1\n");
    await put(root, "research/unrelated.py", "VALUE = 'first'\n");
    await put(root, "strategy_engine/parity.py", "VALUE = 'first'\n");
    await put(root, "src/App.tsx", "export const App = () => null;\n");

    const strategy = {
      file: "strategies/fixture.py",
      file_hash: sha256(adapter),
      source_files: ["strategies/fixture.py", "research/declared.py"],
    };
    const initialExecution = executionSourceFingerprint(root, strategy);
    const snapshots = createSourceSnapshots({
      root,
      state: join(root, "state"),
      python: "unused",
      cleanEnvironment: () => ({}),
    });
    const initialApp = snapshots.applicationBuildHash();

    await put(root, "src/App.tsx", "export const App = () => <main />;\n");
    await put(root, "research/unrelated.py", "VALUE = 'changed'\n");
    await put(root, "workbench/research.py", "VALUE = 'changed'\n");
    await put(root, "strategy_engine/parity.py", "VALUE = 'changed'\n");
    assert.equal(executionSourceFingerprint(root, strategy), initialExecution);
    assert.notEqual(snapshots.applicationBuildHash(), initialApp);

    await put(root, "research/declared.py", "VALUE = 2\n");
    assert.notEqual(executionSourceFingerprint(root, strategy), initialExecution);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
