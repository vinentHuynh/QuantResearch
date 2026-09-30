import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, resolve } from "node:path";
import { normalizedMarks, monitor, assessCondition, CONDITION_VERSION } from "../shared/ts/strategyCondition.ts";
import { calculatePortfolio, defaultPolicy } from "../shared/ts/portfolio.ts";
import { summarizeDaily } from "../shared/ts/riskSizing.ts";

const api = "http://127.0.0.1:8001/api/workbench/collective";
const get = async (url, body) => {
  const response = await fetch(url, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  if (!response.ok) throw Error(`${url}: ${response.status}`);
  return response.json();
};
const catalog = await get(api);
const items = catalog.items.filter(i => i.working && !i.benchmark);
const calibration = catalog.condition_calibration;
assert(calibration?.version === CONDITION_VERSION && calibration.validation.accepted, "Matching calibration required; do not refit to evaluation results");
const sources = await get(api + "/series", { ids: items.map(i => i.id) });
const root = resolve(process.env.WORKBENCH_HOME || "data/workbench", "collective");
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
const histories = items.map(i => {
  const bytes = readFileSync(join(root, i.series_file));
  assert.equal(hash(bytes), i.checksum);
  assert(calibration.sources.some(s => s.id === i.id && s.checksum === i.checksum));
  const history = JSON.parse(bytes);
  assert.deepEqual(history, sources.find(s => s.id === i.id));
  return history;
});
const folder = `reports/condition-viability-${new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-")}`;
mkdirSync(folder, { recursive: true });
const variants = [
  ...[1, .75, .5].map(size => ({ name: `Constant ${size*100}%`, trigger: null, normal: size, warning: size })),
  { name: "CUSUM pause", trigger: "cusum", normal: 1, warning: 0 },
  { name: "CUSUM half size", trigger: "cusum", normal: 1, warning: .5 },
  { name: "Recent-loss pause", trigger: "watch", normal: 1, warning: 0 },
  { name: "Recent-loss half size", trigger: "watch", normal: 1, warning: .5 },
];
const plan = {
  createdAt: new Date().toISOString(), start: "2024-01-01", end: "2026-08-31", variants,
  hypothesis: "Frozen condition warnings predict subsequent losses and improve entry filtering or sizing beyond simple reduced constant exposure.",
  evidence: "Previously inspected, selected historical books; development analysis, not a fresh holdout or live validation.",
  calibration, sources: items.map(i => ({ id: i.id, name: `${i.symbol} ${i.name} ${i.timeframe}`, checksum: i.checksum, series_file: i.series_file })),
  code: ["shared/ts/strategyCondition.ts", "shared/ts/portfolio.ts", "shared/ts/riskSizing.ts", "scripts/analyze-condition-viability.mjs"].map(path => ({ path, checksum: hash(readFileSync(path)) })),
  rules: {
    timing: "Use only marks and natural exits on UTC days strictly before entry day. Freeze size at entry; retain original exits. Extra-delay stress waits one additional calendar day.",
    monitor: "Continuous baseline/shadow outcomes regardless of skipped trades. CUSUM resets at independent source segments and requires 20 normalized observations in the active segment. Recent-loss trigger is last 10 natural trades < 0 OR last 20 marked observations < 0, with full windows required. Recovery returns size only on the next eligible entry.",
    accounting: "Closed-trade net P&L. Includes terminal accounting outcomes. Open/intraday drawdown is not reconstructed by entry reweighting. No strategy-state or brokerage execution rerun.",
    forecast: "At non-overlapping 20-observation anchors within each source segment, classify next 20 marked observations. No partial terminal horizons. Windows are still dependent across books and over time; counts are descriptive.",
    matched: "Constant multiplier equal to mean entry multiplier is an ex-post participation-matched diagnostic, not a deployable optimized size or a volatility match.",
    bootstrap: "Joint portfolio daily P&L differences; circular blocks 5/10/20 observed dates, 2000 resamples, seed 815731. Conditional historical uncertainty; does not remove selection bias.",
    viability: "Candidate must retain >=75% baseline net, reduce closed drawdown to <=75%, beat baseline recovery factor in >=2 of 3 year slices, and have a positive lower 95% bootstrap bound versus participation-matched constant sizing at all block lengths. Every variant is retained. Passing only warrants prospective study, not live use.",
  },
  stresses: ["double recorded costs with baseline warning decisions held fixed (friction stress, not a cost-aware state rerun)", "one extra calendar day of decision delay", "leave one book out", "round down to recorded whole contracts"],
};
writeFileSync(`${folder}/protocol.json`, JSON.stringify(plan, null, 2), { flag: "wx" });
const sum = a => a.reduce((s, x) => s+x, 0);
const mean = a => a.length ? sum(a)/a.length : null;
const dayBefore = (date, days = 1) => new Date(Date.parse(date+"T00:00:00Z")-days*86400000).toISOString().slice(0,10);
function timeline(history, ref) {
  const marks = [...history.daily].sort((a,b) => a.date.localeCompare(b.date));
  const natural = history.trades.filter(t => t.synthetic_exit === false).sort((a,b) => a.exit.localeCompare(b.exit));
  const normalized = normalizedMarks(history, ref, plan.end, calibration.lookback).filter(p => p.date > calibration.calibrationEnd);
  let exit = 0, point = 0;
  const recent = [], states = [];
  for (let n = 0; n < marks.length && marks[n].date <= plan.end; n++) {
    const mark = marks[n];
    while (exit < natural.length && natural[exit].exit.slice(0,10) <= mark.date) { recent.push(natural[exit++]); if (recent.length > 10) recent.shift(); }
    while (point < normalized.length && normalized[point].date <= mark.date) point++;
    if (mark.date < plan.start) continue;
    const current = monitor(normalized.slice(0, point), calibration.k, calibration.h, calibration.recoverySessions);
    const ready = current.segment === mark.segment && current.segmentCount >= 20;
    states.push({ date: mark.date, segment: mark.segment,
      watch: (recent.length === 10 && sum(recent.map(t => t.pnl)) < 0) || (n >= 19 && sum(marks.slice(n-19,n+1).map(d => d.pnl)) < 0),
      cusum: ready && current.alarm, ready, score: current.cusum, recovery: ready && current.recovery });
  }
  return states;
}
const timelines = histories.map((s,n) => timeline(s, calibration.books[items[n].id]));
function previousState(states, entry, delay = 0) {
  const cutoff = dayBefore(entry.slice(0,10), 1+delay);
  let low = 0, high = states.length;
  while (low < high) { const mid = (low+high) >>> 1; if (states[mid].date <= cutoff) low = mid+1; else high = mid; }
  return low ? states[low-1] : null;
}
const dates = [];
for (let n = Date.parse(plan.start+"T00:00:00Z"); n <= Date.parse(plan.end+"T00:00:00Z"); n += 86400000) dates.push(new Date(n).toISOString().slice(0,10));
const dateIndex = new Map(dates.map((d,n) => [d,n]));
const observed = new Set(histories.flatMap(s => s.daily.filter(d => d.date >= plan.start && d.date <= plan.end).map(d => d.date)));
const observedIndices = dates.map((d,n) => observed.has(d) ? n : -1).filter(n => n >= 0);
const baseline = calculatePortfolio(items, histories, Object.fromEntries(items.map(i => [i.id,1])), plan.start, plan.end, "closed", { ...defaultPolicy, enabled: false });
const years = ["2024", "2025", "2026"];
function evaluate(variant, options = {}) {
  const points = dates.map(() => 0), perBook = [], decisions = [];
  let weights = [], skippedProfit = 0, avoidedLoss = 0, missingCosts = 0, missingQuantities = 0;
  histories.forEach((history, b) => {
    if (options.omit === items[b].id) return;
    const bookPoints = dates.map(() => 0);
    let count = 0, warningCount = 0, zero = 0;
    history.trades.forEach(t => {
      const index = dateIndex.get(t.exit.slice(0,10));
      if (index === undefined) return;
      assert(t.entry.slice(0,10) >= plan.start, "Pre-period carry requires explicit equal initial exposure");
      const state = previousState(timelines[b], t.entry, options.delay || 0);
      assert(!state || state.date < t.entry.slice(0,10), "A decision must precede the entry day");
      const warning = !!(variant.trigger && state?.[variant.trigger] && (variant.trigger !== "cusum" || state.segment === t.segment));
      let weight = warning ? variant.warning : variant.normal;
      if (options.whole) {
        if (!(Number.isInteger(t.quantity) && t.quantity > 0)) missingQuantities++;
        else weight = Math.floor(t.quantity*weight)/t.quantity;
      }
      if (options.doubleCost && !Number.isFinite(t.cost)) missingCosts++;
      const pnl = t.pnl - (options.doubleCost ? t.cost || 0 : 0);
      const value = pnl * weight;
      points[index] += value; bookPoints[index] += value;
      weights.push(weight); count++; if (warning) warningCount++; if (!weight) zero++;
      skippedProfit += Math.max(0,pnl)*(1-weight); avoidedLoss += Math.max(0,-pnl)*(1-weight);
      decisions.push({ id: items[b].id, entry: t.entry, exit: t.exit, sourceDate: state?.date || null, warning, weight, pnl: value });
    });
    perBook.push({ id: items[b].id, name: plan.sources[b].name, ...summarizeDaily(bookPoints), trades: count, warningEntries: warningCount, skipped: zero });
  });
  return { name: variant.name, status: missingCosts || missingQuantities ? "Unavailable" : "Succeeded", missingCosts, missingQuantities,
    ...summarizeDaily(points), participation: mean(weights), trades: weights.length, accepted: weights.filter(w => w>0).length,
    avoidedLoss, skippedProfit, perBook, points, decisions,
    years: years.map(year => ({ year, ...summarizeDaily(points.filter((_,n) => dates[n].startsWith(year))) })) };
}
const results = variants.map(v => evaluate(v));
assert.deepEqual(results[0].points, baseline.points.map(p => p.pnl), "Replay baseline must reconcile day-for-day with the app");
assert.equal(results[1].net, baseline.net * .75);
assert.equal(results[2].net, baseline.net * .5);
assert(baseline.points.every(p => p.pnl === 0 || observed.has(p.date)), "Bootstrap calendar must include every realized P&L date");
for (const trigger of ["watch", "cusum"]) {
  const manual = Object.fromEntries(items.map((item,b) => {
    let previous = false;
    const schedule = [];
    for (const state of timelines[b]) {
      if (state[trigger] === previous) continue;
      previous = state[trigger];
      schedule.push({ timestamp: new Date(Date.parse(state.date+"T00:00:00Z")+86400000).toISOString(), action: previous ? "pause" : "resume", reason: "Frozen prior-day condition analysis" });
    }
    return [item.id, schedule];
  }));
  const replay = calculatePortfolio(items, histories, Object.fromEntries(items.map(i => [i.id,1])), plan.start, plan.end, "closed", { ...defaultPolicy, enabled: true, mode: "manual", manual });
  const pause = results.find(r => r.name === (trigger === "watch" ? "Recent-loss pause" : "CUSUM pause"));
  const half = results.find(r => r.name === (trigger === "watch" ? "Recent-loss half size" : "CUSUM half size"));
  assert.deepEqual(pause.points, replay.points.map(p => p.pnl), "Independent app manual replay must reproduce daily filtered P&L");
  assert.deepEqual(half.points, pause.points.map((p,n) => (p+results[0].points[n])/2), "Half-size path must reconcile with accepted and shadow books");
}
// Independently check status parity and future-prefix invariance at declared cutoffs.
for (let b = 0; b < histories.length; b++) {
  for (const cutoff of ["2024-06-28", "2025-06-30", "2026-08-31"]) {
    const prefix = { ...histories[b], daily: histories[b].daily.filter(d => d.date <= cutoff), trades: histories[b].trades.filter(t => t.exit.slice(0,10) <= cutoff) };
    assert.deepEqual(timeline(prefix, calibration.books[items[b].id]), timelines[b].filter(s => s.date <= cutoff));
    const state = timelines[b].filter(s => s.date <= cutoff).at(-1);
    const app = assessCondition(items[b], histories[b], state.date, calibration);
    assert.equal(state.cusum, !!(app.calibrated && app.detector.alarm));
    assert.equal(state.watch, (app.last10.count === 10 && app.last10.pnl < 0) || (app.last20.count === 20 && app.last20.pnl < 0));
  }
}
const rng = seed => () => { seed = (Math.imul(seed,1664525)+1013904223) >>> 0; return seed/4294967296; };
const quantile = (a,q) => [...a].sort((a,b) => a-b)[Math.floor((a.length-1)*q)];
function bootstrapDelta(values) {
  return [5,10,20].map(block => {
    const random = rng(815731+block), samples = [];
    for (let path = 0; path < 2000; path++) {
      let total = 0, index = 0;
      for (let n = 0; n < values.length; n++) { if (n % block === 0) index = Math.floor(random()*values.length); total += values[index++ % values.length]; }
      samples.push(total);
    }
    return { block, lower: quantile(samples,.025), upper: quantile(samples,.975), positiveFraction: samples.filter(x => x>0).length/samples.length };
  });
}
for (const result of results.filter(r => variants.find(v => v.name === r.name).trigger)) {
  result.matchedConstant = summarizeDaily(results[0].points.map(v => v*result.participation));
  result.matchedDelta = result.net-result.matchedConstant.net;
  result.bootstrap = bootstrapDelta(observedIndices.map(n => result.points[n]-results[0].points[n]*result.participation));
  result.yearRecoveryWins = result.years.filter((y,n) => y.recovery !== null && y.recovery > results[0].years[n].recovery).length;
  result.criteria = {
    retain75PercentNet: result.net >= .75*results[0].net,
    reduceDrawdown25Percent: result.drawdown <= .75*results[0].drawdown,
    twoOfThreeYearRecovery: result.yearRecoveryWins >= 2,
    positiveMatchedLowerBound: result.bootstrap.every(r => r.lower > 0),
  };
  result.viableForProspectiveStudy = Object.values(result.criteria).every(Boolean);
}
const forecastRows = [];
histories.forEach((history,b) => {
  for (const segment of history.coverage.filter(c => c.end >= plan.start && c.start <= plan.end)) {
    const marks = history.daily.filter(d => d.date >= (segment.start > plan.start ? segment.start : plan.start) && d.date <= (segment.end < plan.end ? segment.end : plan.end));
    for (let n = 19; n+20 < marks.length; n += 20) {
      const state = timelines[b].find(s => s.date === marks[n].date);
      const future = marks.slice(n+1,n+21);
      forecastRows.push({ id: items[b].id, name: plan.sources[b].name, date: state.date, end: future.at(-1).date,
        watch: state.watch, cusum: state.cusum, ready: state.ready, pnl: sum(future.map(d => d.pnl)) });
    }
  }
});
const describe = rows => ({ windows: rows.length, losses: rows.filter(r => r.pnl<0).length, lossRate: rows.length ? rows.filter(r => r.pnl<0).length/rows.length : null, meanPnl: mean(rows.map(r => r.pnl)), net: sum(rows.map(r => r.pnl)) });
const forecasts = ["watch", "cusum"].map(trigger => {
  const eligible = forecastRows.filter(r => trigger !== "cusum" || r.ready);
  return { trigger, warning: describe(eligible.filter(r => r[trigger])), clear: describe(eligible.filter(r => !r[trigger])),
    perBook: items.map(i => ({ id: i.id, warning: describe(eligible.filter(r => r.id === i.id && r[trigger])), clear: describe(eligible.filter(r => r.id === i.id && !r[trigger])) })) };
});
const events = timelines.map((states,b) => ({ id: items[b].id, name: plan.sources[b].name,
  maximumCusum: Math.max(...states.filter(s => s.ready).map(s => s.score)), threshold: calibration.h,
  monitoredDays: states.filter(s => s.ready).length, cusumDays: states.filter(s => s.cusum).length, watchDays: states.filter(s => s.watch).length,
  cusumEpisodes: states.filter((s,n) => s.cusum && !states[n-1]?.cusum).map(s => s.date),
  watchEpisodes: states.filter((s,n) => s.watch && !states[n-1]?.watch).map(s => s.date) }));
const compact = ({ points, decisions, ...rest }) => rest;
const stress = {
  doubleCost: variants.map(v => compact(evaluate(v,{ doubleCost: true }))),
  extraDayDelay: variants.map(v => compact(evaluate(v,{ delay: 1 }))),
  wholeContracts: variants.map(v => compact(evaluate(v,{ whole: true }))),
  leaveOneOut: items.map(i => ({ omitted: i.id, name: plan.sources.find(s => s.id === i.id).name, results: variants.map(v => compact(evaluate(v,{ omit: i.id }))) })),
};
const report = { plan, results: results.map(compact), forecasts, forecastRows, events, stress,
  checks: ["API and immutable-file checksum agreement", "day-for-day baseline reconciliation", "constant-size reconciliation", "independent app manual-pause replay reconciliation", "half-size reconciliation", "bootstrap calendar completeness", "strict prior-day entry decisions", "three historical cutoffs prefix invariant per book", "app condition parity"],
  coverage: { marketDataThrough: catalog.market_data_through, simulationThrough: items.map(i => ({ id: i.id, end: i.end })) } };
writeFileSync(`${folder}/results.json`, JSON.stringify(report,null,2));
writeFileSync(`${folder}/decisions.json`, JSON.stringify(results.map(r => ({ name: r.name, decisions: r.decisions })),null,2));
writeFileSync(`${folder}/daily.csv`, ["date,"+results.map(r => r.name).join(","), ...dates.map((d,n) => [d,...results.map(r => r.points[n])].join(","))].join("\n"));
const cash = x => x.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const percent = x => x === null ? "n/a" : `${(100*x).toFixed(1)}%`;
const dominatedOmissions = stress.leaveOneOut.filter(s => {
  const half = s.results.find(r => r.name === "Recent-loss half size"), fixed = s.results.find(r => r.name === "Constant 75%");
  return half.net < fixed.net && half.drawdown > fixed.drawdown;
}).length;
const lines = ["# Condition-system viability analysis", "", plan.evidence, "",
  "**Conclusion: useful for describing recent losses, but automatic pause/sizing viability is not established.** Recent-loss controls underperformed simple sizing; the frozen CUSUM produced no warnings, leaving its real-warning usefulness untested. No automatic policy is promoted.", "",
  `Seven current working books, one copy each; ${plan.start} to ${plan.end}. Existing calibration and thresholds were frozen. All outcomes below use the same closed-trade accounting, including recorded fees and terminal closes.`, "",
  "| Rule | Net P&L | Max closed drawdown | Recovery factor | Mean entry multiplier |",
  "| --- | ---: | ---: | ---: | ---: |",
  ...results.map(r => `| ${r.name} | ${cash(r.net)} | ${cash(r.drawdown)} | ${r.recovery?.toFixed(2) ?? "n/a"} | ${r.participation.toFixed(3)} |`), "",
  "## Does a warning predict the next losing window?", "",
  "Non-overlapping forward windows contain the next 20 observed marked days within the same source segment. Counts remain dependent across correlated books. These are descriptive associations, not a claim of statistical significance.", "",
  "| Warning | Warning windows | Losing after warning | Clear windows | Losing after clear |",
  "| --- | ---: | ---: | ---: | ---: |",
  ...forecasts.map(r => `| ${r.trigger} | ${r.warning.windows} | ${percent(r.warning.lossRate)} | ${r.clear.windows} | ${percent(r.clear.lossRate)} |`), "",
  `CUSUM raised ${events.reduce((n,e) => n+e.cusumEpisodes.length,0)} episodes across the seven books. Maximum supported CUSUM score was ${Math.max(...events.map(e => e.maximumCusum)).toFixed(2)} versus the frozen ${calibration.h.toFixed(2)} threshold. No alarms does not establish successful loss-stage detection. These books were selected using later performance, which limits conclusions about detecting failing strategies.`, "",
  "## Added value beyond smaller constant sizing", "",
  "The participation match is an ex-post diagnostic, not a volatility match. Bootstrap intervals use synchronized portfolio differences and preserve local dependence; they do not remove selection bias or prove future performance.", "",
  ...results.filter(r => r.criteria).flatMap(r => [
    `- **${r.name}:** ${cash(r.matchedDelta)} versus participation-matched constant sizing; 95% interval envelope ${cash(Math.min(...r.bootstrap.map(b => b.lower)))} to ${cash(Math.max(...r.bootstrap.map(b => b.upper)))}. Recovery factor improved in ${r.yearRecoveryWins}/3 year slices. ${r.viableForProspectiveStudy ? "Passed" : "Failed"} the declared combined development criteria.`,
    `  Avoided loss: ${cash(r.avoidedLoss)}; forgone profit: ${cash(r.skippedProfit)}. Criteria: ${JSON.stringify(r.criteria)}.`,
  ]), "",
  "## Robustness and implementation limits", "",
  `Recent-loss half sizing earned less and had more closed drawdown than constant 75% sizing in ${dominatedOmissions}/7 leave-one-book-out portfolios. Cost stress below holds baseline warning decisions fixed; it is a friction sensitivity, not a stateful cost-aware rerun.`, "",
  ...stress.doubleCost.map(r => `- Double recorded costs, ${r.name}: ${r.status === "Succeeded" ? `${cash(r.net)} net / ${cash(r.drawdown)} closed drawdown` : "Unavailable: missing costs"}.`), "",
  ...stress.extraDayDelay.filter(r => variants.find(v => v.name === r.name).trigger).map(r => `- Extra day delay, ${r.name}: ${cash(r.net)} net / ${cash(r.drawdown)} closed drawdown.`), "",
  ...stress.wholeContracts.map(r => `- Whole contracts, ${r.name}: ${r.status === "Succeeded" ? `${cash(r.net)} net; ${r.accepted}/${r.trades} accepted trades` : "Unavailable: missing quantities"}.`), "",
  "Year slices, per-book contributions, every leave-one-out result, exact entries, P&L paths, and all failed criteria are retained in results.json, decisions.json and daily.csv. No threshold was optimized against these outcomes. Paused books continue shadow monitoring; existing positions retain their original exits, so warnings cannot protect losses already embedded in an open position.", "",
  `Prior synthetic calibration had a ${(calibration.validation.worstRate*100).toFixed(1)}% worst baseline alarm rate over 252 observations, but ${(calibration.validation.residualVolatilityAlarmRate*100).toFixed(1)}% under doubled standardized-residual volatility. This substantial sensitivity prevents interpreting a warning as proof that the strategy lost its edge.`, "",
  "Fractional exposure, proportional costs, fixed strategy state, contract rolls, shared margin and intraday open losses remain unresolved. Closed drawdown can understate open-position risk. Prospective validation and a stateful marked-equity execution test are required before considering automatic use. Replay ends August 31, 2026; this does not establish current September condition.", "",
  "Verification: " + report.checks.join("; ") + ".", "",
];
writeFileSync(`${folder}/findings.md`, lines.join("\n"));
console.log(JSON.stringify({ folder, results: results.map(r => ({ name: r.name, net: r.net, drawdown: r.drawdown, recovery: r.recovery, criteria: r.criteria })), forecasts: forecasts.map(({ perBook, ...r }) => r), cusumEpisodes: events.reduce((n,e) => n+e.cusumEpisodes.length,0), dominatedOmissions, checks: report.checks },null,2));
