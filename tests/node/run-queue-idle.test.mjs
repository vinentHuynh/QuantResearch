import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import test from "node:test";

import { createRunQueue } from "../../server/core/runQueue.ts";

test("idle queue polls do not hydrate saved runs", () => {
  const folder = mkdtempSync(join(tmpdir(), "workbench-run-queue-"));
  const records = new Map();
  let reads = 0;
  let revision = 0;
  try {
    const queue = createRunQueue({
      all: () => { reads += 1; return [...records.values()].reverse(); },
      get: (_kind, id) => records.get(id),
      saveRun: run => { records.set(run.id, run); revision += 1; },
      runDir: id => join(folder, id),
      python: "unused",
      concurrency: 1,
      cleanEnvironment: () => ({}),
      sourceFolder: () => folder,
      supervisorFile: "unused",
      supervisorToken: "unused",
      hash: () => "unused",
      now: () => "2026-09-30T00:00:00.000Z",
      dataRevision: () => String(revision),
    });
    queue.recoverInterrupted();
    for (let index = 0; index < 20; index += 1) queue.pump();
    assert.equal(reads, 1);

    const pending = queue.enqueue({ timeout: 300, strategy: {}, dataset: {} });
    queue.cancel(pending.id);
    for (let index = 0; index < 20; index += 1) queue.pump();
    assert.equal(reads, 2, "a local write refreshes persisted queue state once");
    assert.equal(records.get(pending.id).status, "Canceled");

    revision += 1; // An external SQLite commit changes the same revision source.
    queue.pump();
    assert.equal(reads, 3, "an external SQLite commit reloads persisted queue state");
  } finally {
    const target = resolve(folder);
    assert.equal(dirname(target), resolve(tmpdir()));
    assert.match(basename(target), /^workbench-run-queue-[\w-]+$/);
    rmSync(target, { recursive: true, force: true });
  }
});
