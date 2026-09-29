import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname, basename } from "node:path";
import { createHash } from "node:crypto";
import {
  calculatePortfolio,
  defaultPolicy,
  replayGate,
  calendarDates,
  commonWindow,
  PortfolioCoverageError,
  tradeDependence,
} from "../src/collectiveModel.ts";
import { createCollective } from "../server/collective.ts";

const item = (id) => ({
  id,
  name: id,
  symbol: id === "a" ? "NQ" : "ES",
  capital: 1000,
  start: "2026-01-01",
  end: "2026-01-10",
  coverage: [{ start: "2026-01-01", end: "2026-01-10" }],
});
const trade = (day, pnl, entryDay = day) => ({
  entry: `2026-01-${String(entryDay).padStart(2, "0")}T10:00:00Z`,
  exit: `2026-01-${String(day).padStart(2, "0")}T12:00:00Z`,
  pnl,
});
const series = (id, daily, trades) => ({
  id,
  daily: daily.map(([date, pnl]) => ({ date, pnl })),
  trades,
  coverage: item(id).coverage,
});
const a = series(
  "a",
  [
    ["2026-01-01", 100],
    ["2026-01-02", -50],
    ["2026-01-03", 70],
  ],
  [trade(1, 100), trade(2, -50), trade(3, 70)],
);
const b = series(
  "b",
  [
    ["2026-01-01", -30],
    ["2026-01-02", 80],
  ],
  [trade(1, -30), trade(2, 80)],
);
const base = calculatePortfolio(
  [item("a"), item("b")],
  [a, b],
  { a: 1, b: 2 },
  "2026-01-01",
  "2026-01-10",
  "marked",
  defaultPolicy,
);
assert.equal(base.capital, 100000);
assert.equal(base.net, 220);
assert.equal(base.points[0].pnl, 40);
assert.equal(base.points[1].pnl, 110);
assert.equal(
  base.points.reduce((n, p) => n + p.pnl, 0),
  base.net,
);
assert.equal(
  base.components.reduce((n, c) => n + c.pnl, 0),
  base.net,
);
assert.equal(base.points.at(-1).equity, base.capital + base.net);
assert.equal(base.components.find(c => c.id === "a").maxDrawdownDollars, 50);
assert.equal(base.components.find(c => c.id === "b").maxDrawdownDollars, 60);
assert.equal(base.maxDrawdownDollars, 0, "Opposing strategies can offset each other's individual drawdowns");
const cropped = calculatePortfolio([item("a")], [a], { a: 1 },
  "2026-01-03", "2026-01-10", "marked", defaultPolicy);
assert.equal(cropped.components[0].maxDrawdownDollars, 0, "Only the selected window contributes to drawdown");
// The account balance is shared, independent of recorded sleeve capital/copies.
const shared = calculatePortfolio([item("a"), { ...item("b"), capital: 900000 }],
  [a, b], { a: 1, b: 2 }, "2026-01-01", "2026-01-10", "marked", defaultPolicy, 2000);
assert.equal(shared.capital, 2000);
assert.equal(shared.net, base.net);
assert.equal(shared.returnOnCapital, 220 / 2000);
assert.equal(shared.points.at(-1).equity, 2220);
assert.equal(shared.components.reduce((n, c) => n + c.pnl / shared.capital, 0), shared.returnOnCapital);
for (const basis of ["marked", "closed"]) {
  const small = calculatePortfolio([item("a")], [a], { a: 1 }, "2026-01-01", "2026-01-10", basis, defaultPolicy, 1000);
  const large = calculatePortfolio([item("a")], [a], { a: 1 }, "2026-01-01", "2026-01-10", basis, defaultPolicy, 2000);
  assert.equal(small.net, large.net);
  assert.equal(small.maxDrawdownDollars, 50);
  assert.equal(small.components[0].maxDrawdownDollars, 50);
  assert.equal(large.maxDrawdownDollars, 50);
  assert.ok(Math.abs(small.maxDrawdown + 50 / 1100) < 1e-12);
  assert.ok(Math.abs(large.maxDrawdown + 50 / 2100) < 1e-12);
  assert.equal(small.returnOnCapital, 2 * large.returnOnCapital);
  const doubled = calculatePortfolio([item("a")], [a], { a: 2 }, "2026-01-01", "2026-01-10", basis, defaultPolicy, 1000);
  assert.equal(doubled.capital, small.capital);
  assert.equal(doubled.net, 2 * small.net);
  assert.equal(doubled.components[0].maxDrawdownDollars, 100);
}
for (const invalid of [0, -1, NaN, Infinity, -Infinity]) {
  assert.throws(() => calculatePortfolio([item("a")], [a], { a: 1 },
    "2026-01-01", "2026-01-10", "marked", defaultPolicy, invalid), /capital must be a positive finite amount/);
}
const depleted = calculatePortfolio([item("a")], [series("a", [["2026-01-01", -200]], [trade(1, -200)])],
  { a: 1 }, "2026-01-01", "2026-01-10", "marked", defaultPolicy, 100);
