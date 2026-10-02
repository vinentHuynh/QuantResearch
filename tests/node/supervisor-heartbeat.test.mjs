import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import test from "node:test";

import { startSupervisorHeartbeat } from "../../server/core/supervisorHeartbeat.ts";
import { createSourceSnapshots } from "../../server/infra/sourceSnapshots.ts";

test("supervisor lease remains fresh while the main thread is blocked", async () => {
  const folder = mkdtempSync(join(tmpdir(), "workbench-heartbeat-"));
  const file = join(folder, "supervisor.json");
  const token = "fixed-test-token";
  const failures = [];
  let heartbeat;
  try {
    heartbeat = await startSupervisorHeartbeat(file, token, process.pid, error => failures.push(error));
    const blockedAt = Date.now();
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 16_500);

    const modifiedAt = statSync(file).mtimeMs;
    assert.ok(modifiedAt > blockedAt + 10_000, "worker must write during the blocked interval");
    assert.ok(Date.now() - modifiedAt < 5_000, "lease must stay well inside the 15-second expiry");
    assert.deepEqual(JSON.parse(readFileSync(file, "utf8")), { token, pid: process.pid });
    assert.deepEqual(failures, []);
  } finally {
    await heartbeat?.stop();
    const target = resolve(folder);
    assert.equal(dirname(target), resolve(tmpdir()));
    assert.match(basename(target), /^workbench-heartbeat-[\w-]+$/);
    rmSync(target, { recursive: true, force: true });
  }
});

test("heartbeat worker code changes the application build fingerprint", () => {
  const folder = mkdtempSync(join(tmpdir(), "workbench-heartbeat-hash-"));
  const server = join(folder, "server");
  const worker = join(server, "supervisorHeartbeat.worker.mjs");
  try {
    mkdirSync(server);
    writeFileSync(worker, "const heartbeat = 1;\n");
    const snapshots = createSourceSnapshots({
      root: folder,
      state: folder,
      python: "unused",
      cleanEnvironment: () => ({}),
      sourceRoots: [server],
    });
    const before = snapshots.applicationBuildHash();
    writeFileSync(worker, "const heartbeat = 2;\n");
    assert.notEqual(snapshots.applicationBuildHash(), before);
  } finally {
    const target = resolve(folder);
    assert.equal(dirname(target), resolve(tmpdir()));
    assert.match(basename(target), /^workbench-heartbeat-hash-[\w-]+$/);
    rmSync(target, { recursive: true, force: true });
  }
});
