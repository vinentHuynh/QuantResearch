import assert from "node:assert/strict";
import {
  calculatePortfolio,
  defaultPolicy,
  replayGate,
} from "../src/collectiveModel.ts";
import {
  defaultSizing,
  volatilityModel,
  correlationRows,
} from "../src/riskSizing.ts";

const date = (n) =>
  new Date(Date.UTC(2025, 0, 1 + n)).toISOString().slice(0, 10);
const marks = Array.from({ length: 150 }, (_, n) => ({
  date: date(n),
  pnl: n % 3 === 0 ? 0 : (n % 2 ? 100 : -100) * (n >= 100 ? 3 : 1),
}));
const trades = Array.from({ length: 140 }, (_, n) => ({
  entry: date(n) + "T10:00:00Z",
  exit: date(n) + "T12:00:00Z",
  pnl: n % 2 ? 120 : -100,
  quantity: 4,
  cost: 8,
}));
const start = date(100),
  end = date(139),
  calibrationEnd = date(99);
const policy = {
  ...defaultPolicy,
  enabled: true,
  mode: "volatility",
  volLookback: 20,
  volCap: 1,
  sizing: { ...defaultSizing, estimator: "session", calibrationEnd },
};
const coverage = [{ start: date(0), end: date(149) }];
const item = (id, symbol = "ES") => ({
  id,
  name: id,
  symbol,
  capital: 100000,
  start: date(0),
  end: date(149),
  coverage,
});
const series = (id, ts = trades, daily = marks) => ({
  id,
  trades: ts,
  daily,
  coverage,
});
const run = (
  p,
  ts = trades,
  cs = { a: 1 },
  items = [item("a")],
  ss = [series("a", ts)],
  from = start,
  through = end,
) => calculatePortfolio(items, ss, cs, from, through, "closed", p);

const fixed = run({ ...policy, mode: "fixed" });
assert.equal(fixed.net, fixed.baseline * 0.75);
assert.equal(fixed.benchmarks[1].net, fixed.net);
assert.equal(fixed.benchmarks[1].drawdown, fixed.maxDrawdownDollars);
assert.equal(fixed.components[0].maxDrawdownDollars, fixed.maxDrawdownDollars);
assert.equal(fixed.components[0].maxDrawdownDollars, fixed.benchmarks[2].drawdown * 0.75);
assert.equal(fixed.benchmarks[2].recovery, fixed.benchmarks[1].recovery);

const model = volatilityModel(marks, policy);
const xs = marks.slice(80, 100).map((p) => p.pnl);
const mean = xs.reduce((a, b) => a + b) / xs.length;
assert(
  Math.abs(
    model.sigma(start) -
      Math.sqrt(xs.reduce((s, x) => s + (x - mean) ** 2, 0) / 19),
  ) < 1e-10,
  "Zero P&L observations count",
);
const replay = replayGate(trades, policy, end, marks, start);
const shifted = replayGate(trades, policy, end, marks, date(105));
assert.deepEqual(
  replay,
  shifted,
  "Changing the chart start cannot recalibrate exposure",
);
const future = replayGate(
  [
    ...trades,
    {
      ...trades.at(-1),
      entry: date(145) + "T10:00:00Z",
      exit: date(146) + "T10:00:00Z",
      pnl: -1e9,
    },
  ],
  policy,
  end,
  [...marks, { date: date(155), pnl: 1e9 }],
  start,
);
assert.deepEqual(
  replay,
  future,
  "Future trades and marks cannot change prior sizing",
);
for (let n = 101; n < trades.length; n++)
  assert(
    Math.abs(replay.weights.get(n) - replay.weights.get(n - 1)) <= 0.25 + 1e-10,
  );
assert.throws(
  () => run({ ...policy, sizing: { ...policy.sizing, calibrationEnd: start } }),
  /after the frozen/,
);
assert.throws(
  () => run({ ...policy, sizing: { ...policy.sizing, floorFraction: NaN } }),
  /Invalid/,
);
assert.throws(
  () =>
    run(
      policy,
      trades,
      { a: 1 },
      [item("a")],
      [series("a", trades, marks.slice(95))],
    ),
  /20 valid/,
);
assert.throws(
  () => run({ ...policy, mode: "deterioration" }, trades.slice(80)),
  /50 normalized/,
);

const items = [item("a"), item("b", "NQ")],
  histories = [series("a"), series("b")],
  copies = { a: 1, b: 1 };