assert.equal(depleted.depleted, true);
assert.equal(depleted.points[0].equity, -100);
assert.equal(depleted.maxDrawdown, -2);
assert.equal(
  base.points.reduce(
    (n, p) => n + Object.values(p.bySymbol).reduce((a, b) => a + b, 0),
    0,
  ),
  base.net,
);
assert.equal(base.points[5].pnl, 0);
assert.equal(base.points[5].trades, 0);
assert.throws(
  () =>
    calculatePortfolio(
      [item("a")],
      [a],
      { a: 1 },
      "2025-12-31",
      "2026-01-10",
      "marked",
      defaultPolicy,
    ),
  /not covered/,
);
assert.throws(
  () =>
    calculatePortfolio(
      [item("a")],
      [a],
      { a: 0.5 },
      "2026-01-01",
      "2026-01-10",
      "marked",
      defaultPolicy,
    ),
  /whole numbers/,
);
assert.throws(
  () =>
    calculatePortfolio(
      [item("a")],
      [],
      { a: 1 },
      "2026-01-01",
      "2026-01-10",
      "marked",
      defaultPolicy,
    ),
  /Loading/,
);
assert.throws(
  () =>
    calculatePortfolio(
      [],
      [],
      {},
      "2026-01-01",
      "2026-01-10",
      "marked",
      defaultPolicy,
    ),
  /at least one/,
);
assert.throws(
  () =>
    calculatePortfolio(
      [item("a")],
      [a],
      { a: 1 },
      "2026-01-01",
      "2026-01-10",
      "marked",
      { ...defaultPolicy, enabled: true },
    ),
  /closed-trade/,
);
assert.equal(calendarDates("2024-02-28", "2024-03-01").length, 3);
const bad = {
  ...a,
  coverage: [
    { start: "2026-01-01", end: "2026-01-02" },
    { start: "2026-01-04", end: "2026-01-10" },
  ],
};
assert.deepEqual(commonWindow([]), { start: "", end: "" });
assert.deepEqual(commonWindow([item("a"), item("b")]), {
  start: "2026-01-01", end: "2026-01-10",
});
assert.deepEqual(commonWindow([item("a"), bad]), {
  start: "2026-01-04", end: "2026-01-10",
});
const repaired = commonWindow([item("a"), bad]);
assert.doesNotThrow(() => calculatePortfolio(
  [item("a")], [bad], { a: 1 }, repaired.start, repaired.end, "marked", defaultPolicy,
));
assert.deepEqual(commonWindow([{ coverage: [
  { start: "2026-01-05", end: "2026-01-10" },
  { start: "2026-01-01", end: "2026-01-04" },
  { start: "2026-01-02", end: "2026-01-03" },
] }, item("a")]), { start: "2026-01-01", end: "2026-01-10" });
assert.deepEqual(commonWindow([item("a"), { coverage: [
  { start: "2026-02-01", end: "2026-02-10" },
] }]), { start: "", end: "" });
assert.deepEqual(commonWindow([{ coverage: [
  { start: "2026-01-01", end: "2026-01-02" },
  { start: "2026-01-04", end: "2026-01-05" },
] }]), { start: "2026-01-04", end: "2026-01-05" });
assert.deepEqual(commonWindow([item("a"), { coverage: [] }]), { start: "", end: "" });
assert.throws(() => calculatePortfolio(
  [item("a")], [bad], { a: 1 }, "2026-01-01", "2026-01-10", "marked", defaultPolicy,
), (error) => error instanceof PortfolioCoverageError && /tested: 2026-01-01 to 2026-01-02; 2026-01-04 to 2026-01-10/.test(error.message));
assert.throws(
  () =>
    calculatePortfolio(
      [item("a")],
      [bad],
      { a: 1 },
      "2026-01-01",
      "2026-01-10",
      "marked",
      defaultPolicy,
    ),
  /not covered/,
);

