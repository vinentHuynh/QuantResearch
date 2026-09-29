import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { defaultPolicy, replayGate } from "../src/collectiveModel.ts";
import { defaultSizing, volatilityModel } from "../src/riskSizing.ts";

const api = "http://127.0.0.1:8001/api/workbench";
async function get(path, body) {
  const response = await fetch(api + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}
const catalog = await get("/collective");
const items = catalog.items.filter(i => i.working);
const histories = await get("/collective/series", { ids: items.map(i => i.id) });
const stamp = new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-");
const folder = join("reports", `latest-condition-${stamp}`);
mkdirSync(folder, { recursive: true });
const policy = { ...defaultPolicy, enabled: true, mode: "deterioration", sizing: { ...defaultSizing } };
const plan = {
  checked_at: new Date().toISOString(), scope: "Seven working/default books, one copy each; not the user's browser-specific selection",
  catalog_at: catalog.generated_at, policy, reporting_start: "2024-01-01",
  classification: "Pause/review when the existing deterioration replay is paused; insufficient monitoring sample when fewer than 30 post-calibration normalized trades exist; otherwise Watch if the last 20 closed trades have negative net P&L; otherwise No deterioration flag. Watch is an audit label, not a new app rule. No flag is not a profitability forecast.",
  accounting: "Recorded net trade outcomes. Current marked drawdown uses all recorded daily marks from each book's inception. Terminal closes can be forced by the test boundary. No live prices, changed strategy settings, or parameter search.",
  sources: items.map(i => ({ id: i.id, name: i.name, symbol: i.symbol, timeframe: i.timeframe, checksum: i.checksum, series_file: i.series_file, coverage_end: i.end })),
  code: ["src/collectiveModel.ts", "src/riskSizing.ts"].map(path => ({ path, checksum: createHash("sha256").update(readFileSync(path)).digest("hex") })),
};
writeFileSync(join(folder, "criteria.json"), JSON.stringify(plan, null, 2), { flag: "wx" });
const sum = xs => xs.reduce((a, b) => a + b, 0);
const mean = xs => xs.length ? sum(xs) / xs.length : null;
const sd = xs => Math.sqrt(sum(xs.map(x => (x - mean(xs)) ** 2)) / (xs.length - 1));
const rows = [];
for (const item of items) {
  const history = histories.find(s => s.id === item.id);
  const bytes = readFileSync(join("data/workbench/collective", item.series_file));
  if (createHash("sha256").update(bytes).digest("hex") !== item.checksum) throw new Error("Source checksum mismatch: " + item.id);
  const end = item.end, cutoff = Date.parse(end + "T23:59:59.999Z");
  const trades = history.trades.filter(t => Date.parse(t.exit) <= cutoff).sort((a, b) => Date.parse(a.exit) - Date.parse(b.exit));
  const daily = history.daily.filter(p => p.date <= end).sort((a, b) => a.date.localeCompare(b.date));
  const windows = Object.fromEntries([10, 20, 30].map(n => {
    const ts = trades.slice(-n);
    return [n, { trades: ts.length, net: sum(ts.map(t => t.pnl)), wins: ts.filter(t => t.pnl > 0).length, first_exit: ts[0]?.exit, last_exit: ts.at(-1)?.exit }];
  }));
  let streak = 0;
  for (let n = trades.length - 1; n >= 0 && trades[n].pnl < 0; n--) streak++;
  let pnl = 0, peak = 0, peakDate = item.start, maximumDrawdown = 0;
  for (const p of daily) { pnl += p.pnl; if (pnl >= peak) { peak = pnl; peakDate = p.date; } maximumDrawdown = Math.max(maximumDrawdown, peak - pnl); }
  const model = volatilityModel(daily, policy);
  const normalized = trades.map(t => ({ ...t, normalized: t.pnl / Math.max(model.target * policy.sizing.floorFraction, model.sigma(t.entry.slice(0, 10))) })).filter(t => Number.isFinite(t.normalized));
  const reference = normalized.filter(t => t.exit.slice(0, 10) <= policy.sizing.calibrationEnd).map(t => t.normalized);
  const observations = normalized.filter(t => t.exit.slice(0, 10) > policy.sizing.calibrationEnd);
  const last = observations.slice(-policy.sizing.monitorWindow).map(t => t.normalized);
  const shortfall = last.length === policy.sizing.monitorWindow ? (mean(reference) - mean(last)) / (sd(reference) / Math.sqrt(last.length)) : null;
  let consecutive = 0;
  for (let n = observations.length; n >= policy.sizing.monitorWindow; n--) {
    const sample = observations.slice(n - policy.sizing.monitorWindow, n).map(t => t.normalized);
    const score = (mean(reference) - mean(sample)) / (sd(reference) / Math.sqrt(sample.length));
    if (score < policy.sizing.monitorThreshold) break;
    consecutive++;
  }
  const modes = {};
  for (const mode of ["deterioration", "rolling", "streak", "drawdown"]) {
    try {
      const replay = replayGate(history.trades, { ...policy, mode }, end, history.daily, plan.reporting_start);
      modes[mode] = { state: replay.state, status: replay.status, last_transition: replay.events.at(-1) ?? null, transitions: replay.events.length };
    } catch (e) { modes[mode] = { state: "Unavailable", error: e.message }; }
  }
  const label = modes.deterioration.state === "Paused" ? "Pause / review" : modes.deterioration.state === "Unavailable" || last.length < policy.sizing.monitorWindow ? "Insufficient monitoring sample" : windows[20].net < 0 ? "Watch: recent losses" : "No deterioration flag";
  const thirtyDaysAgo = new Date(cutoff - 30 * 86400000).toISOString().slice(0, 10);
  rows.push({ id: item.id, name: item.name, symbol: item.symbol, timeframe: item.timeframe, label, coverage_end: end, last_mark: daily.at(-1)?.date, last_closed_trade: trades.at(-1)?.exit, recent_windows: windows, loss_streak: streak, last_30_calendar_days: { trades: trades.filter(t => t.exit.slice(0, 10) > thirtyDaysAgo).length, marked_pnl: sum(daily.filter(p => p.date > thirtyDaysAgo).map(p => p.pnl)) }, current_marked_drawdown: peak - pnl, current_marked_drawdown_pct: (peak - pnl) / (item.capital + peak), peak_date: peakDate, maximum_historical_marked_drawdown: maximumDrawdown, normalized_monitor: { calibration_trades: reference.length, post_calibration_trades: observations.length, reference_mean: mean(reference), recent_mean: mean(last), shortfall_score: shortfall, threshold: policy.sizing.monitorThreshold, consecutive_breaches: consecutive, confirmations_required: policy.sizing.monitorConfirm }, modes });
}
const result = { plan, rows };
writeFileSync(join(folder, "condition.json"), JSON.stringify(result, null, 2));
const fmt = v => v == null ? "n/a" : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
writeFileSync(join(folder, "findings.md"), [
  "# Latest recorded strategy condition", "", `Checked ${plan.checked_at}. Scope: the seven default working books, one copy each. Histories end ${items.map(i => i.end).sort()[0]}; this is not a live-market assessment.`, "",
  "Audit labels: Pause/review follows the existing 30-trade normalized deterioration rule (threshold 2, five consecutive confirmations, calibration through 2023-12-31). Otherwise Watch means the last 20 completed trades lost money; no flag means neither condition triggered. These descriptive labels do not predict the next trade. Current marked drawdown is measured from the all-history peak, not an intraday extreme.", "",
  "| Strategy | Status | Last 10 trades net | Last 20 trades net | Last 30 trades net | Current marked drawdown | Peak date | Last exit |",
  "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
  ...rows.map(r => `| ${r.name} / ${r.symbol} / ${r.timeframe} | ${r.label} | $${fmt(r.recent_windows[10].net)} | $${fmt(r.recent_windows[20].net)} | $${fmt(r.recent_windows[30].net)} | $${fmt(r.current_marked_drawdown)} | ${r.peak_date} | ${r.last_closed_trade} |`),
  "", "Raw dollar-loss rules and normalized deterioration answer different questions. Their exact states and last transitions, along with sample dates, loss streaks and monitor scores, are retained in condition.json. Thirty trades can span years for a slow strategy. Test-window terminal liquidations can contribute to the final trade, so those dates do not necessarily describe a natural strategy exit. No settings were changed.", "",
].join("\n"));
console.log(JSON.stringify({ folder, rows }, null, 2));
