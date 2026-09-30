import {
  calculatePortfolio,
  commonWindow,
  PortfolioCoverageError,
  type CollectiveCatalog,
  type CollectiveItem,
  type CollectiveSeries,
  type GatePolicy,
} from "./portfolio.ts";
import { collectiveProgress } from "./progress.ts";

export type PortfolioResult = ReturnType<typeof calculatePortfolio>;

export type CollectiveComputation = {
  value: PortfolioResult | null;
  error: string;
  coverageGap: boolean;
};

export type CollectiveFilters = {
  milestone: string;
  markets: string[];
  timeframe: string;
  search: string;
};

export type CollectiveCalculationSettings = {
  capital: number;
  copies: Record<string, number>;
  start: string;
  end: string;
  basis: "marked" | "closed";
  policy: GatePolicy;
};

export function selectedCollectiveItems(
  catalog: CollectiveCatalog | null,
  copies: Record<string, number>,
) {
  return (catalog?.items || []).filter((item) => copies[item.id] > 0);
}

export function filterCollectiveItems(
  catalog: CollectiveCatalog | null,
  filters: CollectiveFilters,
) {
  const query = filters.search.toLowerCase();
  return (catalog?.items || [])
    .filter(
      (item) =>
        (filters.milestone === "all" ||
          (filters.milestone === "working"
            ? item.working
            : filters.milestone === "feasible"
              ? item.feasible
              : !item.working && !item.benchmark)) &&
        (!filters.markets.length || filters.markets.includes(item.symbol)) &&
        (filters.timeframe === "all" || item.timeframe === filters.timeframe) &&
        `${item.name} ${item.symbol} ${item.timeframe} ${item.session} ${item.source}`
          .toLowerCase()
          .includes(query),
    )
    .sort(
      (a, b) =>
        Number(a.benchmark) - Number(b.benchmark) ||
        collectiveProgress(b).stage - collectiveProgress(a).stage ||
        a.name.localeCompare(b.name) ||
        a.symbol.localeCompare(b.symbol),
    );
}

export function latestEsNqItems(catalog: CollectiveCatalog | null) {
  return (catalog?.items || []).filter(
    (item) =>
      item.working &&
      item.latest_replay &&
      (item.symbol === "ES" || item.symbol === "NQ"),
  );
}

export function hasLatestEsNqWindow(items: CollectiveItem[]) {
  const window = commonWindow(items);
  return {
    window,
    available:
      items.length >= 2 &&
      items.some((item) => item.symbol === "ES") &&
      items.some((item) => item.symbol === "NQ") &&
      Boolean(window.end),
  };
}

export function calculateCollectiveResult(
  selected: CollectiveItem[],
  histories: CollectiveSeries[],
  settings: CollectiveCalculationSettings,
): CollectiveComputation {
  try {
    return {
      value: calculatePortfolio(
        selected,
        histories,
        settings.copies,
        settings.start,
        settings.end,
        settings.basis,
        settings.policy,
        settings.capital,
      ),
      error: "",
      coverageGap: false,
    };
  } catch (error) {
    return {
      value: null,
      error: String(error instanceof Error ? error.message : error),
      coverageGap: error instanceof PortfolioCoverageError,
    };
  }
}

export function collectiveTestedWindow(
  selected: CollectiveItem[],
  histories: CollectiveSeries[],
) {
  return commonWindow(
    selected.map(
      (item) => histories.find((history) => history.id === item.id) || item,
    ),
  );
}

export function summarizeCollectiveResult(result: PortfolioResult | null) {
  const totals: Record<string, number> = {};
  const annual: Record<string, number> = {};
  for (const point of result?.points || []) {
    for (const [symbol, pnl] of Object.entries(point.bySymbol)) {
      totals[symbol] = (totals[symbol] || 0) + pnl;
    }
    const year = point.date.slice(0, 4);
    annual[year] = (annual[year] || 0) + point.pnl;
  }
  return { totals, annual };
}
