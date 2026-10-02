import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { test } from "node:test";
import { createResearchArchive } from "../../server/features/runs/researchArchive.ts";
import { createRecordRepository } from "../../server/infra/recordRepository.ts";
import { createRevisionedRunSummaries } from "../../server/infra/revisionedRunSummaries.ts";
import { runConfigurationKey } from "../../shared/ts/evidence.ts";
import {
  archivedConfigurationForRun,
  isConfigurationArchived,
  isRunArchived,
} from "../../shared/ts/researchArchive.ts";

function run(id, input = {}, extra = {}) {
  return {
    id,
    status: "Succeeded",
    created_at: "2026-10-01T12:00:00.000Z",
    input: {
      protocol: 2,
      strategy: { id: "alpha", file_hash: "adapter-a", execution_source_hash: "engine-a" },
      dataset: { id: "dataset-a", symbol: "NQ" },
      source_hash: "engine-a",
      execution_source_hash: "engine-a",
      timeframe: "15m",
      session: "full-trading-day",
      parameters: { lookback: 12, risk: 1 },
      start: "2026-01-01",
      end: "2026-06-30",
      capital: 100000,
      fee: 2,
      slippage: 1,
      ...input,
    },
    ...extra,
  };
}

function fixture(t, options = {}) {
  const db = new DatabaseSync(":memory:");
  t.after(() => db.close());
  const records = createRecordRepository(db);
  const projected = createRevisionedRunSummaries(db);
  const dependencies = {
    db,
    records,
    runs: () => records.all("run"),
    active: () => false,
    now: () => "2026-10-01T13:00:00.000Z",
    ...options,
  };
  return { db, records, projected, dependencies, archive: createResearchArchive(dependencies) };
}

test("individual archiving persists separately, preserves all evidence bytes, and changes state revision", t => {
  const { records, projected, dependencies, archive } = fixture(t);
  const original = run("one", {}, { notes: "failed checks retained", result: { metrics: { trades: 7 }, equity_preview: [1, 2] } });
  records.put("run", original.id, original);
  records.put("evaluation", "eval", { id: "eval", status: "Failed", folds: [] });
  records.put("watch", "watch", { id: "watch", run_id: original.id });
  const before = [records.raw("run", "one"), records.raw("evaluation", "eval"), records.raw("watch", "watch")];
  const revision = projected.revision();
  const archived = archive.archiveRuns(["one", "one"]);
  assert.deepEqual(archived, { runs: [{ id: "one", archived_at: "2026-10-01T13:00:00.000Z" }], configurations: [] });
  assert.notEqual(projected.revision(), revision);
  assert.deepEqual([records.raw("run", "one"), records.raw("evaluation", "eval"), records.raw("watch", "watch")], before);
  assert.deepEqual(createResearchArchive(dependencies).read(), archived);
  const archivedRevision = projected.revision();
  assert.deepEqual(archive.archiveRuns(["one"]), archived);
  assert.equal(projected.revision(), archivedRevision, "idempotent archive must not rewrite metadata");
  assert.deepEqual(archive.unarchiveRuns(["one"]), { runs: [], configurations: [] });
  const restoredRevision = projected.revision();
  assert.deepEqual(archive.unarchiveRuns(["one"]), { runs: [], configurations: [] });
  assert.equal(projected.revision(), restoredRevision);
  assert.equal(records.raw("run", "one"), before[0]);
});

test("malformed and unknown run batches reject before persisting any archive", t => {
  const { records, archive } = fixture(t);
  records.put("run", "one", run("one"));
  for (const ids of [undefined, null, {}, "one", [], [null], [2], [""], [" "], ["one", "missing"]]) {
    assert.throws(() => archive.archiveRuns(ids), /valid run|no longer exists/);
    assert.throws(() => archive.unarchiveRuns(ids), /valid run|no longer exists/);
    assert.deepEqual(archive.read(), { runs: [], configurations: [] });
    assert.equal(records.raw("research_archive", "workspace"), undefined);
  }
});

test("active runs reject whole batches, including a live process with terminal saved status", t => {
  const { records, archive } = fixture(t, { active: id => id === "live" });
  records.put("run", "done", run("done"));
  for (const status of ["Queued", "Running", "Summarizing"]) {
    records.put("run", status, run(status, {}, { status }));
    assert.throws(() => archive.archiveRuns(["done", status]), /finish before archiving/);
    assert.deepEqual(archive.read().runs, []);
  }
  records.put("run", "live", run("live"));
  assert.throws(() => archive.archiveRuns(["done", "live"]), /finish before archiving/);
  assert.deepEqual(archive.read().runs, []);
});

