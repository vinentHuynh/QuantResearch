import assert from "node:assert/strict";
import test from "node:test";
import { canArchiveRun, runHistoryGroups } from "../../src/features/runs/model.ts";
import { runConfigurationKey } from "../../shared/ts/evidence.ts";

const makeRun = (id, date, configuration = "primary") => ({
  id,
  status: "Succeeded",
  created_at: `${date}T12:00:00Z`,
  input: {
    configuration_id: configuration,
    strategy: { id: "example", file_hash: "source" },
    dataset: { symbol: "NQ" },
    end: date,
    timeframe: "1h",
    session: "full-trading-day",
    parameters: { setup: configuration },
  },
  result: { metrics: {} },
});
const entry = id => ({ id, archived_at: "2026-10-01T00:00:00Z" });

test("archiving the latest run reveals the older active attempt without changing saved history", () => {
  const older = makeRun("older", "2026-01-01");
  const newer = makeRun("newer", "2026-02-01");
  const runs = [older, newer];
  const before = structuredClone(runs);
  const result = runHistoryGroups(runs, { runs: [entry(newer.id)], configurations: [] });
  assert.deepEqual(result.activeRuns, [older]);
  assert.deepEqual(result.latestHistory, [older]);
  assert.deepEqual(result.archivedRuns, [newer]);
  assert.deepEqual(runs, before);
  assert.deepEqual(runHistoryGroups(runs).latestHistory, [newer]);
});

test("archive shows every attempt and includes configuration archives without duplicate rows", () => {
  const older = makeRun("older", "2026-01-01");
  const newer = makeRun("newer", "2026-02-01");
  const other = makeRun("other", "2026-03-01", "alternative");
  const corrupt = { ...makeRun("corrupt", "2026-04-01"), result: {} };
  const archive = {
    runs: [entry(newer.id)],
    configurations: [{ strategy_id: "example", configuration_key: runConfigurationKey(older), archived_at: "2026-10-01T00:00:00Z" }],
  };
  const result = runHistoryGroups([older, newer, other, corrupt], archive);
  assert.deepEqual(result.activeRuns, [other]);
  assert.deepEqual(result.latestHistory, [other]);
  assert.deepEqual(result.archivedRuns, [older, newer, corrupt]);
  const restoredConfiguration = runHistoryGroups([older, newer, other, corrupt], { ...archive, configurations: [] });
  assert.deepEqual(restoredConfiguration.archivedRuns, [newer]);
  assert.deepEqual(restoredConfiguration.latestHistory, [other, older]);
});

test("run archive controls reject every active execution status", () => {
  for (const status of ["Queued", "Running", "Summarizing"]) assert.equal(canArchiveRun({ status }), false, status);
  for (const status of ["Succeeded", "Failed", "Canceled", "Interrupted"]) assert.equal(canArchiveRun({ status }), true, status);
});