const policy = {
  ...defaultPolicy,
  enabled: true,
  mode: "streak",
  streak: 2,
  cooldown: 1,
  recovery: 2,
};
const trades = [
  trade(1, -10),
  trade(2, -20),
  trade(3, 30),
  trade(4, 40),
  trade(5, 50),
];
const gate = replayGate(trades, policy, "2026-01-05");
assert.deepEqual([...gate.accepted], [0, 1, 4]);
assert.equal(gate.events[0].state, "Paused");
assert.equal(gate.events[1].state, "Active");
assert.equal(gate.state, "Active");
const gseries = series("a", [], trades);
const filtered = calculatePortfolio(
  [item("a")],
  [gseries],
  { a: 1 },
  "2026-01-01",
  "2026-01-05",
  "closed",
  policy,
);
assert.equal(filtered.net, 20);
assert.equal(filtered.baseline, 90);
assert.equal(filtered.components[0].skipped, 2);
assert.equal(filtered.components[0].maxDrawdownDollars, filtered.maxDrawdownDollars,
  "A single strategy's drawdown follows its pause-filtered P&L");
const future = replayGate(
  [...trades, trade(6, -99999), trade(7, -99999)],
  policy,
  "2026-01-05",
);
assert.deepEqual(future, gate);
// A still-open loss cannot disable a new entry; accepted open positions keep their exits.
const overlap = [trade(4, -500, 1), trade(2, 10), trade(3, 20), trade(5, 100)];
const sameTime = {
  entry: "2026-01-04T12:00:00Z",
  exit: "2026-01-04T13:00:00Z",
  pnl: 5,
};
const causal = replayGate(
  [...overlap, sameTime],
  { ...policy, streak: 1 },
  "2026-01-05",
);
assert(causal.accepted.has(1));
assert(causal.accepted.has(2));
assert(causal.accepted.has(4));
assert(!causal.accepted.has(3));
assert.equal(
  calculatePortfolio(
    [item("a")],
    [series("a", [], [trade(4, 123, 1)])],
    { a: 1 },
    "2026-01-03",
    "2026-01-05",
    "closed",
    defaultPolicy,
  ).net,
  123,
);
const rolling = replayGate(
  trades,
  { ...policy, mode: "rolling", lookback: 2, lossLimit: 0 },
  "2026-01-05",
);
assert.equal(rolling.events[0].timestamp, trades[1].exit);
const drawdown = replayGate(
  trades,
  { ...policy, mode: "drawdown", drawdown: 25 },
  "2026-01-05",
);
assert.equal(drawdown.events[0].timestamp, trades[1].exit);
// Recovery excludes the trigger and positions opened before the pause.
const recoveryPolicy = { ...policy, streak: 1, recovery: 2 };
const oldWinner = [trade(1, -10), trade(2, 100, 1), trade(3, 20), trade(4, 30), trade(5, 40)];
const recovered = replayGate(oldWinner, recoveryPolicy, "2026-01-05");
assert.deepEqual([...recovered.accepted], [0, 1, 4]);
assert.equal(Date.parse(recovered.events[1].timestamp), Date.parse(oldWinner[3].exit));
const waiting = replayGate(oldWinner, recoveryPolicy, "2026-01-03");
assert.equal(waiting.status.recoveryTrades, 1);
assert.equal(waiting.status.recoveryPnl, 20);
assert.equal(waiting.state, "Paused");
// Recovery completed during cooldown must permit the first later entry,
// even if no trade exits at or after cooldown expiry.
const cooldown = replayGate([trade(1, -10), trade(2, 10), trade(3, 20), trade(8, 30)],
  { ...recoveryPolicy, cooldown: 5 }, "2026-01-08");
assert(cooldown.accepted.has(3));
const expiryLoss = replayGate([trade(1, -10), trade(2, 100), trade(5, -10), trade(6, 20)],
  { ...policy, streak: 1, recovery: 1, cooldown: 2 }, "2026-01-06");
