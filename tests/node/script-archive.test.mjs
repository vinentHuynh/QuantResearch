import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { createScriptArchive } from "../../server/features/scripts/scriptArchive.ts";

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), "script-archive-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(join(root, "strategies"));
  const source = "# test adapter\nSTRATEGY = {'id': 'test-alpha'}\n";
  const file = join(root, "strategies", "alpha.py");
  writeFileSync(file, source);
  const strategy = {
    id: "test-alpha",
    name: "Test alpha",
    file: "strategies/alpha.py",
    file_hash: createHash("sha256").update(source).digest("hex"),
    source_files: ["strategies/alpha.py"],
    parameters: {},
    timeframes: ["1h"],
  };
  return { root, file, source, strategy };
}

test("archive moves a script out of discovery, persists metadata, and restore returns it", (t) => {
  const { root, file, source, strategy } = fixture(t);
  const service = createScriptArchive(root, { now: () => "2026-09-30T12:00:00.000Z" });
  const entry = service.archive(strategy, [strategy]);
  assert.equal(existsSync(file), false);
  assert.equal(entry.original_path, "strategies/alpha.py");
  assert.equal(entry.archive_path, "strategies_archive/test-alpha/alpha.py");
  assert.equal(entry.archived_at, "2026-09-30T12:00:00.000Z");
  assert.equal(readFileSync(join(root, entry.archive_path), "utf8"), source);
  assert.equal(readFileSync(join(root, "strategies_archive/manifest.json"), "utf8").includes("test-alpha"), true);
  const reopened = createScriptArchive(root);
  assert.deepEqual([...reopened.archivedIds()], ["test-alpha"]);
  assert.deepEqual(reopened.list(), [entry]);
  assert.throws(() => reopened.archive(strategy, [strategy]), /already archived/);
  assert.deepEqual(reopened.restore("test-alpha"), entry);
  assert.equal(readFileSync(file, "utf8"), source);
  assert.equal(existsSync(join(root, entry.archive_path)), false);
  assert.deepEqual(reopened.list(), []);
});

test("archive refuses to break another active strategy source dependency", (t) => {
  const { root, file, strategy } = fixture(t);
  const dependent = {
    ...strategy,
    id: "test-dependent",
    name: "Dependent adapter",
    file: "strategies/dependent.py",
    source_files: ["strategies/dependent.py", strategy.file],
  };
  const service = createScriptArchive(root);
  assert.throws(() => service.archive(strategy, [strategy, dependent]), /required by active scripts: Dependent adapter/);
  assert.equal(existsSync(file), true);
  assert.deepEqual(service.list(), []);
});

test("restore keeps a dependent archived until its source dependency is restored", (t) => {
  const { root, file, strategy } = fixture(t);
  const dependentSource = "# dependent adapter\n";
  const dependentFile = join(root, "strategies", "dependent.py");
  writeFileSync(dependentFile, dependentSource);
  const dependent = {
    ...strategy,
    id: "test-dependent",
    name: "Dependent adapter",
    file: "strategies/dependent.py",
    file_hash: createHash("sha256").update(dependentSource).digest("hex"),
    source_files: ["strategies/dependent.py", strategy.file],
  };
  const service = createScriptArchive(root);
  service.archive(dependent, [strategy, dependent]);
  service.archive(strategy, [strategy]);
  assert.throws(() => service.restore(dependent.id), /Source dependency strategies\/alpha.py is missing/);
  assert.equal(existsSync(dependentFile), false);
  assert.deepEqual([...service.archivedIds()].sort(), [strategy.id, dependent.id].sort());
  service.restore(strategy.id);
  service.restore(dependent.id);
  assert.equal(existsSync(file), true);
  assert.equal(existsSync(dependentFile), true);
});

