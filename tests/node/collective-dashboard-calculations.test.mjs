import assert from "node:assert/strict";
import { test } from "node:test";

import {
  filterCollectiveItems,
  hasLatestEsNqWindow,
  itemsForLoadedSeries,
  selectedCollectiveItems,
  summarizeCollectiveResult,
  verifiedCommonEnd,
  withLatestEsNq,
} from "../../shared/ts/collective.ts";
import {
  coverageEndExplanation,
  firstAvailableSavedCombination,
  followCommonStartForSavedSettings,
  alignCommonStart,
  followLatestForSavedSettings,
  initializeCollectiveSettings,
  portfolioUpdatePresentation,
  strategyReturnAndDrawdownPercent,
} from "../../src/features/portfolio/collectiveViewModel.ts";

const item = (id, symbol, overrides = {}) => ({
  id,
  key: id,
  name: `${symbol} strategy`,
  symbol,
  timeframe: "1h",
  session: "rth",
  source: `${id}.json`,
  start: "2024-01-01",
  end: "2024-01-31",
  capital: 100000,
  working: true,
  feasible: false,
  tested: true,
  benchmark: false,
  reasons: [],
  parameters: {},
  net_pnl: 100,
  recent_pnl: 100,
  trades: 2,
  coverage: [{ start: "2024-01-01", end: "2024-01-31" }],
  series_file: `${id}.json`,
  checksum: id.padEnd(64, "0"),
  ...overrides,
});

test("portfolio selection and filters keep hidden selections independent", () => {
  const catalog = {
    items: [
      item("es", "ES", { feasible: true }),
      item("nq", "NQ"),
      item("ym", "YM", { working: false }),
    ],
  };
  const selected = selectedCollectiveItems(catalog, { es: 1, ym: 2 });
  const visible = filterCollectiveItems(catalog, {
    milestone: "working",
    markets: ["NQ"],
    timeframe: "all",
    search: "strategy",
  });

  assert.deepEqual(selected.map(({ id }) => id), ["es", "ym"]);
  assert.deepEqual(visible.map(({ id }) => id), ["nq"]);
  assert.deepEqual(
    selected.filter(
      ({ id }) => !visible.some((candidate) => candidate.id === id),
    ).map(({ id }) => id),
    ["es", "ym"],
  );
});

test("latest ES/NQ availability requires both markets and a common window", () => {
  const latest = { start: "2024-01-01", end: "2024-01-31", dataset_id: "d", extension_sha256: "a" };
  const es = item("es", "ES", { latest_replay: latest });
  const nq = item("nq", "NQ", {
    latest_replay: latest,
    coverage: [{ start: "2024-01-15", end: "2024-02-15" }],
  });

  assert.deepEqual(hasLatestEsNqWindow([es]), {
    available: false,
    window: { start: "2024-01-01", end: "2024-01-31" },
  });
  assert.deepEqual(hasLatestEsNqWindow([es, nq]), {
    available: true,
    window: { start: "2024-01-15", end: "2024-01-31" },
  });
});

test("latest ES/NQ opens from the catalog without changing capital or accounting", () => {
  const es = item("es", "ES", {
    end: "2026-09-30",
    coverage: [{ start: "2024-01-01", end: "2026-09-30" }],
    latest_replay: { start: "2026-09-01", end: "2026-09-30" },
  });
  const nq = item("nq", "NQ", {
    end: "2026-09-28",
    coverage: [{ start: "2024-01-01", end: "2026-09-28" }],
    latest_replay: { start: "2026-09-01", end: "2026-09-28" },
  });
  const settings = {
    capital: 125000,
    copies: { es: 2, ym: 1 },
    start: "2024-02-01",
    end: "2026-08-31",
    basis: "closed",
    policy: { enabled: false },
  };
  assert.deepEqual(withLatestEsNq(settings, { items: [es, nq] }), {
    ...settings,
    copies: { es: 1, nq: 1 },
    end: "2026-09-28",
  });
  assert.deepEqual(withLatestEsNq(settings, { items: [es] }), null);
});

test("portfolio presentation summaries aggregate markets and years", () => {
  const summary = summarizeCollectiveResult({
    points: [
      { date: "2024-12-31", pnl: 4, bySymbol: { ES: 3, NQ: 1 } },
      { date: "2025-01-02", pnl: -2, bySymbol: { ES: -2 } },
    ],
  });
  assert.deepEqual(summary, {
    totals: { ES: 1, NQ: 1 },
    annual: { 2024: 4, 2025: -2 },
  });
});

test("selected strategy percentages use its daily portfolio P&L and peak equity", () => {
  const result = {
    capital: 100,
    components: [
      { id: "es", pnl: 15 },
      { id: "nq", pnl: -10 },
    ],
    points: [
      { byStrategy: { es: 20, nq: -5 } },
      { byStrategy: { es: -10, nq: 2 } },
      { byStrategy: { es: 5, nq: -7 } },
    ],
  };

  const es = strategyReturnAndDrawdownPercent(result, "es");
  assert.equal(es.pnlPercent, 0.15);
  assert.ok(Math.abs(es.drawdownPercent - 10 / 120) < 1e-10);

  const nq = strategyReturnAndDrawdownPercent(result, "nq");
  assert.equal(nq.pnlPercent, -0.1);
  assert.ok(Math.abs(nq.drawdownPercent - 0.1) < 1e-10);
});