assert.equal(expiryLoss.events[1].timestamp, "2026-01-03T12:00:00.000Z");
assert.equal(expiryLoss.events[2].state, "Paused");
assert(!expiryLoss.accepted.has(3));
const manualPolicy = { ...policy, mode: "manual" };
const schedule = [
  { timestamp: "2026-01-02T10:00:00Z", action: "pause", reason: "Review exposure" },
  { timestamp: "2026-01-04T10:00:00Z", action: "resume", reason: "Review complete" },
];
const manualGate = replayGate(trades, manualPolicy, "2026-01-05", [], "", schedule);
assert.deepEqual([...manualGate.accepted], [0, 3, 4]);
assert.equal(manualGate.events.length, 2);
assert.equal(replayGate(trades, manualPolicy, "2026-01-03", [], "", schedule).state, "Paused");
assert.deepEqual(replayGate([...trades, trade(9, -999)], manualPolicy, "2026-01-05", [], "", schedule), manualGate);
assert.equal(replayGate(trades, { ...manualPolicy, enabled: false }, "2026-01-05", [], "", schedule).accepted.size, 5);
assert.equal(replayGate([trade(4, 100, 1)], manualPolicy, "2026-01-05", [], "", schedule).accepted.size, 1);
assert.throws(() => replayGate(trades, manualPolicy, "2026-01-05", [], "", [...schedule, schedule[0]]), /one manual/);
assert.throws(() => replayGate(trades, { ...policy, cooldown: NaN }, "2026-01-05"), /whole number/);
const perBook = calculatePortfolio([item("a"), item("b")], [series("a", [], trades), series("b", [], trades)],
  { a: 1, b: 2 }, "2026-01-01", "2026-01-05", "closed", { ...manualPolicy, manual: { a: schedule } });
assert.equal(perBook.components.find(c => c.id === "a").pnl, 80);
assert.equal(perBook.components.find(c => c.id === "b").pnl, 180);
// Verified history access is allowlisted; corruption and duplicate sleeves fail closed.
const folder = mkdtempSync(join(tmpdir(), "collective-test-"));
try {
  mkdirSync(join(folder, "collective"));
  const filename = "a".repeat(20) + "-" + "b".repeat(16) + ".json";
  const bytes = JSON.stringify(a);
  const checksum = createHash("sha256").update(bytes).digest("hex");
  writeFileSync(join(folder, "collective", filename), bytes);
  writeFileSync(
    join(folder, "collective", "index.json"),
    JSON.stringify({ items: [{ id: "a", series_file: filename, checksum }] }),
  );
  const api = createCollective(".", folder, "python");
  assert.deepEqual(api.series(["a"]), [a]);
  assert.throws(() => api.series(["a", "a"]), /unique/);
  assert.throws(() => api.series(["../secret"]), /Unknown/);
  writeFileSync(join(folder, "collective", filename), bytes + " ");
  assert.throws(() => api.series(["a"]), /changed/);
} finally {
  assert.equal(dirname(resolve(folder)), resolve(tmpdir()));
  assert(basename(folder).startsWith("collective-test-"));
  rmSync(folder, { recursive: true, force: true });
}
// Loss-clustering diagnostic: streaks, alternation, window fallback, small samples.
const iso = (y, m, d, h = 0) => new Date(Date.UTC(y, m - 1, d, h)).toISOString();
const seq = (pnls) =>
  pnls.map((pnl, i) => ({ entry: iso(2025, 1, 1 + i, 9), exit: iso(2025, 1, 1 + i, 15), pnl }));
