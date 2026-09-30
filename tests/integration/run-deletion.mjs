import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { randomUUID } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRunDeletion } from "../../server/runDeletion.ts";

const state = mkdtempSync(join(tmpdir(), "strategy-workbench-delete-"));
const db = new DatabaseSync(":memory:");
try {
db.exec(
  "CREATE TABLE records(kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id))",
);
const save = (kind, id, body) =>
  db
    .prepare("INSERT OR REPLACE INTO records VALUES(?,?,?)")
    .run(kind, id, JSON.stringify(body));
const put = (kind, body) => save(kind, body.id, body);
const all = (kind) =>
  db
    .prepare("SELECT body FROM records WHERE kind=? ORDER BY rowid")
    .all(kind)
    .map((r) => JSON.parse(r.body));
const a = randomUUID(),
  b = randomUUID(),
  c = randomUUID(),
  e = randomUUID(),
  w = randomUUID();
put("run", { id: a, status: "Succeeded", input: { experiment_id: e } });
put("run", {
  id: b,
  status: "Succeeded",
  watch_id: w,
  input: { experiment_id: e, retry_of: a },
});
put("run", { id: c, status: "Succeeded", input: { experiment_id: e } });
put("watch", { id: w, run_id: a });
put("experiment", { id: e, attempted_variants: 3, run_ids: [a, b, c] });
put("dataset", { id: "preserved-data" });
put("preset", { id: "preserved-preset" });
for (const id of [a, b, c]) {
  mkdirSync(join(state, "runs", id), { recursive: true });
  writeFileSync(join(state, "runs", id, "equity.csv"), "test artifact");
}
let active = false;
const deletion = createRunDeletion({
  db,
  state,
  all,
  put: save,
  raw: (kind, id) =>
    db.prepare("SELECT body FROM records WHERE kind=? AND id=?").get(kind, id)?.body,
  active: () => active,
});
const first = deletion.preview([a]);
assert.deepEqual(new Set(first.affected_ids), new Set([a, b]));
assert.equal(first.counts.watchlist, 1);
active = true;
assert.throws(() => deletion.remove([a], first.token), /Cancel active/);
active = false;
put("run", { ...all("run")[0], notes: "changed since preview" });
assert.throws(() => deletion.remove([a], first.token), /scope changed/);
const preview = deletion.preview([a]),
  removed = deletion.remove(preview.ids, preview.token);
assert.deepEqual(removed.warnings, []);
assert.deepEqual(
  all("run").map((r) => r.id),
  [c],
);
assert.equal(all("watch").length, 0);
assert.equal(all("experiment")[0].attempted_variants, 3);
assert.equal(all("experiment")[0].deleted_variants, 2);
assert.deepEqual(all("experiment")[0].run_ids, [c]);
assert(existsSync(join(removed.backup, "records.json")));
assert(existsSync(join(removed.backup, "runs", a, "equity.csv")));
assert(!existsSync(join(state, "runs", a)));
assert(existsSync(join(state, "runs", c)));
assert.equal(all("dataset").length, 1);
assert.equal(all("preset").length, 1);
const restored = deletion.restore(removed.id);
assert(restored.restored);
assert.deepEqual(new Set(all("run").map((run) => run.id)), new Set([a, b, c]));
assert.equal(all("watch").length, 1);
assert.deepEqual(all("experiment")[0].run_ids, [a, b, c]);
assert.equal(all("experiment")[0].deleted_variants, undefined);
assert(existsSync(join(state, "runs", a, "equity.csv")));
assert(!existsSync(join(removed.backup, "runs", a)));
assert(all("deletion")[0].restored_at);
assert.throws(() => deletion.restore(removed.id), /existing record/);
const group = randomUUID(),
  d = randomUUID(),
  regime = randomUUID();
put("evaluation", { id: group, status: "Running" });
put("run", {
  id: d,
  status: "Succeeded",
  input: { experiment_id: group, research: { evaluation_id: group } },
});
assert.throws(() => deletion.preview([d]), /Cancel active/);
put("evaluation", { id: group, status: "Succeeded" });
put("regime", { id: regime, evaluation_id: group, status: "Succeeded" });
const cascade = deletion.preview([d]);
assert.equal(cascade.counts.evaluations, 1);
assert.equal(cascade.counts.regimes, 1);
deletion.remove([d], cascade.token);
assert.equal(all("evaluation").length, 0);
assert.equal(all("regime").length, 0);
assert.throws(() => deletion.preview(["../outside"]), /no longer exists/);
console.log(
  "Deletion checks passed: dependency closure, active guard, stale preview, byte-exact recovery, preserved experiment history, local backup, and dataset/preset preservation.",
);
} finally {
  db.close();
  rmSync(state, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
