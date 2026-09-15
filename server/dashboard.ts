import { readFileSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import type { Run, Input } from "./workbench.ts";
import type { Evaluation } from "./research.ts";
import type {
  DashboardData,
  DashboardRow,
  DashboardScenario,
  DashboardRegime,
  TradeStats,
} from "../src/dashboardTypes.ts";

export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [],
    field = "",
    quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      if (quoted && text[i + 1] === '"') {
        field += '"';
        i++;
      } else quoted = !quoted;
    } else if (c === "," && !quoted) {
      row.push(field);
      field = "";
    } else if (c === "\n" && !quoted) {
      row.push(field.replace(/\r$/, ""));
      if (row.some(Boolean)) rows.push(row);
      row = [];
      field = "";
    } else field += c;
  }
  if (quoted) throw new Error("Unterminated trade CSV field");
  if (field || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  return rows;
}
export function tradeStatistics(pnl: number[]): TradeStats {
  if (pnl.some((v) => !Number.isFinite(v)))
    throw new Error("Nonfinite trade P&L");
  const winners = pnl.filter((v) => v > 0),
    losers = pnl.filter((v) => v < 0);
  const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);
  const profit = sum(winners),
    loss = -sum(losers),
    net = sum(pnl);
  const average_win = winners.length ? profit / winners.length : null;
  const average_loss = losers.length ? loss / losers.length : null;
  return {
    trades: pnl.length,
    wins: winners.length,
    losses: losers.length,
    breakeven: pnl.length - winners.length - losers.length,
    net_pnl: net,
    win_rate: pnl.length ? winners.length / pnl.length : null,
    average_win,
    average_loss,
    expectancy: pnl.length ? net / pnl.length : null,
    payoff_ratio:
      average_win !== null && average_loss !== null
        ? average_win / average_loss
        : null,
    profit_factor: loss ? profit / loss : null,
  };
}
const canonical = (value: unknown): string =>
  value && typeof value === "object" && !Array.isArray(value)
    ? JSON.stringify(
        Object.fromEntries(
          Object.entries(value)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([k, v]) => [k, canonical(v)]),
        ),
      )
    : JSON.stringify(value);
