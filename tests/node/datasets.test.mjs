import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { test } from "node:test";
import { DatabaseSync } from "node:sqlite";

import { createDatasets } from "../../server/features/datasets/datasets.ts";
import { createRecordRepository } from "../../server/infra/recordRepository.ts";

test("dataset service preserves v1 rows and normalizes new protocol references", async () => {
  const home = await mkdtemp(join(tmpdir(), "workbench-datasets-"));
  const datasetsRoot = join(home, "datasets");
  await mkdir(datasetsRoot, { recursive: true });
  const db = new DatabaseSync(join(home, "workbench.sqlite3"));
  try {
    const records = createRecordRepository(db);
    const legacy = {
      id: "existing-v1",
      symbol: "NQ",
      first: "2025-01-01T00:00:00Z",
      last: "2025-12-31T23:59:00Z",
      path: join(datasetsRoot, "existing.parquet"),
      archive: "raw\\existing.zip",
      checksum: "a".repeat(64),
      registered_at: "2026-01-01T00:00:00Z",
      currency: "USD",
    };
    const legacyBytes = JSON.stringify(legacy);
    db.prepare("INSERT INTO records(kind,id,body) VALUES(?,?,?)").run(
      "dataset",
      legacy.id,
      legacyBytes,
    );

    const replacement = {
      ...legacy,
      schema_version: 2,
      path: "datasets/existing.parquet",
    };
    const registered = {
      ...replacement,
      id: "new-v2",
      path: "datasets/new.parquet",
      archive: "raw/new.zip",
    };
    await writeFile(
      join(datasetsRoot, "catalog.json"),
      JSON.stringify({ datasets: [replacement, registered], errors: [] }),
    );

    const service = createDatasets({
      root: resolve("."),
      state: home,
      python: "unused-python",
      cleanEnvironment: () => ({}),
      put: records.put,
      raw: records.raw,
    });

    assert.equal(records.raw("dataset", legacy.id), legacyBytes);
    assert.deepEqual(records.get("dataset", legacy.id), legacy);
    assert.deepEqual(records.get("dataset", registered.id), registered);
    assert.deepEqual(service.job(), { status: "Idle", log: "" });

    const protocol = service.protocol(legacy);
    assert.equal(protocol.schema_version, 2);
    assert.equal(protocol.path, "datasets/existing.parquet");
    assert.equal(protocol.archive, "raw/existing.zip");
    assert.equal(isAbsolute(protocol.path), false);

    const v1 = service.legacy(registered);
    assert.equal(v1.schema_version, undefined);
    assert.equal(v1.path, join(datasetsRoot, "new.parquet"));
    assert.equal(isAbsolute(v1.path), true);

    assert.throws(
      () => service.file({ ...registered, path: "datasets//new.parquet" }),
      /canonical logical reference/,
    );
    assert.throws(
      () => service.file({ ...legacy, path: join(home, "..", "outside") }),
      /outside WORKBENCH_HOME/,
    );
  } finally {
    db.close();
    await rm(home, { recursive: true, force: true });
  }
});
