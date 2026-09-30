import type { RunSummary } from "../../../shared/ts/workbenchModels.ts";
import { strategyTitle } from "../../shared/formatting/strategyTitle.ts";

export type RunSortValue = string | number | null | undefined;
export type RunSortColumn = {
  key: string;
  label: string;
  numeric?: boolean;
  value: (run: RunSummary, now: number) => RunSortValue;
};

export function runtimeSeconds(run: RunSummary, now: number) {
  return run.started_at
    ? Math.max(
        0,
        (run.ended_at ? Date.parse(run.ended_at) : now) -
          Date.parse(run.started_at),
      ) / 1000
    : null;
}

export const runSortColumns: RunSortColumn[] = [
  { key: "created", label: "Created", value: (run) => Date.parse(run.created_at) },
  {
    key: "strategy",
    label: "Strategy / run",
    value: (run) => strategyTitle(run.input.strategy.name),
  },
  {
    key: "data",
    label: "Data / window",
    value: (run) =>
      `${run.input.dataset.symbol} ${run.input.timeframe} ${run.input.start} ${run.input.end}`,
  },
  { key: "stage", label: "Run purpose", value: (run) => run.input.stage },
  { key: "status", label: "Execution", value: (run) => run.status },
  {
    key: "return",
    label: "Net return",
    numeric: true,
    value: (run) => run.result?.metrics.net_return,
  },
  {
    key: "drawdown",
    label: "Drawdown",
    numeric: true,
    value: (run) => run.result?.metrics.max_drawdown,
  },
  {
    key: "trades",
    label: "Trades",
    numeric: true,
    value: (run) => run.result?.metrics.trades,
  },
  { key: "runtime", label: "Runtime", numeric: true, value: runtimeSeconds },
];

export const runSortOptions = runSortColumns.flatMap((column) =>
  ["asc", "desc"].map((direction) => ({
    value: `${column.key}:${direction}`,
    label:
      column.key === "created"
        ? direction === "asc"
          ? "Oldest"
          : "Newest"
        : `${column.label} (${direction === "asc" ? "ascending" : "descending"})`,
  })),
);

export function compareRunValues(
  a: RunSortValue,
  b: RunSortValue,
  descending: boolean,
) {
  const missing = (value: RunSortValue) =>
    value == null || (typeof value === "number" && !Number.isFinite(value));
  if (missing(a)) return missing(b) ? 0 : 1;
  if (missing(b)) return -1;
  const order =
    typeof a === "number" && typeof b === "number"
      ? a - b
      : String(a).localeCompare(String(b), undefined, {
          numeric: true,
          sensitivity: "base",
        });
  return descending ? -order : order;
}

export function runConfigurationKey(run: RunSummary) {
  if (run.input.configuration_id) return run.input.configuration_id;
  return JSON.stringify([
    run.input.strategy.id,
    run.input.dataset.symbol,
    run.input.timeframe,
    run.input.session,
    run.input.parameters,
  ]);
}

function runRecency(run: RunSummary) {
  return [
    Date.parse(run.input.end || ""),
    Date.parse(run.ended_at || run.created_at || ""),
    Date.parse(run.created_at || ""),
  ];
}

function isNewerRun(candidate: RunSummary, current: RunSummary) {
  const left = runRecency(candidate);
  const right = runRecency(current);
  for (let i = 0; i < left.length; i += 1) {
    if (left[i] !== right[i]) return left[i] > right[i];
  }
  return candidate.id > current.id;
}

export function isInvalidRun(run: RunSummary) {
  return run.status === "Succeeded" && !run.result?.metrics;
}

export function latestRunsByConfiguration(runs: RunSummary[]) {
  const latest = new Map<string, RunSummary>();
  for (const run of runs.filter((candidate) => !isInvalidRun(candidate))) {
    const key = runConfigurationKey(run);
    const current = latest.get(key);
    if (!current || isNewerRun(run, current)) latest.set(key, run);
  }
  return [...latest.values()].sort((a, b) => {
    if (isNewerRun(a, b)) return -1;
    if (isNewerRun(b, a)) return 1;
    return 0;
  });
}
