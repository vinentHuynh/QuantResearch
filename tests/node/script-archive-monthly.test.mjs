import assert from "node:assert/strict";
import { test } from "node:test";
import { parseCsv } from "../../server/features/scorecards/dashboard.ts";
import { visibleMonthlyCsv, visibleMonthlyReport } from "../../server/features/scripts/archiveVisibility.ts";

test("saved NQ comparison hides archived scripts and ranks remaining rows", () => {
  const report = {
    rows: [
      { strategy_id: "archived", rank: 1 },
      { strategy_id: "active", rank: 2 },
      { strategy_id: "unranked", rank: null },
    ],
    zone_screen: { attempts: 3, selected_exit: "example", actual_exit_profitable: 0 },
  };
  const visible = visibleMonthlyReport(report, new Set(["archived"]));
  assert.deepEqual(visible.rows, [
    { strategy_id: "active", rank: 1 },
    { strategy_id: "unranked", rank: null },
  ]);
  assert.equal(report.rows[1].rank, 2);
  assert.equal(visibleMonthlyReport(report, new Set(["snd"])).zone_screen.attempts, 0);
});

test("saved NQ CSV exports remove archived rows while preserving quoted fields", () => {
  const source = [
    '"rank","strategy_id","selection_note"',
    '"1","archived","Research, first"',
    '"2","active","Research, second"',
    '"","unranked","No trades"',
  ].join("\n") + "\n";
  const visible = parseCsv(visibleMonthlyCsv(source, new Set(["archived"])));
  assert.deepEqual(visible, [
    ["rank", "strategy_id", "selection_note"],
    ["1", "active", "Research, second"],
    ["", "unranked", "No trades"],
  ]);
});