const portfolio = {
  ...policy,
  mode: "portfolio",
  sizing: { ...policy.sizing, portfolioVolLimit: 100, equityVolLimit: 80 },
};
const combined = run(portfolio, trades, copies, items, histories);
for (const d of combined.sizingDecisions.filter((d) => d.id === "a")) {
  const sigma = Math.max(
    model.sigma(d.entry.slice(0, 10)),
    model.target * policy.sizing.floorFraction,
  );
  assert(
    2 * d.multiple * sigma <= 80 + 1e-6,
    "Perfectly correlated simultaneous books respect the shared equity risk cap",
  );
}
const reversed = run(
  portfolio,
  trades,
  copies,
  [...items].reverse(),
  [...histories].reverse(),
);
assert.equal(
  combined.net,
  reversed.net,
  "Simultaneous entries have no item-order priority",
);
assert(
  Math.abs(combined.components[0].pnl - combined.components[1].pnl) < 1e-8,
);
assert(combined.net < run(policy, trades, copies, items, histories).net);
assert.deepEqual(
  combined.points.filter((p) => p.date <= date(120)),
  run(portfolio, trades, copies, items, histories, start, date(120)).points,
);
assert(
  Math.abs(
    correlationRows(items, histories, calibrationEnd)[0].correlation - 1,
  ) < 1e-12,
);
const partialDaily = marks.filter((_, n) => n % 2 === 0);
assert.equal(
  correlationRows(
    items,
    [series("a"), series("b", trades, partialDaily)],
    calibrationEnd,
  )[0].observations,
  50,
  "Missing marks are not replaced with zeros",
);

const contracts = {
  ...policy,
  mode: "fixed",
  sizing: { ...policy.sizing, fixedSize: 0.74, wholeContracts: true },
};
const rounded = run(contracts);
assert.equal(
  rounded.net,
  rounded.baseline * 0.5,
  "4 contracts at .74 round down to 2",
);
const doubled = run(contracts, trades, { a: 2 });
assert.equal(
  doubled.net,
  (doubled.baseline * 5) / 8,
  "Copies are included before rounding",
);
assert.throws(
  () =>
    run(
      contracts,
      trades.map(({ quantity, ...t }) => t),
    ),
  /recorded quantities/,
);
const margin = {
  ...contracts,
  sizing: {
    ...contracts.sizing,
    fixedSize: 1,
    marginPerContract: 1000,
    marginBudget: 4000,
  },
};
const margined = run(margin, trades, copies, items, histories);
assert.equal(
  margined.net,
  margined.baseline * 0.5,
  "Shared budget is allocated pro rata across simultaneous entries",
);
assert.throws(
  () => run({ ...margin, sizing: { ...margin.sizing, marginPerContract: 0 } }),
  /explicit margin/,
);

// Realized loss limits observe only earlier exits, never the outcome of a new entry.
const lossTrades = [
  {
    entry: start + "T09:00:00Z",
    exit: start + "T12:00:00Z",
    pnl: -200,
    quantity: 1,
  },
  {
    entry: start + "T12:00:00Z",
    exit: start + "T13:00:00Z",
    pnl: 50,
    quantity: 1,
  },
  {
    entry: start + "T12:00:01Z",
    exit: start + "T14:00:00Z",
    pnl: 500,
    quantity: 1,
  },
];
const lossPolicy = {
  ...policy,
  mode: "fixed",
  sizing: { ...policy.sizing, fixedSize: 1, lossLimit: 150 },
};
const limited = run(lossPolicy, lossTrades);
assert.equal(limited.net, -150);
assert.equal(limited.trades, 2, "Equal-time exit is unavailable to entry");
assert.equal(limited.components[0].state, "Paused");
assert.equal(
  run(lossPolicy, [lossTrades[0]]).components[0].state,
  "Paused",
  "Cutoff status sees a breach even without another entry",
);
assert.equal(
  run({ ...lossPolicy, enabled: false }, lossTrades).net,
  350,
  "Disabling replay disables caps too",
);

const damaged = trades.map((t, n) => ({ ...t, pnl: n >= 100 ? -300 : t.pnl }));
const decay = {
  ...policy,
  mode: "deterioration",
  sizing: {
    ...policy.sizing,
    monitorWindow: 20,
    monitorConfirm: 2,
    monitorThreshold: 1,
  },
};
const paused = replayGate(damaged, decay, end, marks, start);
assert.equal(paused.state, "Paused");
assert(paused.accepted.has(119));
assert(!paused.accepted.has(122));
const manual = [
  {
    timestamp: date(135) + "T09:00:00Z",
    action: "resume",
    reason: "Review complete",
  },
];
const resumed = replayGate(damaged, decay, end, marks, start, manual);
assert(resumed.accepted.has(135));
assert.equal(resumed.state, "Active");
assert.throws(
  () =>
    replayGate(damaged, decay, end, marks, start, [
      { ...manual[0], timestamp: "invalid" },
    ]),
  /timezone/,
);
assert.deepEqual(
  replayGate(damaged, decay, date(125), marks, start).events,
  paused.events.filter((e) => e.timestamp.slice(0, 10) <= date(125)),
);
console.log(
  "Sizing checks passed: benchmarks, frozen/causal calibration, zero sessions, caps, correlations, copies, whole contracts, shared margin, equal-time losses, sustained deterioration and manual review.",
);