test("follow latest migrates only a saved end date at the common tested end", () => {
  const saved = { end: "2026-08-31" };
  assert.equal(followLatestForSavedSettings(saved, "2026-08-31"), true);
  assert.equal(followLatestForSavedSettings(saved, "2026-09-29"), false);
  assert.equal(followLatestForSavedSettings({ ...saved, followLatest: false }, "2026-08-31"), false);
  assert.equal(followLatestForSavedSettings({ ...saved, followLatest: true }, "2026-09-29"), true);
});

test("manual end coverage copy names the limiting book and complete UTC data day", () => {
  const old = item("old", "NQ", {
    name: "Multi-speed momentum", timeframe: "1h", end: "2023-12-31",
    coverage: [{ start: "2018-01-01", end: "2023-12-31" }],
  });
  const recent = item("recent", "NQ", {
    name: "Overnight Session", timeframe: "1m", end: "2026-09-28",
    coverage: [{ start: "2018-01-01", end: "2026-09-28" }],
  });
  const settings = { start: "2020-09-05", end: "2026-09-30", followLatest: false };
  const tracking = { selection: ["old", "recent"], items: {
    old: { status: "manual-update-required", dataset_last: "2026-09-28" },
    recent: { status: "up-to-date", dataset_last: "2026-09-28" },
  } };
  const message = coverageEndExplanation(
    [old, recent], [], settings,
    { start: "2020-09-05", end: "2023-12-31" }, tracking,
  );
  assert.match(message, /manually set P&L end is 2026-09-30/);
  assert.match(message, /latest complete UTC data day.*2026-09-28/);
  assert.match(message, /Multi-speed momentum \/ NQ \/ 1h is simulated through 2023-12-31/);
  assert.match(message, /requires a manual update/);
  assert.match(message, /Apply the common tested window/);
  assert.equal(settings.end, "2026-09-30");
  assert.equal(settings.followLatest, false);
  assert.equal(coverageEndExplanation([old, recent], [],
    { ...settings, end: "2023-12-31" },
    { start: "2020-09-05", end: "2023-12-31" }, tracking), null);
});

test("portfolio update copy distinguishes failed and pinned histories from manual work", () => {
  const update = { status: "manual-update-required", error: "older history" };
  const failed = item("failed", "NQ", {
    research_status: { kind: "failed-checks", finding: "Frozen drawdown criterion failed." },
  });
  assert.deepEqual(portfolioUpdatePresentation(failed, update), {
    label: "Failed checks · history retained",
    attention: true,
    title: "Frozen drawdown criterion failed.",
  });

  const pinned = item("pinned", "NQ", {
    key: "example__NQ__pinned__run",
    source: "Pinned workbench",
  });
  const pinnedPresentation = portfolioUpdatePresentation(pinned, update);
  assert.equal(pinnedPresentation.label, "Pinned history · not auto-updated");
  assert.equal(pinnedPresentation.attention, true);
  assert.match(pinnedPresentation.title, /exact saved history is immutable/i);

  assert.deepEqual(portfolioUpdatePresentation(item("manual", "NQ"), update), {
    label: "Manual update required",
    attention: true,
    title: "older history",
  });
});

test("coverage copy treats a pinned limiter as a fixed historical snapshot", () => {
  const pinned = item("pinned", "NQ", {
    key: "example__NQ__pinned__run",
    source: "Pinned workbench",
    end: "2023-12-31",
    coverage: [{ start: "2018-01-01", end: "2023-12-31" }],
  });
  const message = coverageEndExplanation(
    [pinned], [],
    { start: "2020-01-01", end: "2026-09-28", followLatest: false },
    { start: "2020-01-01", end: "2023-12-31" },
    { selection: ["pinned"], items: { pinned: { status: "manual-update-required", dataset_last: "2026-09-28" } } },
  );
  assert.match(message, /fixed historical snapshot/);
  assert.match(message, /current replayable configuration/);
  assert.doesNotMatch(message, /requires a manual update/);
});

test("automatic portfolio start follows the verified common window while manual starts stay fixed", () => {
  const common = { start: "2022-01-01", end: "2026-09-28" };
  assert.equal(followCommonStartForSavedSettings({ start: "2020-09-05" }, common), true);
  assert.equal(followCommonStartForSavedSettings({ start: "2023-01-01" }, common), false);
  assert.equal(followCommonStartForSavedSettings({ start: "2020-09-05", followCommonStart: false }, common), false);
  assert.equal(followCommonStartForSavedSettings({ start: "2023-01-01", followCommonStart: true }, common), true);
  const automatic = { start: "2020-09-05", followCommonStart: true };
  assert.equal(alignCommonStart(automatic, common).start, "2022-01-01");
  assert.equal(alignCommonStart({ ...automatic, start: "2022-01-01" },
    { start: "2020-09-05", end: "2026-09-28" }).start, "2020-09-05");
  assert.equal(alignCommonStart({ ...automatic, followCommonStart: false }, common).start, "2020-09-05");
  assert.equal(alignCommonStart(automatic, { start: "", end: "" }).start, "2020-09-05");
});

