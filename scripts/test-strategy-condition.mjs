import assert from "node:assert/strict";
import {
  assessCondition,
  fitReference,
  normalizedMarks,
  monitor,
  conditionProtocol,
} from "../src/strategyCondition.ts";
import { replayGate, defaultPolicy } from "../src/collectiveModel.ts";
const date = (n) =>
  new Date(Date.UTC(2022, 0, 1 + n)).toISOString().slice(0, 10);
const daily = Array.from({ length: 950 }, (_, n) => ({
  date: date(n),
  pnl: n % 2 ? 100 : -90,
  segment: "one",
}));
const trades = Array.from({ length: 15 }, (_, n) => ({
  entry: date(920 + n) + "T10:00:00Z",
  exit: date(920 + n) + "T12:00:00Z",
  pnl: n < 5 ? 100 : -10,
  synthetic_exit: false,
}));
const series = {
  id: "a",
  provenance_version: 2,
  daily,
  trades,
  coverage: [{ start: date(0), end: date(949) }],
};
const item = {
  id: "a",
  name: "Fixture",
  symbol: "ES",
  timeframe: "1d",
  checksum: "source",
};
const reference = fitReference(series);
const mixedVersions = {
  ...series,
  trades: [
    { entry: date(0), exit: date(10), pnl: 1, source_version: "old" },
    { entry: date(20), exit: date(30), pnl: 1, source_version: "new" },
  ],
};
assert.equal(
  fitReference(mixedVersions),
  null,
  "Do not pool changed strategy sources",
);
assert(reference && reference.count > 600);
const calibration = {
  ...conditionProtocol,
  h: 30,
  createdAt: "2026-01-01",
  sources: [{ id: "a", checksum: "source" }],
  books: { a: reference },
  validation: { accepted: true },
  report: "fixture",
};
const current = assessCondition(item, series, date(949), calibration);
const versioned = {
  ...calibration,
  books: { a: { ...reference, sourceVersion: "old" } },
};
assert.equal(
  assessCondition(
    item,
    { ...series, trades: trades.map((t) => ({ ...t, source_version: "new" })) },
    date(949),
    versioned,
  ).calibrated,
  false,
);
assert.equal(current.condition, "Watch — recent losses");
assert.equal(current.last10.pnl, -100);
assert.equal(current.lossStreak, 10);
assert.equal(current.last10.start, date(925));
assert.equal(current.last10.end, date(934));
assert(current.available);
// Historical snapshots cannot borrow future outcomes or future marked volatility.
const cutoff = date(929);
const prefix = {
  ...series,
  daily: daily.filter((d) => d.date <= cutoff),
  trades: trades.filter((t) => t.exit.slice(0, 10) <= cutoff),
};
assert.deepEqual(
  normalizedMarks(series, reference, cutoff),
  normalizedMarks(prefix, reference, cutoff),
);
const fullAssessment = assessCondition(item, series, cutoff, calibration);
const prefixAssessment = assessCondition(item, prefix, cutoff, calibration);
for (const field of [
  "last10",
  "last20",
  "drawdown",
  "lossStreak",
  "detector",
  "condition",
])
  assert.deepEqual(fullAssessment[field], prefixAssessment[field]);
assert.deepEqual(
  fitReference({
    ...series,
    daily: daily.map((d) => (d.date > "2023-12-31" ? { ...d, pnl: 1e12 } : d)),
  }),
  reference,
);
// Forced wins and losses never change the natural sample or streak; marked accounting stays intact.
const forced = {
  ...series,
  trades: [
    ...trades,
    ...[1e6, -1e6].map((pnl, n) => ({
      entry: date(940 + n),
      exit: date(941 + n),
      pnl,
      synthetic_exit: true,
    })),
  ],
};
const forcedStatus = assessCondition(item, forced, date(949), calibration);
assert.deepEqual(forcedStatus.last10, current.last10);
assert.equal(forcedStatus.lossStreak, current.lossStreak);
assert.equal(forcedStatus.excludedSynthetic, 2);
const unknown = assessCondition(
  item,
  {
    ...series,
    trades: [...trades, { entry: date(945), exit: date(946), pnl: -100 }],
  },
  date(949),
  calibration,
);
assert.equal(unknown.unknownExits, 1);
assert.equal(unknown.lossStreak, null);
const stale = assessCondition(item, series, "2026-09-16", calibration);
assert(!stale.available);
assert.equal(stale.asOf, date(949));
assert.equal(stale.condition, current.condition);
const gap = assessCondition(
  item,
  {
    ...series,
    coverage: [
      { start: date(0), end: date(900) },
      { start: date(940), end: date(949) },
    ],
  },
  date(930),
  calibration,
);
assert(!gap.available);
assert.equal(gap.asOf, date(900));
assert.equal(
  assessCondition(item, series, "2021-01-01", calibration).condition,
  "Insufficient evidence",
);
assert.equal(
  assessCondition(item, series, "2023-01-01", calibration).calibrated,
  false,
);
assert.equal(
  assessCondition(
    { ...item, checksum: "changed" },
    series,
    date(949),
    calibration,
  ).calibrated,
  false,
);
assert.equal(
  assessCondition(
    item,
    { ...series, provenance_version: 1 },
    date(949),
    calibration,
  ).calibrated,
  false,
);
assert.equal(
  assessCondition(item, series, date(949), {
    ...calibration,
    validation: { accepted: false },
  }).calibrated,
  false,
);
const warmup = {
  ...series,
  daily: daily.map((d, n) => (n > 940 ? { ...d, segment: "new run" } : d)),
};
assert.equal(
  assessCondition(item, warmup, date(949), calibration).calibrated,
  false,
);
const points = (n, value, offset = 0, segment = "one") =>
  Array.from({ length: n }, (_, i) => ({
    date: date(800 + offset + i),
    value,
    segment,
  }));
const weak = points(10, -1);
assert(monitor(weak, 0.25, 5).alarm);
assert(monitor([...weak, ...points(20, 1, 10)], 0.25, 5).recovery);
assert(!monitor([...weak, ...points(40, 1, 10)], 0.25, 5).recovery);
assert(!monitor([...weak, ...points(1, 1, 10, "new run")], 0.25, 5).alarm);
assert.deepEqual(
  monitor(weak, 0.25, 5),
  monitor([...weak, ...points(20, 1, 10)].slice(0, 10), 0.25, 5),
);
// Terminal daily P&L still appears in accounting, never in inference.
const terminal = {
  ...series,
  daily: daily.map((d, n) =>
    n === 949 ? { ...d, terminal: true, pnl: -123456 } : d,
  ),
};
assert.equal(
  normalizedMarks(terminal, reference, date(949)).at(-1).date,
  date(948),
);
assert(
  assessCondition(item, terminal, date(949), calibration).last20.pnl < -120000,
);
const gateTrades = [-1, -1, 100, -1, 10].map((pnl, n) => ({
  entry: date(900 + n) + "T10:00:00Z",
  exit: date(900 + n) + "T12:00:00Z",
  pnl,
  synthetic_exit: n === 2,
}));
const gate = replayGate(
  gateTrades,
  { ...defaultPolicy, enabled: true, mode: "streak", streak: 3, cooldown: 99 },
  date(910),
);
assert(
  !gate.accepted.has(4),
  "Forced winner must not reset a natural loss streak",
);
console.log(
  "Condition checks passed: causal dates and normalization, forced/unknown exits, accounting retention, freshness/gaps, calibration provenance, segment warmup, warning/recovery hysteresis, and natural-only permission triggers.",
);
