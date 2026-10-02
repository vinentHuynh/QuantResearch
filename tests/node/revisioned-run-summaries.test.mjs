import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createRevisionedRunSummaries } from "../../server/infra/revisionedRunSummaries.ts";

test("projected runs are reused until local or external SQLite writes change them", () => {
  const folder = mkdtempSync(join(tmpdir(), "revisioned-runs-"));
  const path = join(folder, "records.sqlite3");
  const db = new DatabaseSync(path);
  const external = new DatabaseSync(path);
  try {
    db.exec("CREATE TABLE records(kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id))");
    const insert = (connection, id, net) => connection.prepare("INSERT INTO records VALUES(?,?,?)").run(
      "run", id, JSON.stringify({ id, input: {}, status: "Succeeded", result: {
        metrics: { net_pnl: net }, equity_preview: [{ equity: net }],
      } }),
    );
    insert(db, "first", 10);
    const cache = createRevisionedRunSummaries(db);
    const first = cache.read();
    assert.equal(cache.read(), first);
    assert.equal(first[0].result.equity_preview, undefined);

    insert(db, "second", 20);
    const second = cache.read();
    assert.notEqual(second, first);
    assert.deepEqual(second.map(run => run.id), ["second", "first"]);
    assert.equal(cache.read(), second);

    insert(external, "third", 30);
    const third = cache.read();
    assert.notEqual(third, second);
    assert.deepEqual(third.map(run => run.id), ["third", "second", "first"]);

    db.prepare("DELETE FROM records WHERE kind='run' AND id='first'").run();
    assert.deepEqual(cache.read().map(run => run.id), ["third", "second"]);
  } finally {
    external.close();
    db.close();
    rmSync(folder, { recursive: true, force: true });
  }
});
