import assert from "node:assert/strict";
import { test } from "node:test";
import {
  portfolioPeriodComponents,
  portfolioPeriodMetrics,
  portfolioPeriodPnl,
  portfolioPeriodPoints,
  portfolioPeriodStart,
} from "../../shared/ts/portfolioPeriods.ts";
import { calculatePortfolio, defaultPolicy } from "../../shared/ts/portfolio.ts";

test("portfolio periods use the selected end and clamp to the tested start", () => {
  const start = "2024-01-15";
  const end = "2026-09-30";
  assert.equal(portfolioPeriodStart("all", start, end), start);
  assert.equal(portfolioPeriodStart("1y", start, end), "2025-09-30");
  assert.equal(portfolioPeriodStart("ytd", start, end), "2026-01-01");
  assert.equal(portfolioPeriodStart("6m", start, end), "2026-03-30");
  assert.equal(portfolioPeriodStart("1m", start, end), "2026-08-30");
  assert.equal(portfolioPeriodStart("1y", "2026-06-01", end), "2026-06-01");
});

test("portfolio periods clamp calendar subtraction at month ends and leap days", () => {
  assert.equal(portfolioPeriodStart("1m", "2023-01-01", "2023-03-31"), "2023-02-28");
  assert.equal(portfolioPeriodStart("1m", "2024-01-01", "2024-03-31"), "2024-02-29");
  assert.equal(portfolioPeriodStart("1y", "2023-01-01", "2024-02-29"), "2023-02-28");
});

test("portfolio P&L sums daily replay results inside each inclusive period", () => {
  const points = [
    { date: "2025-09-29", pnl: 1 },
    { date: "2025-09-30", pnl: 2 },
    { date: "2026-01-01", pnl: 4 },
    { date: "2026-03-30", pnl: 8 },
    { date: "2026-08-29", pnl: 16 },
    { date: "2026-08-30", pnl: 32 },
    { date: "2026-09-30", pnl: 64 },
    { date: "2026-10-01", pnl: 128 },
  ];
  const start = "2025-09-29";
  const end = "2026-09-30";
  assert.deepEqual(portfolioPeriodPoints(points, "1m", start, end).map((point) => point.date), ["2026-08-30", "2026-09-30"]);
  assert.equal(portfolioPeriodPnl(points, "all", start, end), 127);
  assert.equal(portfolioPeriodPnl(points, "1y", start, end), 126);
  assert.equal(portfolioPeriodPnl(points, "ytd", start, end), 124);
  assert.equal(portfolioPeriodPnl(points, "6m", start, end), 120);
  assert.equal(portfolioPeriodPnl(points, "1m", start, end), 96);
  assert.equal(portfolioPeriodPnl(points, "1m", "2026-09-30", end), 64);
});

test("period risk and trade ratios use only accepted outcomes in the selected replay days", () => {
  const start = "2025-12-31";
  const end = "2026-01-04";
  const item = {
    id: "book", name: "Book", symbol: "ES", timeframe: "1m", session: "rth",
    coverage: [{ start, end }],
  };
  const trade = (date, pnl) => ({
    entry: `${date}T10:00:00Z`, exit: `${date}T11:00:00Z`, pnl,
  });
  const series = {
    id: "book", coverage: item.coverage, daily: [],
    trades: [
      trade("2025-12-31", 10), trade("2026-01-01", -20),
      trade("2026-01-02", 40), trade("2026-01-03", -10),
      trade("2026-01-04", 100),
    ],
  };
  const policy = {
    ...defaultPolicy, enabled: true, mode: "manual",
    manual: { book: [{ timestamp: "2026-01-04T00:00:00Z", action: "pause", reason: "hold" }] },
  };
  const result = calculatePortfolio([item], [series], { book: 1 }, start, end, "closed", policy, 100);
  const all = portfolioPeriodMetrics(result, portfolioPeriodPoints(result.points, "all", start, end));
  assert.deepEqual(all, {
    maxDrawdownDollars: result.maxDrawdownDollars,
    maxDrawdown: result.maxDrawdown,
    recoveryFactor: result.recoveryFactor,
    profitFactor: result.profitFactor,
    winRate: result.winRate,
    trades: result.trades,
    positiveDays: result.positiveDays,
    activeDays: result.activeDays,
  });
  assert.equal(result.profitFactor, 50 / 30);
  assert.equal(result.points.at(-1).grossProfit, 0);
  assert.equal(result.points.at(-1).trades, 0);

  const ytd = portfolioPeriodMetrics(result, portfolioPeriodPoints(result.points, "ytd", start, end));
  assert.equal(ytd.maxDrawdownDollars, 20);
  assert.ok(Math.abs(ytd.maxDrawdown + 0.2) < 1e-12);
  assert.equal(ytd.recoveryFactor, 0.5);
  assert.equal(ytd.profitFactor, 40 / 30);
  assert.equal(ytd.winRate, 1 / 3);
  assert.equal(ytd.trades, 3);
  assert.equal(ytd.positiveDays, 1);
  assert.equal(ytd.activeDays, 3);

  assert.strictEqual(portfolioPeriodComponents(result, result.points), result.components);
  const [component] = portfolioPeriodComponents(result, portfolioPeriodPoints(result.points, "ytd", start, end));
  assert.equal(component.id, "book");
  assert.equal(component.state, "Paused");
  assert.equal(component.pnl, 10);
  assert.equal(component.maxDrawdownDollars, 20);
  assert.equal(component.baseline, 110);
  assert.equal(component.trades, 3);
  assert.equal(component.skipped, 1);
  assert.equal(component.exposure, 0.75);
});

