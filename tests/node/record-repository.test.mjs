import assert from "node:assert/strict";
import { test } from "node:test";
import { DatabaseSync } from "node:sqlite";

import {
  createRecordRepository,
  isRecordEnvelope,
} from "../../server/infra/recordRepository.ts";

test("new records use a v2 envelope while reads preserve the public shape", () => {
  const db = new DatabaseSync(":memory:");
  const records = createRecordRepository(db);
  records.put("run", "new", { id: "new", status: "Queued" });
  const raw = JSON.parse(records.raw("run", "new"));
  assert.equal(isRecordEnvelope(raw, "run", "new"), true);
  assert.deepEqual(records.get("run", "new"), {
    id: "new",
    status: "Queued",
  });
});

test("an existing v1 row remains unwrapped when it is updated", () => {
  const db = new DatabaseSync(":memory:");
  const records = createRecordRepository(db);
  db.prepare("INSERT INTO records VALUES(?,?,?)").run(
    "run",
    "old",
    JSON.stringify({ id: "old", status: "Running", source_dir: "C:/old" }),
  );
  records.put("run", "old", {
    id: "old",
    status: "Interrupted",
    source_dir: "C:/old",
  });
  const raw = JSON.parse(records.raw("run", "old"));
  assert.equal(isRecordEnvelope(raw), false);
  assert.equal(raw.status, "Interrupted");
  assert.equal(raw.source_dir, "C:/old");
});

test("a legacy row may be updated to a protocol-v2 domain body", () => {
  const db = new DatabaseSync(":memory:");
  const records = createRecordRepository(db);
  db.prepare("INSERT INTO records VALUES(?,?,?)").run(
    "dataset",
    "bars",
    JSON.stringify({ id: "bars", path: "C:/legacy/bars.parquet" }),
  );
  const body = {
    schema_version: 2,
    id: "bars",
    path: "datasets/bars.parquet",
  };
  records.put("dataset", "bars", body);
  assert.deepEqual(records.get("dataset", "bars"), body);
  assert.deepEqual(records.all("dataset"), [body]);
  assert.deepEqual(JSON.parse(records.raw("dataset", "bars")), body);
  db.close();
});

test("mixed protocol rows are returned in insertion order", () => {
  const db = new DatabaseSync(":memory:");
  const records = createRecordRepository(db);
  db.prepare("INSERT INTO records VALUES(?,?,?)").run(
    "view",
    "old",
    JSON.stringify({ id: "old", name: "Legacy" }),
  );
  records.put("view", "new", { id: "new", name: "Current" });
  assert.deepEqual(records.all("view"), [
    { id: "new", name: "Current" },
    { id: "old", name: "Legacy" },
  ]);
});

test("malformed protocol-v2 envelopes are rejected instead of read as v1", () => {
  const cases = [
    ["wrong-kind", { schema_version: 2, kind: "view", id: "bad", body: {} }],
    ["wrong-id", { schema_version: 2, kind: "run", id: "other", body: {} }],
    ["nonobject-body", { schema_version: 2, kind: "run", id: "bad", body: [] }],
    [
      "extra-field",
      { schema_version: 2, kind: "run", id: "bad", body: {}, extra: true },
    ],
  ];
  for (const [label, value] of cases) {
    const db = new DatabaseSync(":memory:");
    const records = createRecordRepository(db);
    db.prepare("INSERT INTO records VALUES(?,?,?)").run(
      "run",
      "bad",
      JSON.stringify(value),
    );
    assert.throws(
      () => records.get("run", "bad"),
      /Invalid protocol-v2 SQLite envelope/,
      label,
    );
    assert.throws(
      () => records.put("run", "bad", { id: "bad" }),
      /Invalid protocol-v2 SQLite envelope/,
      `${label} update`,
    );
    db.close();
  }
});

test("non-object protocol-v1 rows are rejected", () => {
  const db = new DatabaseSync(":memory:");
  const records = createRecordRepository(db);
  db.prepare("INSERT INTO records VALUES(?,?,?)").run("run", "bad", "[]");
  assert.throws(
    () => records.get("run", "bad"),
    /Invalid protocol-v1 SQLite record/,
  );
  db.close();
});