export function sameSettings(a: Input, b: Input) {
  return (
    a.strategy.id === b.strategy.id &&
    a.strategy.file_hash === b.strategy.file_hash &&
    a.dataset.symbol === b.dataset.symbol &&
    [
      "timeframe",
      "session",
      "capital",
      "fee",
      "slippage",
      "warmup_days",
      "delay_bars",
    ].every((k) => (a[k as keyof Input] ?? 0) === (b[k as keyof Input] ?? 0)) &&
    canonical(a.parameters) === canonical(b.parameters)
  );
}
type Strategy = Pick<Input["strategy"], "id" | "name" | "file_hash">;
type Regime = {
  id: string;
  evaluation_id: string;
  status: string;
  feature: string;
  window: number;
  created_at: string;
  result?: { states: DashboardRegime["states"] };
};
type Dependencies = {
  all: <T>(kind: string) => T[];
  strategies: () => Strategy[];
  runDir: (id: string) => string;
};
export function createDashboard(d: Dependencies) {
  const cache = new Map<string, { key: string; pnl: number[] }>();
  function ledger(run: Run) {
    const artifacts = run.result?.artifacts as
      { name: string; checksum: string }[] | undefined;
    const entry = artifacts?.find((a) => a.name === "trades.csv");
    if (!entry?.checksum)
      throw new Error("Verified full trade ledger is unavailable");
    const path = join(d.runDir(run.id), "trades.csv"),
      stat = statSync(path);
    const key = `${entry.checksum}:${stat.mtimeMs}:${stat.ctimeMs}:${stat.size}`;
    if (cache.get(run.id)?.key === key) return cache.get(run.id)!.pnl;
    const bytes = readFileSync(path);
    if (createHash("sha256").update(bytes).digest("hex") !== entry.checksum)
      throw new Error("Trade ledger checksum changed");
    const [header, ...rows] = parseCsv(bytes.toString("utf8"));
    const column = header?.indexOf("net_pnl");
    if (column === undefined || column < 0)
      throw new Error("Trade P&L column is missing");
    const pnl = rows.map((r) => {
      const value = r[column];
      if (!value?.trim() || !Number.isFinite(Number(value)))
        throw new Error("Invalid trade P&L");
      return Number(value);
    });
    if (cache.size >= 256) cache.clear();
    cache.set(run.id, { key, pnl });
    return pnl;
  }
  return function dashboard(symbol?: string): DashboardData {
    const runs = d.all<Run>("run"),
      evaluations = d.all<Evaluation>("evaluation"),
      regimes = d.all<Regime>("regime");
    const datasets = d.all<{ symbol: string; last: string }>("dataset");
    const symbols = [
      ...new Set([
        ...datasets.map((r) => r.symbol),
        ...evaluations.map((e) => e.candidates[0].dataset.symbol),
      ]),
    ].sort();
    const market =
      symbol || (symbols.includes("NQ") ? "NQ" : symbols[0] || "NQ");
    if (symbols.length && !symbols.includes(market))
      throw new Error("Unknown dashboard market");
    const registered = d.strategies(),
      strategies = [...registered];
    for (const e of evaluations)
      if (!strategies.some((s) => s.id === e.candidates[0].strategy.id))
        strategies.push(e.candidates[0].strategy);
    const rows: DashboardRow[] = strategies.map((strategy) => {
      const history = evaluations
        .filter(
          (e) =>
            e.candidates[0].strategy.id === strategy.id &&
            e.candidates[0].dataset.symbol === market,
        )
        .sort(
          (a, b) =>
            (b.folds.at(-1)?.test_end || "").localeCompare(
              a.folds.at(-1)?.test_end || "",
            ) || b.created_at.localeCompare(a.created_at),
        );
      const e = history[0];
      const row: DashboardRow = {
        strategy_id: strategy.id,
        name: strategy.name,
        symbol: market,
        status: "Not evaluated",
        reasons: [],
        target_rr: null,
        scenarios: [],
        trades: null,
        baseline_run_ids: [],
        regimes: [],
        prior_flags: [],
        parameters: [],
      };
      if (!e) {
        row.reasons.push(
          "No evaluation is available for this strategy and market.",
        );
        return row;
      }
      const base = e.candidates[0];
      Object.assign(row, {
        evaluation_id: e.id,
        evaluation_name: e.name,
        evaluated_at: e.created_at,
        start: e.folds[0].test_start,
        end: e.folds.at(-1)!.test_end,
        timeframe: base.timeframe,
        session: base.session,
        capital: base.capital,
        fee: base.fee,
        slippage: base.slippage,
        source_hash: e.source_hash,
      });
      row.newer_data_through = datasets
        .filter((ds) => ds.symbol === market)
        .map((ds) => ds.last.slice(0, 10))
        .sort()
        .at(-1);
      const result = e.result as { scenarios: DashboardScenario[] } | undefined;
      if (e.status !== "Succeeded" || !result?.scenarios?.length) {
        row.status = ["Running", "Summarizing", "Queued"].includes(e.status)
          ? "In progress"
          : "Incomplete";
        row.reasons.push(
          e.error ||
            e.note ||
            `Latest evaluation is ${e.status}. Earlier results are not substituted.`,
        );
        return row;
      }
      row.scenarios = result.scenarios;
      const baseline = row.scenarios.find((s) => s.name === "Baseline");
      const baselineRuns = e.folds.map((f) =>
        runs.find((r) => r.id === f.tests[0]),
      );
      row.baseline_run_ids = baselineRuns
        .filter((r): r is Run => !!r)
        .map((r) => r.id);
      row.parameters = baselineRuns
        .filter((r): r is Run => !!r)
        .map((r) => r.input.parameters);
      const rr = row.parameters.map((p) => p.reward_risk);
      if (
        rr.length &&
        rr.every((v) => typeof v === "number" && v > 0 && v === rr[0])
      )
        row.target_rr = Number(rr[0]);
      try {
        if (
          !baseline ||
          baselineRuns.some(
            (r) =>
              !r ||
              r.status !== "Succeeded" ||
              r.input.research?.scenario !== "Baseline",
          )
        )
          throw new Error("Baseline fold evidence is incomplete");
        row.trades = tradeStatistics(baselineRuns.flatMap((r) => ledger(r!)));
        if (
          row.trades.trades !== baseline.metrics.trades ||
          Math.abs(row.trades.net_pnl - baseline.metrics.net_pnl) > 0.01
        )
          throw new Error(
            "Full trade ledger does not reconcile with evaluation",
          );
      } catch (error) {
        row.trades = null;
        row.trade_error = String(error);
        row.reasons.push(row.trade_error);
      }
      const selectedInputs = baselineRuns
        .filter((r): r is Run => !!r)
        .map((r) => r.input);
      row.prior_flags = runs
        .filter(
          (r) =>
            r.created_at < e.created_at &&
            r.status === "Succeeded" &&
            /\bchecks-failed\b/.test(r.tags || "") &&
            selectedInputs.some((input) => sameSettings(input, r.input)),
        )
        .map((r) => ({ id: r.id, end: r.input.end, kind: "run" as const }));
      for (const older of history.slice(1))
        if (
          older.created_at < e.created_at &&
          older.status === "Succeeded" &&
          older.result &&
          older.outcome !== "Meets criteria" &&
          older.candidates.every((c) =>
            selectedInputs.some((input) => sameSettings(input, c as Input)),
          )
        )
          row.prior_flags.push({
            id: older.id,
            end: older.folds.at(-1)!.test_end,
            kind: "evaluation",
          });
      const changed = !registered.some(
        (s) => s.id === strategy.id && s.file_hash === base.strategy.file_hash,
      );
      const expected = e.scenarios || [
        "Baseline",
        "Higher costs",
        "Delayed execution",
      ];
      const meets = expected.every(
        (name) =>
          row.scenarios.find((s) => s.name === name)?.outcome ===
            "Meets criteria" &&
          (row.scenarios.find((s) => s.name === name)?.metrics.net_pnl ?? 0) >
            0,
      );
      row.status =
        changed || row.trade_error || !meets
          ? "Needs review"
          : row.prior_flags.length
            ? "Conditional"
            : "Research candidate";
      if (changed)
        row.reasons.push(
          "The strategy adapter has changed or is no longer registered.",
        );
      for (const name of expected)
        if (!row.scenarios.some((s) => s.name === name))
          row.reasons.push(`${name}: declared scenario evidence is missing.`);
      for (const s of row.scenarios)
        if (s.metrics.net_pnl <= 0)
          row.reasons.push(`${s.name}: net profit is not positive.`);
      for (const s of row.scenarios)
        if (s.outcome !== "Meets criteria") {
          const failures = [
            s.metrics.net_return < e.min_return ? "return below criterion" : "",
            Math.abs(s.metrics.max_drawdown) > e.max_drawdown
              ? `drawdown exceeds ${(e.max_drawdown * 100).toFixed(0)}%`
              : "",
            s.metrics.trades < e.min_test_trades ? "too few trades" : "",
          ].filter(Boolean);
          row.reasons.push(`${s.name}: ${failures.join("; ") || s.outcome}.`);
        }
      if (row.prior_flags.length)
        row.reasons.push(
          `${row.prior_flags.length} earlier matching research check(s) remain flagged for review.`,
        );
      if (meets)
        row.reasons.push(
          "All declared latest scenarios are profitable and meet the evaluation criteria.",
        );
      if (!row.scenarios.some((s) => s.name === "Delayed execution"))
        row.reasons.push(
          base.strategy.execution_model === "event-v1"
            ? "Event-order delay sensitivity is untested."
            : "Execution-delay stress was not included.",
        );
      if (strategy.id === "buy-hold") {
        row.status = "Benchmark";
        row.reasons.unshift("Passive comparison benchmark.");
      }
      for (const feature of ["volatility", "trend"]) {
        const study = regimes
          .filter((r) => r.evaluation_id === e.id && r.feature === feature)
          .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
        if (study?.status === "Succeeded" && study.result)
          row.regimes.push({
            id: study.id,
            feature,
            window: study.window,
            states: study.result.states,
          });
      }
      return row;
    });
    const order = [
      "Research candidate",
      "Conditional",
      "Needs review",
      "Benchmark",
      "In progress",
      "Incomplete",
      "Not evaluated",
    ];
    rows.sort(
      (a, b) =>
        order.indexOf(a.status) - order.indexOf(b.status) ||
        a.name.localeCompare(b.name),
    );
    return {
      generated_at: new Date().toISOString(),
      symbols,
      symbol: market,
      rows,
    };
  };
}