const streaky = seq(Array.from({ length: 40 }, (_, i) => (i % 10 < 5 ? 1 : -1)));
const alternating = seq(Array.from({ length: 40 }, (_, i) => (i % 2 ? -1 : 1)));
const clustered = tradeDependence(streaky, "2026-01-01", "2026-12-31");
assert.equal(clustered.verdict, "cluster");
assert.equal(clustered.trades, 40);
assert.equal(clustered.prior, true);
assert(clustered.runsZ < -1.96 && clustered.autocorrelation > 0.5);
const alternate = tradeDependence(alternating, "2026-01-01", "2026-12-31");
assert.equal(alternate.verdict, "alternate");
assert(alternate.runsZ > 1.96 && alternate.autocorrelation < -0.5);
assert.equal(alternate.afterLoss, 1);
assert.equal(alternate.afterWin, -1);
const inWindow = tradeDependence(alternating, "2025-01-01", "2025-12-31");
assert.equal(inWindow.prior, false);
assert.equal(inWindow.trades, 40);
assert.equal(tradeDependence(streaky.slice(0, 10), "2026-01-01", "2026-12-31").verdict, "insufficient");
const random = tradeDependence(seq([3, -1, 2, -2, -1, 4, 1, -3, 2, 1, -2, 3, -1, -1, 2, 1, -2, 1, 3, -1, -2, 2, 1, -1, -3, 2, 1, -1, 2, -2, 1, 1]), "2026-01-01", "2026-12-31");
assert.equal(random.verdict, "none");

// Volatility scaling: sigma from marks strictly before entry, target from entries before the window, capped, causal.
const marks = [];
for (let i = 0; i < 40; i++) marks.push({ date: iso(2025, 11, 1 + i).slice(0, 10), pnl: i % 2 ? -10 : 10 });
const volTrades = [];
for (let i = 0; i < 12; i++) volTrades.push({ entry: iso(2025, 12, 11 + i, 9), exit: iso(2025, 12, 11 + i, 15), pnl: 5 });
for (let i = 0; i < 14; i++) marks.push({ date: iso(2025, 12, 23 + i).slice(0, 10), pnl: i % 2 ? -40 : 40 });
volTrades.push({ entry: iso(2026, 1, 6, 9), exit: iso(2026, 1, 6, 15), pnl: 100 });
volTrades.push({ entry: iso(2026, 1, 7, 9), exit: iso(2026, 1, 7, 15), pnl: -50 });
const volPolicy = { ...defaultPolicy, enabled: true, mode: "volatility" };
const vol = replayGate(volTrades, volPolicy, "2026-01-10", marks, "2026-01-01");
const stdev = (xs) => {
  const m = xs.reduce((a, b) => a + b, 0) / xs.length;
  return Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1));
};
const before = (date) => marks.filter((p) => p.date < date).map((p) => p.pnl).slice(-25);
const target = stdev(before("2025-12-11"));
for (let i = 0; i < 12; i++) assert(Math.abs(vol.weights.get(i) - 1) < 1e-9);
assert(Math.abs(vol.weights.get(12) - target / stdev(before("2026-01-06"))) < 1e-9);
assert(vol.weights.get(12) < 0.5 && vol.weights.get(13) < 0.5);
assert.equal(vol.accepted.size, 14);
assert.equal(vol.state, "Reduced");
assert.deepEqual(vol.events.map((e) => [e.state, e.timestamp]), [["Reduced", volTrades[12].entry]]);
const later = replayGate(
  [...volTrades, { entry: iso(2026, 1, 9, 9), exit: iso(2026, 1, 9, 15), pnl: -9999 }],
  volPolicy,
  "2026-01-10",
  [...marks, { date: "2026-01-08", pnl: -5000 }],
  "2026-01-01",
);
for (let i = 0; i < 14; i++) assert.equal(later.weights.get(i), vol.weights.get(i));
assert.equal(replayGate(volTrades, { ...volPolicy, volCap: 0.25 }, "2026-01-10", marks, "2026-01-01").weights.get(0), 0.25);
const unsized = replayGate(volTrades, volPolicy, "2026-01-10", marks, "2025-12-01");
assert(volTrades.every((_, i) => unsized.weights.get(i) === 1));
assert.match(unsized.events[0].reason, /Fewer than 10/);
const volSeries = { id: "a", daily: marks, trades: volTrades, coverage: item("a").coverage };
const scaled = calculatePortfolio([item("a")], [volSeries], { a: 1 }, "2026-01-01", "2026-01-10", "closed", volPolicy);
assert(Math.abs(scaled.net - (100 * vol.weights.get(12) - 50 * vol.weights.get(13))) < 1e-9);
assert.equal(scaled.baseline, 50);
assert.equal(scaled.components[0].trades, 2);
assert.equal(scaled.components[0].skipped, 0);
assert.equal(scaled.components[0].state, "Reduced");
assert(Math.abs(scaled.exposure - (vol.weights.get(12) + vol.weights.get(13)) / 2) < 1e-9);
assert.equal(scaled.events.length, 1);
assert.equal(scaled.dependence[0].verdict, "insufficient");
assert.throws(
  () => calculatePortfolio([item("a")], [volSeries], { a: 1 }, "2026-01-01", "2026-01-10", "marked", volPolicy),
  /closed-trade/,
);