test("period contributions keep each strategy's P&L path and baseline separate", () => {
  const start = "2025-12-31";
  const end = "2026-01-02";
  const items = ["a", "b"].map((id) => ({
    id, name: id, symbol: "ES", timeframe: "1m", session: "rth",
    coverage: [{ start, end }],
  }));
  const trades = (outcomes) => outcomes.map(([date, pnl]) => ({
    entry: `${date}T10:00:00Z`, exit: `${date}T11:00:00Z`, pnl,
  }));
  const series = [
    { id: "a", coverage: items[0].coverage, daily: [], trades: trades([
      ["2025-12-31", 10], ["2026-01-01", -20], ["2026-01-02", 40],
    ]) },
    { id: "b", coverage: items[1].coverage, daily: [], trades: trades([
      ["2025-12-31", -5], ["2026-01-01", 15], ["2026-01-02", -10],
    ]) },
  ];
  const policy = {
    ...defaultPolicy, enabled: true, mode: "manual",
    manual: { b: [{ timestamp: "2026-01-02T00:00:00Z", action: "pause", reason: "hold" }] },
  };
  const result = calculatePortfolio(items, series, { a: 1, b: 1 }, start, end, "closed", policy, 100);
  const rows = portfolioPeriodComponents(result, portfolioPeriodPoints(result.points, "ytd", start, end));
  assert.deepEqual(rows.map(({ id, pnl, maxDrawdownDollars, baseline, trades, skipped, exposure, state }) => ({
    id, pnl, maxDrawdownDollars, baseline, trades, skipped, exposure, state,
  })), [
    { id: "a", pnl: 20, maxDrawdownDollars: 20, baseline: 20, trades: 2, skipped: 0, exposure: 1, state: "Active" },
    { id: "b", pnl: 15, maxDrawdownDollars: 0, baseline: 5, trades: 1, skipped: 1, exposure: 0.5, state: "Paused" },
  ]);
  assert.equal(result.points.at(-1).byStrategyBaseline.b, -10);
  assert.equal(result.points.at(-1).byStrategySkipped.b, 1);
  assert.equal(result.points.at(-1).byStrategyTrades.a, 1);
});

test("period metrics preserve null ratios for no-loss, no-drawdown, and empty windows", () => {
  const result = {
    capital: 100,
    points: [{ date: "2026-01-01" }, { date: "2026-01-02" }],
  };
  const winner = portfolioPeriodMetrics(result, [{
    date: "2026-01-02", pnl: 20, trades: 1, grossProfit: 20,
    grossLoss: 0, winningTrades: 1,
  }]);
  assert.equal(winner.maxDrawdownDollars, 0);
  assert.equal(winner.maxDrawdown, 0);
  assert.equal(winner.recoveryFactor, null);
  assert.equal(winner.profitFactor, null);
  assert.equal(winner.winRate, 1);
  const empty = portfolioPeriodMetrics(result, []);
  assert.equal(empty.trades, 0);
  assert.equal(empty.profitFactor, null);
  assert.equal(empty.winRate, null);
  assert.equal(empty.activeDays, 0);
});
