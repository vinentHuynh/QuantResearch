import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { test } from "node:test";
import { DatabaseSync } from "node:sqlite";
import { Ajv2020 } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

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
      rows: 100,
      timeframe: "1m",
      timezone: "UTC",
      tick_size: 0.25,
      point_value: 20,
      warnings: ["Provider reported a degraded date; audit retained."],
      provenance: { kind: "local_composite_databento_archive" },
      provider_quality_flags: [{ date: "2025-11-02", condition: "degraded" }],
      quality_evidence: {
        minute_audit: "reports/update/quality-verification.json",
      },
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
    assert.equal(Object.hasOwn(protocol, "provider_quality_flags"), false);
    assert.equal(Object.hasOwn(protocol, "quality_evidence"), false);
    assert.deepEqual(protocol.provenance, {
      ...legacy.provenance,
      provider_quality_flags: legacy.provider_quality_flags,
      quality_evidence: legacy.quality_evidence,
    });
    assert.deepEqual(service.protocol(protocol), protocol);
    assert.equal(records.raw("dataset", legacy.id), legacyBytes);
    assert.equal(JSON.stringify(legacy), legacyBytes);

    const ajv = new Ajv2020({ allErrors: true, strict: false });
    addFormats(ajv);
    const validate = ajv.compile(
      JSON.parse(
        await readFile(
          new URL(
            "../../shared/contracts/dataset-manifest.v2.schema.json",
            import.meta.url,
          ),
          "utf8",
        ),
      ),
    );
    assert.equal(validate(protocol), true, JSON.stringify(validate.errors));
    assert.equal(validate({ ...protocol, provider_quality_flags: [] }), false);
    assert.ok(
      validate.errors.some((error) => error.keyword === "additionalProperties"),
    );

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