console.log(
  "Collective checks passed: aggregation, capital/copies, coverage gaps, leap dates, prior-only gates, shadow recovery, open trades, prefix invariance, loss-clustering diagnostic, causal volatility scaling, and verified history access.",
);

if (process.argv.includes("--real")) {
  const root = process.cwd(),
    api = createCollective(root, join(root, "data/workbench"), "python"),
    catalog = api.catalog();
  assert(catalog.items.length >= 312, 'Preserve the original campaign configurations');
  assert.equal(catalog.errors.length, 0);
  const working = catalog.items.filter((i) => i.working),
    histories = api.series(working.map((i) => i.id)),
    copies = Object.fromEntries(working.map((i) => [i.id, 1]));
  const result = calculatePortfolio(
    working,
    histories,
    copies,
    "2024-01-01",
    "2026-08-31",
    "marked",
    defaultPolicy,
  );
  const expectedMarked = histories.reduce((total, history) =>
    total + history.daily.filter((point) => point.date >= "2024-01-01" && point.date <= "2026-08-31")
      .reduce((sum, point) => sum + point.pnl, 0), 0);
  assert(Math.abs(result.net - expectedMarked) < 0.01);
  const closed = calculatePortfolio(
    working,
    histories,
    copies,
    "2024-01-01",
    "2026-08-31",
    "closed",
    defaultPolicy,
  );
  const expectedClosed = histories.reduce((total, history) =>
    total + history.trades.filter((trade) => trade.exit.slice(0, 10) >= "2024-01-01" && trade.exit.slice(0, 10) <= "2026-08-31")
      .reduce((sum, trade) => sum + trade.pnl, 0), 0);
  assert(Math.abs(closed.net - expectedClosed) < 0.01);
  const gated = calculatePortfolio(
    working,
    histories,
    copies,
    "2024-01-01",
    "2026-08-31",
    "closed",
    { ...defaultPolicy, enabled: true },
  );
  const partial = calculatePortfolio(
    working,
    histories,
    copies,
    "2024-01-01",
    "2025-12-31",
    "closed",
    { ...defaultPolicy, enabled: true },
  );
  assert.deepEqual(
    gated.points.filter((p) => p.date <= "2025-12-31"),
    partial.points,
  );
  const volatility = { ...defaultPolicy, enabled: true, mode: "volatility" };
  const sized = calculatePortfolio(
    working,
    histories,
    copies,
    "2024-01-01",
    "2026-08-31",
    "closed",
    volatility,
  );
  const sizedPartial = calculatePortfolio(
    working,
    histories,
    copies,
    "2024-01-01",
    "2025-12-31",
    "closed",
    volatility,
  );
  assert.deepEqual(
    sized.points.filter((p) => p.date <= "2025-12-31"),
    sizedPartial.points,
  );
  assert.equal(sized.trades, closed.trades, "Volatility scaling never skips an entry");
  assert(sized.exposure > 0 && sized.exposure < defaultPolicy.volCap);
  assert.equal(gated.dependence.length, working.length);
  console.log(
    JSON.stringify(
      {
        configurations: catalog.items.length,
        working: working.length,
        feasible: catalog.items.filter((i) => i.feasible).length,
        combined_net: result.net,
        capital: result.capital,
        drawdown: result.maxDrawdown,
        score: result.recoveryFactor,
        pause_net: gated.net,
        pause_delta: gated.net - result.net,
        pause_events: gated.events.length,
        loss_clustering_books: gated.dependence.filter((d) => d.verdict === "cluster").length,
        volatility_net: sized.net,
        volatility_drawdown_dollars: sized.maxDrawdownDollars,
        volatility_exposure: sized.exposure,
        volatility_score: sized.recoveryFactor,
      },
      null,
      2,
    ),
  );
}