test("configuration archives match exact strategy/source/parameters but span dates, costs and future attempts", t => {
  const { records, archive } = fixture(t);
  const seed = run("seed");
  const retry = run("retry", { start: "2025-01-01", fee: 7, parameters: { risk: 1, lookback: 12 }, dataset: { id: "new-dataset", symbol: "NQ" } });
  const other = [
    run("other-strategy", { strategy: { ...seed.input.strategy, id: "beta" } }),
    run("other-source", { execution_source_hash: "engine-b" }),
    run("other-parameter", { parameters: { lookback: 14, risk: 1 } }),
    run("other-market", { dataset: { id: "es", symbol: "ES" } }),
    run("other-timeframe", { timeframe: "1h" }),
    run("other-session", { session: "new-york-rth" }),
  ];
  for (const entry of [seed, retry, ...other]) records.put("run", entry.id, entry);
  const state = archive.archiveConfiguration(seed.id);
  assert.equal(state.runs.length, 0);
  assert.equal(state.configurations.length, 1);
  assert.equal(isConfigurationArchived("alpha", runConfigurationKey(seed), state), true);
  assert.equal(archivedConfigurationForRun(retry, state), state.configurations[0]);
  assert.equal(isRunArchived(run("future", { end: "2026-09-30" }), state), true);
  assert.equal(isRunArchived(seed, state), true);
  for (const entry of other) assert.equal(isRunArchived(entry, state), false, entry.id);
  assert.deepEqual(archive.archiveConfiguration(retry.id), state, "matching seeds must not duplicate configuration metadata");
  assert.deepEqual(records.get("run", seed.id), seed);
});

test("restoring a configuration retains independently archived runs and restoring a run retains its configuration archive", t => {
  const { records, archive } = fixture(t);
  const one = run("one"), two = run("two");
  records.put("run", one.id, one);
  records.put("run", two.id, two);
  archive.archiveRuns([one.id]);
  archive.archiveConfiguration(two.id);
  let state = archive.unarchiveRuns([one.id]);
  assert.equal(isRunArchived(one, state), true);
  assert.deepEqual(state.runs, []);
  archive.archiveRuns([one.id]);
  state = archive.unarchiveConfiguration(two.id);
  assert.equal(isRunArchived(one, state), true);
  assert.equal(isRunArchived(two, state), false);
  assert.deepEqual(state.configurations, []);
  assert.deepEqual(archive.unarchiveConfiguration(one.id), state);
});

test("configuration actions validate their seed and reject matching active work", t => {
  const { records, archive } = fixture(t);
  records.put("run", "seed", run("seed"));
  for (const id of [undefined, null, 7, {}, "", " ", "missing"]) {
    assert.throws(() => archive.archiveConfiguration(id), /valid run|no longer exists/);
    assert.throws(() => archive.unarchiveConfiguration(id), /valid run|no longer exists/);
  }
  records.put("run", "active", run("active", { capital: 200000 }, { status: "Summarizing" }));
  assert.throws(() => archive.archiveConfiguration("seed"), /active research/);
  assert.deepEqual(archive.read(), { runs: [], configurations: [] });
});

test("active evaluation candidates block a configuration between queued child jobs", t => {
  const { records, archive } = fixture(t);
  const seed = run("seed");
  records.put("run", seed.id, seed);
  const evaluation = { id: "eval", status: "Running", source_hash: "engine-a", execution_source_hash: "engine-a", candidates: [seed.input], folds: [] };
  records.put("evaluation", evaluation.id, evaluation);
  assert.throws(() => archive.archiveConfiguration(seed.id), /active research/);
  records.put("evaluation", evaluation.id, { ...evaluation, execution_source_hash: "engine-b" });
  assert.equal(archive.archiveConfiguration(seed.id).configurations.length, 1, "another frozen source is unrelated");
});

test("active parent evaluations and regimes linked through evidence also block configuration archive", t => {
  const { records, archive } = fixture(t);
  const seed = run("seed");
  records.put("run", seed.id, seed);
  const evaluation = { id: "eval", status: "Summarizing", candidates: [], folds: [{ training: [], tests: [seed.id] }] };
  records.put("evaluation", evaluation.id, evaluation);
  assert.throws(() => archive.archiveConfiguration(seed.id), /active research/);
  records.put("evaluation", evaluation.id, { ...evaluation, status: "Succeeded" });
  records.put("regime", "regime", { evaluation_id: evaluation.id, status: "Running" });
  assert.throws(() => archive.archiveConfiguration(seed.id), /active research/);
  records.put("regime", "regime", { evaluation_id: evaluation.id, status: "Succeeded" });
  archive.archiveConfiguration(seed.id);
  assert.equal(archive.read().configurations.length, 1);
});

test("archive writes roll back atomically if persistence fails", t => {
  const { records, dependencies } = fixture(t);
  records.put("run", "one", run("one"));
  const archive = createResearchArchive({
    ...dependencies,
    records: { ...records, put: (...args) => { records.put(...args); throw new Error("write failed"); } },
  });
  assert.throws(() => archive.archiveRuns(["one"]), /write failed/);
  assert.equal(records.raw("research_archive", "workspace"), undefined);
  assert.deepEqual(records.get("run", "one"), run("one"));
  assert.deepEqual(createResearchArchive(dependencies).archiveRuns(["one"]).runs.map(entry => entry.id), ["one"]);
});

test("legacy states without archive metadata remain visible", () => {
  const seed = run("one");
  assert.equal(isRunArchived(seed), false);
  assert.equal(archivedConfigurationForRun(seed), undefined);
  assert.equal(isConfigurationArchived("alpha", runConfigurationKey(seed)), false);
});
