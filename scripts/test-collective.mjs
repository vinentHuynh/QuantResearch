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
assert.equal(base.capital, 3000);
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
assert.deepEqual([...gate.accepted], [0, 1, 3, 4]);
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
assert.equal(filtered.net, 60);
assert.equal(filtered.baseline, 90);
assert.equal(filtered.components[0].skipped, 1);
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
console.log(
  "Collective checks passed: aggregation, capital/copies, coverage gaps, leap dates, prior-only gates, shadow recovery, open trades, prefix invariance, and verified history access.",
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
  assert(
    Math.abs(result.net - working.reduce((n, i) => n + i.recent_pnl, 0)) < 0.01,
  );
  const closed = calculatePortfolio(
    working,
    histories,
    copies,
    "2024-01-01",
    "2026-08-31",
    "closed",
    defaultPolicy,
  );
  assert(Math.abs(closed.net - result.net) < 0.01);
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
      },
      null,
      2,
    ),
  );
}