test("archive and restore reject changed bytes and occupied destinations", (t) => {
  const { root, file, strategy } = fixture(t);
  const service = createScriptArchive(root);
  writeFileSync(file, "changed after scan");
  assert.throws(() => service.archive(strategy, [strategy]), /changed since discovery/);
  writeFileSync(file, "# test adapter\nSTRATEGY = {'id': 'test-alpha'}\n");
  const destination = join(root, "strategies_archive/test-alpha/alpha.py");
  mkdirSync(join(root, "strategies_archive/test-alpha"), { recursive: true });
  writeFileSync(destination, "occupied");
  assert.throws(() => service.archive(strategy, [strategy]), /destination already exists/);
  assert.equal(existsSync(file), true);
  rmSync(destination);
  service.archive(strategy, [strategy]);
  writeFileSync(destination, "edited archive");
  assert.throws(() => service.restore("test-alpha"), /source changed/);
  writeFileSync(destination, "# test adapter\nSTRATEGY = {'id': 'test-alpha'}\n");
  writeFileSync(file, "new active script");
  assert.throws(() => service.restore("test-alpha"), /destination already exists/);
  assert.equal(readFileSync(file, "utf8"), "new active script");
});

test("archive rejects traversal in discovered metadata and saved manifest", (t) => {
  const { root, strategy } = fixture(t);
  const service = createScriptArchive(root);
  assert.throws(() => service.archive({ ...strategy, file: "strategies/../outside.py" }, [strategy]), /active catalog|top-level/);
  const manifest = {
    schema_version: 1,
    scripts: [{
      id: strategy.id,
      name: strategy.name,
      archived_at: "2026-09-30T12:00:00.000Z",
      original_path: strategy.file,
      archive_path: "strategies_archive/../../outside.py",
      file_hash: strategy.file_hash,
      strategy,
    }],
  };
  mkdirSync(join(root, "strategies_archive"));
  writeFileSync(join(root, "strategies_archive/manifest.json"), JSON.stringify(manifest));
  assert.throws(() => service.list(), /Invalid archived script manifest entry/);
});

test("failed manifest persistence rolls back the source move", (t) => {
  const { root, file, source, strategy } = fixture(t);
  const service = createScriptArchive(root, {
    manifestWriter: () => { throw new Error("simulated write failure"); },
  });
  assert.throws(() => service.archive(strategy, [strategy]), /simulated write failure/);
  assert.equal(readFileSync(file, "utf8"), source);
  assert.equal(existsSync(join(root, "strategies_archive/test-alpha/alpha.py")), false);
  assert.deepEqual(createScriptArchive(root).list(), []);
});

test("failed manifest persistence rolls back a restore", (t) => {
  const { root, file, source, strategy } = fixture(t);
  const entry = createScriptArchive(root).archive(strategy, [strategy]);
  const failing = createScriptArchive(root, {
    manifestWriter: () => { throw new Error("simulated restore write failure"); },
  });
  assert.throws(() => failing.restore(strategy.id), /simulated restore write failure/);
  assert.equal(existsSync(file), false);
  assert.equal(readFileSync(join(root, entry.archive_path), "utf8"), source);
  assert.deepEqual(createScriptArchive(root).list(), [entry]);
});

test("interrupted move is recovered from the manifest", (t) => {
  const { root, file, strategy } = fixture(t);
  const service = createScriptArchive(root);
  const entry = service.archive(strategy, [strategy]);
  renameSync(join(root, entry.archive_path), file);
  assert.deepEqual(createScriptArchive(root).list(), [entry]);
  assert.equal(existsSync(file), false);
  assert.equal(existsSync(join(root, entry.archive_path)), true);
});

test("failed rediscovery validation leaves the source in Archive", (t) => {
  const { root, file, strategy } = fixture(t);
  const service = createScriptArchive(root);
  const entry = service.archive(strategy, [strategy]);
  assert.throws(() => service.restore(strategy.id, () => { throw new Error("not discoverable"); }), /not discoverable/);
  assert.equal(existsSync(file), false);
  assert.equal(existsSync(join(root, entry.archive_path)), true);
  assert.deepEqual(service.list(), [entry]);
});