test("a later-start selected book aligns a legacy invalid start without changing a pinned start", () => {
  const catalog = { items: [
    item("older", "NQ", { coverage: [{ start: "2020-09-05", end: "2026-09-28" }] }),
    item("later", "NQ", { coverage: [{ start: "2022-01-01", end: "2026-09-28" }] }),
  ] };
  const settings = { capital: 100000, copies: { older: 1, later: 1 }, start: "2020-09-05",
    end: "2026-09-28", followLatest: true, basis: "marked", policy: { enabled: false } };
  const restored = initializeCollectiveSettings(settings, catalog, true, ["older", "later"]);
  assert.equal(restored.start, "2022-01-01");
  assert.equal(restored.followCommonStart, true);
  const pinned = initializeCollectiveSettings({ ...settings, followCommonStart: false }, catalog, true, ["older", "later"]);
  assert.equal(pinned.start, "2020-09-05");
  assert.equal(pinned.followCommonStart, false);
  const validInterior = initializeCollectiveSettings({ ...settings, start: "2023-01-01" }, catalog, true, ["older", "later"]);
  assert.equal(validInterior.start, "2023-01-01");
  assert.equal(validInterior.followCommonStart, false);
});

test("follow latest waits for every refreshed history before moving the end date", () => {
  const es = item("es", "ES", { end: "2026-09-29", coverage: [{ start: "2024-01-01", end: "2026-09-29" }] });
  const nq = item("nq", "NQ", { end: "2026-09-29", coverage: [{ start: "2024-01-01", end: "2026-09-29" }] });
  const old = (id) => ({ id, daily: [], trades: [], coverage: [{ start: "2024-01-01", end: "2026-08-31" }] });
  const updated = (id) => ({ id, daily: [], trades: [], coverage: [{ start: "2024-01-01", end: "2026-09-29" }] });

  assert.equal(verifiedCommonEnd([es, nq], []), "");
  assert.equal(verifiedCommonEnd([es, nq], [old("es"), old("nq")]), "2026-08-31");
  assert.equal(verifiedCommonEnd([es, nq], [updated("es"), old("nq")]), "2026-08-31");
  assert.equal(verifiedCommonEnd([es, nq], [updated("es"), updated("nq")]), "2026-09-29");
});

test("browser selections and manual dates survive initialization while a new browser uses server IDs", () => {
  const catalog = { items: [item("es", "ES"), item("nq", "NQ")] };
  const settings = {
    capital: 100000,
    copies: { es: 3 },
    start: "2024-01-01",
    end: "2024-01-15",
    followLatest: false,
    basis: "marked",
    policy: { enabled: false },
  };
  const restored = initializeCollectiveSettings(settings, catalog, true, ["nq"]);
  assert.deepEqual(restored.copies, { es: 3 });
  assert.equal(restored.end, "2024-01-15");
  assert.equal(restored.followLatest, false);

  const fresh = initializeCollectiveSettings(settings, catalog, false, ["nq"]);
  assert.deepEqual(fresh.copies, { nq: 1 });
  assert.equal(fresh.end, "2024-01-31");
  assert.equal(fresh.followLatest, true);
  assert.deepEqual(initializeCollectiveSettings(settings, catalog, false, []).copies, {});
});

test("the first saved combination with all selected books available becomes the default", () => {
  const catalog = { items: [item("es", "ES"), item("nq", "NQ")] };
  const saved = [
    { id: "removed", settings: { copies: { retired: 1 } } },
    { id: "unselected", settings: { copies: { es: 0 } } },
    { id: "partially-removed", settings: { copies: { retired: 1, es: 2 } } },
    { id: "first-available", settings: { copies: { es: 2 } } },
    { id: "later", settings: { copies: { nq: 1 } } },
  ];

  assert.equal(firstAvailableSavedCombination(saved, catalog), saved[3]);
  assert.equal(firstAvailableSavedCombination(saved.slice(4), catalog), saved[4]);
  assert.equal(firstAvailableSavedCombination(saved.slice(0, 3), catalog), undefined);
  assert.equal(firstAvailableSavedCombination([], catalog), undefined);
});

test("an updated catalog does not pair its changed book metadata with an older loaded series", () => {
  const loaded = item("es", "ES", { name: "Original", end: "2026-08-31" });
  const updated = item("es", "ES", { name: "Updated", end: "2026-09-29" });
  assert.equal(itemsForLoadedSeries([updated], { items: [loaded] })[0], loaded);
  assert.equal(itemsForLoadedSeries([updated], { items: [updated] })[0], updated);
});
