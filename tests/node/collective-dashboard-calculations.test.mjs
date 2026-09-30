import assert from "node:assert/strict";
import { test } from "node:test";

import {
  filterCollectiveItems,
  hasLatestEsNqWindow,
  selectedCollectiveItems,
  summarizeCollectiveResult,
} from "../../shared/ts/collective.ts";

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
