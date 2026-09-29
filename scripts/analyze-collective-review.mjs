import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { calculatePortfolio, defaultPolicy } from "../src/collectiveModel.ts";

const folder = "reports/workbench-review-2026-09-16";
const catalog = JSON.parse(
  readFileSync("data/workbench/collective/index.json", "utf8"),
);
const histories = new Map();
for (const item of catalog.items) {
  const bytes = readFileSync("data/workbench/collective/" + item.series_file);
  if (createHash("sha256").update(bytes).digest("hex") !== item.checksum)
    throw new Error("Corrupt history: " + item.id);
  histories.set(item.id, JSON.parse(bytes));
}
const compact = (r) => ({
  net: r.net,
  baseline: r.baseline,
  capital: r.capital,
  drawdown: r.maxDrawdown,
  drawdown_dollars: r.maxDrawdownDollars,
  recovery_factor: r.recoveryFactor,
  trades: r.trades,
  profit_factor: r.profitFactor,
  win_rate: r.winRate,
  exposure: r.exposure,
  components: r.components,
});
const working = catalog.items.filter((i) => i.working);
const series = working.map((i) => histories.get(i.id)),
  copies = Object.fromEntries(working.map((i) => [i.id, 1]));
const portfolios = {};
for (const mode of [
  "off-marked",
  "off-closed",
  "rolling",
  "streak",
  "drawdown",
  "volatility",
]) {
  const policy = {
    ...defaultPolicy,
    enabled: !mode.startsWith("off"),
    mode: mode.startsWith("off") ? "rolling" : mode,
  };
  const result = calculatePortfolio(
    working,
    series,
    copies,
    "2024-01-01",
    "2026-08-31",
    mode === "off-marked" ? "marked" : "closed",
    policy,
  );
  portfolios[mode] = compact(result);
  if (mode === "rolling") {
    writeFileSync(
      folder + "/pause-decisions.json",
      JSON.stringify(result.events, null, 2),
    );
    writeFileSync(
      folder + "/loss-dependence.json",
      JSON.stringify(result.dependence, null, 2),
    );
  }
}
const rows = [];
for (const item of catalog.items) {
  const s = histories.get(item.id);
  for (const [start, end] of [
    ["2024-01-01", "2024-12-31"],
    ["2025-01-01", "2025-12-31"],
    ["2026-01-01", "2026-08-31"],
  ]) {
    try {
      const result = calculatePortfolio(
        [item],
        [s],
        { [item.id]: 1 },
        start,
        end,
        "marked",
        defaultPolicy,
      );
      rows.push({
        id: item.id,
        name: item.name,
        symbol: item.symbol,
        timeframe: item.timeframe,
        start,
        end,
        working: item.working,
        feasible: item.feasible,
        ...compact(result),
        components: undefined,
      });
    } catch (e) {
      rows.push({
        id: item.id,
        name: item.name,
        symbol: item.symbol,
        timeframe: item.timeframe,
        start,
        end,
        unavailable: e.message,
      });
    }
  }
}
const correlations = [];
const daily = series.map((s) => new Map(s.daily.map((p) => [p.date, p.pnl])));
const dates = [...new Set(series.flatMap((s) => s.daily.map((p) => p.date)))]
  .filter((d) => d >= "2024-01-01" && d <= "2026-08-31")
  .sort();
for (let i = 0; i < working.length; i++)
  for (let j = i + 1; j < working.length; j++) {
    const a = dates.map((d) => daily[i].get(d) || 0),
      b = dates.map((d) => daily[j].get(d) || 0);
    const am = a.reduce((s, x) => s + x, 0) / a.length,
      bm = b.reduce((s, x) => s + x, 0) / b.length;
    const numerator = a.reduce((s, x, k) => s + (x - am) * (b[k] - bm), 0);
    const denom = Math.sqrt(
      a.reduce((s, x) => s + (x - am) ** 2, 0) *
        b.reduce((s, x) => s + (x - bm) ** 2, 0),
    );
    correlations.push({
      a: working[i].name + " / " + working[i].symbol,
      b: working[j].name + " / " + working[j].symbol,
      correlation: denom ? numerator / denom : null,
    });
  }
writeFileSync(
  folder + "/collective-analysis.json",
  JSON.stringify(
    {
      checked_at: new Date().toISOString(),
      verified_histories: histories.size,
      import_errors: catalog.errors,
      portfolios,
      correlations: correlations.sort((a, b) => b.correlation - a.correlation),
      annual_configurations: rows,
    },
    null,
    2,
  ),
);
console.log(
  JSON.stringify(
    {
      histories: histories.size,
      working: working.length,
      portfolios: Object.fromEntries(
        Object.entries(portfolios).map(([k, v]) => [
          k,
          {
            net: v.net,
            drawdown: v.drawdown_dollars,
            score: v.recovery_factor,
          },
        ]),
      ),
      correlations: correlations.slice(0, 6),
    },
    null,
    2,
  ),
);
