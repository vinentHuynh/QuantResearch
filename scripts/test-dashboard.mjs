import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, writeFileSync, unlinkSync, rmdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  createDashboard,
  parseCsv,
  sameSettings,
  tradeStatistics,
} from "../server/dashboard.ts";

const stats = tradeStatistics([200, 100, -50, -100, 0]);
assert.equal(stats.payoff_ratio, 2);
assert.equal(stats.profit_factor, 2);
assert.equal(stats.win_rate, 0.4);
assert.equal(stats.expectancy, 30);
assert.equal(stats.breakeven, 1);
assert.equal(tradeStatistics([10, 20]).profit_factor, null);
assert.equal(tradeStatistics([10, 20]).payoff_ratio, null);
assert.equal(tradeStatistics([-10, -20]).profit_factor, 0);
assert.equal(tradeStatistics([]).win_rate, null);
assert.equal(tradeStatistics([0]).expectancy, 0);
assert.throws(() => tradeStatistics([NaN]), /Nonfinite/);
assert.deepEqual(
  parseCsv(
    'net_pnl,note\r\n100,"comma, and ""quote"""\r\n-50,"multi\nline"\r\n',
  ),
  [
    ["net_pnl", "note"],
    ["100", 'comma, and "quote"'],
    ["-50", "multi\nline"],
  ],
);
assert.throws(() => parseCsv('a\n"unterminated'), /Unterminated/);
const folder = mkdtempSync(join(tmpdir(), "workbench-dashboard-")),
  path = join(folder, "trades.csv");
try {
  const csv =
    "net_pnl,note\n" +
    Array.from(
      { length: 120 },
      (_, i) => `${i % 2 ? -50 : 100},"trade, ${i}"`,
    ).join("\n");
  writeFileSync(path, csv);
  const strategy = {
    id: "test",
    name: "Test strategy",
    file_hash: "same",
    execution_model: "event-v1",
  };
  const input = {
    strategy,
    dataset: { symbol: "NQ" },
    parameters: { reward_risk: 2, lookback: 20 },
    timeframe: "5m",
    session: "full-trading-day",
    capital: 100000,
    fee: 1.25,
    slippage: 1,
    warmup_days: 60,
    delay_bars: 0,
    start: "2025-01-01",
    end: "2025-12-31",
    research: { scenario: "Baseline" },
  };
  const metrics = {
    net_pnl: 3000,
    net_return: 0.03,
    max_drawdown: -0.1,
    trades: 120,
    costs: 10,
    sharpe: 1,
  };
  const scenarios = ["Baseline", "Higher costs"].map((name) => ({
    name,
    outcome: "Meets criteria",
    metrics,
    equity_preview: [],
  }));
  const run = {
    id: "full",
    created_at: "2026-01-02",
    status: "Succeeded",
    input,
    result: {
      metrics,
      trade_preview: Array(100).fill({ net_pnl: 999999 }),
      artifacts: [
        {
          name: "trades.csv",
          checksum: createHash("sha256").update(csv).digest("hex"),
        },
      ],
    },
  };
  const evaluation = {
    id: "e",
    name: "Evaluation",
    created_at: "2026-01-01",
    status: "Succeeded",
    candidates: [input],
    folds: [
      { test_start: "2025-01-01", test_end: "2025-12-31", tests: ["full"] },
    ],
    result: { scenarios },
    scenarios: scenarios.map((s) => s.name),
    min_return: 0,
    max_drawdown: 0.35,
    min_test_trades: 20,
    source_hash: "snapshot",
    outcome: "Meets criteria",
  };
  const records = {
    run: [run],
    evaluation: [evaluation],
    regime: [],
    dataset: [
      { symbol: "NQ", last: "2026-09-03" },
      { symbol: "ES", last: "2026-09-03" },
    ],
  };
  const registered = [
    strategy,
    { id: "new", name: "New strategy", file_hash: "new" },
  ];
  const dashboard = createDashboard({
    all: (kind) => records[kind],
    strategies: () => registered,
    runDir: () => folder,
  });
  let row = dashboard().rows.find((r) => r.strategy_id === "test");
  assert.equal(row.status, "Research candidate");
  assert.equal(row.trades.trades, 120);
  assert.equal(row.trades.net_pnl, 3000);
  assert.equal(row.trades.payoff_ratio, 2);
  assert.equal(row.target_rr, 2);
  assert.equal(
    dashboard().rows.find((r) => r.strategy_id === "new").status,
    "Not evaluated",
  );
  assert(dashboard("ES").rows.every((r) => r.status === "Not evaluated"));
  assert.throws(() => dashboard("INVALID"), /Unknown/);
  assert(
    sameSettings(input, {
      ...input,
      parameters: { lookback: 20, reward_risk: 2 },
    }),
  );
  assert(!sameSettings(input, { ...input, capital: 50000 }));
  const prior = {
    ...run,
    id: "prior",
    created_at: "2025-01-01",
    tags: "campaign, checks-failed",
  };
  records.run.push(prior);
  assert.equal(dashboard().rows[0].status, "Conditional");
  prior.input = { ...input, capital: 50000 };
  assert.equal(dashboard().rows[0].status, "Research candidate");
  records.run.pop();
  records.evaluation.push({
    ...evaluation,
    id: "newer",
    created_at: "2026-02-01",
    status: "Failed",
    result: undefined,
    error: "Failed trial",
  });
  row = dashboard().rows[0];
  assert.equal(row.status, "Incomplete");
  assert.equal(row.scenarios.length, 0);
  records.evaluation.pop();
  scenarios[1].outcome = "Does not meet criteria";
  assert.equal(dashboard().rows[0].status, "Needs review");
  scenarios[1].outcome = "Meets criteria";
  scenarios[1].metrics = { ...metrics, net_pnl: -1 };
  assert.equal(dashboard().rows[0].status, "Needs review");
  scenarios[1].metrics = metrics;
  const missing = scenarios.pop();
  assert.match(dashboard().rows[0].reasons.join(" "), /evidence is missing/);
  scenarios.push(missing);
  registered[0] = { ...strategy, file_hash: "changed" };
  assert.equal(dashboard().rows[0].status, "Needs review");
  registered[0] = strategy;
  writeFileSync(path, csv + "\n123,bad");
  row = dashboard().rows[0];
  assert.equal(row.status, "Needs review");
  assert.equal(row.trades, null);
  assert.match(row.trade_error, /checksum/);
  writeFileSync(path, csv);
  metrics.trades = 100;
  assert.match(dashboard().rows[0].trade_error, /reconcile/);
  console.log(
    "Dashboard tests passed: full ledgers, R:R, profit factor, zero-loss/empty cases, CSV parsing, latest-attempt selection, prior flags, market isolation, new strategies, changed code and corrupt evidence.",
  );
} finally {
  unlinkSync(path);
  rmdirSync(folder);
}
