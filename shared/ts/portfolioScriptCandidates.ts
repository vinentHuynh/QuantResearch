import { runConfigurationKey } from "./evidence.ts";
import type { CollectiveCatalog, CollectiveItem } from "./portfolio.ts";
import { isCurrentStrategyRun, portfolioStageStatus, type strategyStageStatuses } from "./stageStatus.ts";
import { lifecycleStatus, type StrategyStageStatus } from "./strategyLifecycle.ts";
import type { RunSummary, Strategy } from "./workbenchModels.ts";

export type PortfolioScriptCandidate = {
  strategyId: string;
  name: string;
  symbol: string;
  timeframe: string;
  item?: CollectiveItem;
  run?: RunSummary;
  status: StrategyStageStatus;
  pnl: number | null;
  chart: number[];
  date: string;
};

export type PortfolioScriptGroup = {
  strategyId: string;
  name: string;
  options: PortfolioScriptCandidate[];
};

export type PortfolioDailyRisk = { max_drawdown: number; max_drawdown_dollars: number };
export type PortfolioRiskDetails = {
  maxDrawdownPercent: number | null;
  maxDrawdownDollars: number | null;
  score: number | null;
};

type RankedCandidate = PortfolioScriptCandidate & { score: number | null; trades: number };
type Filters = { markets?: string[]; timeframe?: string; search?: string };

const finite = (value: number | null | undefined): value is number => typeof value === "number" && Number.isFinite(value);
export const isPortfolioBaselineRun = (run: RunSummary, importedBenchmark = false) => {
  if (run.input.portfolio_replay) return false;
  const research = run.input.research;
  if (research) return research.role === "Test" && research.scenario === "Baseline";
  const tags = (run.tags || "").toLowerCase();
  return !run.input.delay_bars && !["stress", "sensitivity", ...(importedBenchmark ? [] : ["benchmark"])].some(tag => tags.includes(tag));
};
const configuration = (run: RunSummary) => JSON.stringify([run.input.strategy.id, runConfigurationKey(run)]);
const recency = (run: RunSummary) => run.created_at || run.input.end || "";
const metricScore = (run?: RunSummary) => {
  const metrics = run?.result?.metrics;
  return metrics && finite(metrics.trades) && metrics.trades > 0
    && finite(metrics.net_return) && finite(metrics.max_drawdown) && metrics.max_drawdown !== 0
    && finite(metrics.net_return / Math.abs(metrics.max_drawdown))
    ? metrics.net_return / Math.abs(metrics.max_drawdown) : null;
};
const runChart = (run?: RunSummary) => {
  if (!run?.result?.metrics.monthly?.length || !finite(run.input.capital)) return [];
  let equity = run.input.capital;
  const points = [0];
  for (const month of run.result.metrics.monthly) {
    if (!finite(month.return)) continue;
    equity *= 1 + month.return;
    if (!finite(equity)) return [];
    points.push(equity - run.input.capital);
  }
  return points;
};

/** Evidence quality is compared before performance, including when two
 * configurations belong to the same script. A failure remains visible when
 * there is no stronger supported option; stale imports never imply a pass. */
function evidenceRank(status: StrategyStageStatus): [number, number] {
  const milestones: Partial<Record<StrategyStageStatus["kind"], number>> = {
    "practical-ready": 60, "forward-tested": 50, "forward-testing": 40,
    "robustness-validated": 30, "evaluation-passed": 20,
  };
  if (milestones[status.kind] !== undefined) return [4, milestones[status.kind]!];
  if (["validation-pending", "evaluation-running", "backtest-running", "not-tested"].includes(status.kind)) {
    return [3, status.stage * 10 + (status.kind === "evaluation-running" ? 2 : status.kind === "validation-pending" ? 1 : 0)];
  }
  if (status.kind === "failed-checks") return [2, status.failedStage || status.stage];
  if (status.kind === "benchmark") return [1, status.stage];
  return [0, status.stage];
}

/** Compare saved-window outcomes using the full end-of-day equity series.
 * A chart or intraday run metric is never a substitute for that series. */
export function portfolioRiskDetails(
  candidate: PortfolioScriptCandidate,
  rawRisk: Readonly<Record<string, PortfolioDailyRisk>> = {},
): PortfolioRiskDetails {
  const source = candidate.item || (candidate.run ? rawRisk[candidate.run.id] : undefined);
  const dollars = source?.max_drawdown_dollars;
  const fraction = source?.max_drawdown;
  if (!finite(dollars) || dollars < 0 || !finite(fraction) || fraction > 0) {
    return { maxDrawdownPercent: null, maxDrawdownDollars: null, score: null };
  }
  const pnl = candidate.pnl;
  const score = !finite(pnl) ? null : dollars > 0 ? pnl / dollars : pnl > 0 ? Infinity : null;
  return {
    maxDrawdownPercent: Math.abs(fraction) * 100,
    maxDrawdownDollars: dollars,
    score: score !== null && (Number.isFinite(score) || score === Infinity) ? score : null,
  };
}

/** The collapsed strategy preview is a performance comparison, independent
 * of the research-first order used for expanded histories. */
export function bestPortfolioPreview(
  options: PortfolioScriptCandidate[],
  rawRisk: Readonly<Record<string, PortfolioDailyRisk>> = {},
): PortfolioScriptCandidate | undefined {
  return [...options].sort((left, right) => {
    const a = portfolioRiskDetails(left, rawRisk).score;
    const b = portfolioRiskDetails(right, rawRisk).score;
    if (a !== b) {
      if (a === null) return 1;
      if (b === null) return -1;
      return b > a ? 1 : -1;
    }
    const aEvidence = evidenceRank(left.status), bEvidence = evidenceRank(right.status);
    return bEvidence[0] - aEvidence[0] || bEvidence[1] - aEvidence[1]
      || (right.item?.end || right.run?.input.end || right.date).localeCompare(
        left.item?.end || left.run?.input.end || left.date)
      || right.date.localeCompare(left.date)
      || (left.item?.id || left.run?.id || "").localeCompare(right.item?.id || right.run?.id || "");
  })[0];
}

function compareCandidates(left: RankedCandidate, right: RankedCandidate) {
  const a = evidenceRank(left.status), b = evidenceRank(right.status);
  const scoreA = left.score ?? -Infinity, scoreB = right.score ?? -Infinity;
  return b[0] - a[0] || b[1] - a[1]
    || (scoreA === scoreB ? 0 : scoreA > scoreB ? -1 : 1)
    || right.trades - left.trades
    || right.date.localeCompare(left.date)
    || left.name.localeCompare(right.name)
    || left.strategyId.localeCompare(right.strategyId)
    || (left.item?.id || left.run?.id || "").localeCompare(right.item?.id || right.run?.id || "");
}

function matches(candidate: PortfolioScriptCandidate, filters: Filters) {
  const query = (filters.search || "").trim().toLowerCase();
  const ids = candidate.item?.source_run_ids || (candidate.run ? [candidate.run.id] : []);
  const source = candidate.run?.input.execution_source_hash || candidate.run?.input.source_hash || "";
  const searchable = [candidate.name, candidate.strategyId, candidate.symbol, candidate.timeframe,
    candidate.item?.id, candidate.item?.start, candidate.item?.end, candidate.run?.input.start,
    candidate.run?.input.end, source, ...ids,
    JSON.stringify(candidate.item?.parameters || candidate.run?.input.parameters || {})].join(" ").toLowerCase();
  return (!filters.markets?.length || filters.markets.includes(candidate.symbol))
    && (!filters.timeframe || filters.timeframe === "all" || filters.timeframe === candidate.timeframe)
    && (!query || searchable.includes(query));
}

function collectCandidates(
  strategies: Strategy[], catalog: CollectiveCatalog, runs: RunSummary[],
  statuses: ReturnType<typeof strategyStageStatuses>, filters: Filters,
  includeEveryRun: boolean,
): RankedCandidate[] {
  const scripts = new Map(strategies.map(strategy => [strategy.id, strategy]));
  const byRun = new Map(runs.map(run => [run.id, run]));
  const candidates: RankedCandidate[] = [];
  const importedConfigurations = new Set<string>();
  const importedExactRuns = new Set<string>();
  const representedScripts = new Set<string>();

  for (const item of catalog.items) {
    const ids = item.source_run_ids || [];
    const linked = ids.map(id => byRun.get(id));
    const known = linked.filter((run): run is RunSummary => !!run);
    const linkedScripts = new Set(known.map(run => run.input.strategy.id));
    // Conflicting explicit provenance must not be reassigned via a similar
    // label or key. Legacy unlinked histories require an exact registered key.
    if (linkedScripts.size > 1 || known.some(run => !isPortfolioBaselineRun(run, item.benchmark))) continue;
    const strategyId = linked.length > 0 && known.length === linked.length
      ? known[0].input.strategy.id : item.key.split("__")[0];
    const strategy = scripts.get(strategyId);
    if (!strategy || (linkedScripts.size && !linkedScripts.has(strategyId))) continue;
    const status = portfolioStageStatus(item, runs, statuses);
    const keys = new Set(known.map(configuration));
    const exactSettings = known.length === ids.length && known.length > 0 && keys.size === 1
      && known.every(run => run.input.dataset.symbol === item.symbol && run.input.timeframe === item.timeframe
        && run.input.session === item.session && Object.keys(run.input.parameters).length === Object.keys(item.parameters).length
        && Object.entries(run.input.parameters).every(([key, value]) => JSON.stringify(value) === JSON.stringify(item.parameters[key])));
    const run = exactSettings ? [...known].sort((a, b) => recency(b).localeCompare(recency(a)))[0] : undefined;
    const key = exactSettings ? configuration(run!) : undefined;
    if (key && !item.research_integrity_error) importedConfigurations.add(key);
    if (exactSettings && ids.length === 1 && !item.research_integrity_error
      && item.coverage?.length === 1 && item.coverage[0].start === run!.input.start
      && item.coverage[0].end === run!.input.end && !item.latest_replay) importedExactRuns.add(ids[0]);
    representedScripts.add(strategyId);
    candidates.push({ strategyId, name: strategy.name, symbol: item.symbol, timeframe: item.timeframe, item, run, status,
      pnl: finite(item.net_pnl) ? item.net_pnl : null,
      chart: item.chart_points?.filter(finite) || runChart(run), date: run ? recency(run) : item.end,
      score: metricScore(run), trades: finite(item.trades) ? item.trades : 0 });
  }

  for (const run of runs) {
    const strategy = scripts.get(run.input.strategy.id);
    if (!strategy || !isPortfolioBaselineRun(run)) continue;
    representedScripts.add(strategy.id);
    if (includeEveryRun ? importedExactRuns.has(run.id) : importedConfigurations.has(configuration(run))) continue;
    const status = statuses.byRun.get(run.id) || (isCurrentStrategyRun(run, strategy)
      ? lifecycleStatus("needs-review", 0, "Research status is unavailable.", [], { kind: "inspect-run", label: "Review run", runId: run.id })
      : lifecycleStatus("retest-required", 0, "The current script needs retesting.", [], { kind: "configure-run", label: "Retest", strategyId: strategy.id }));
    const metrics = run.result?.metrics;
    candidates.push({ strategyId: strategy.id, name: strategy.name, symbol: run.input.dataset.symbol, timeframe: run.input.timeframe,
      run, status, pnl: finite(metrics?.net_pnl) ? metrics.net_pnl : null, chart: runChart(run), date: recency(run),
      score: metricScore(run), trades: finite(metrics?.trades) ? metrics.trades : 0 });
  }

  for (const strategy of scripts.values()) {
    if (representedScripts.has(strategy.id)) continue;
    candidates.push({ strategyId: strategy.id, name: strategy.name, symbol: "", timeframe: "", pnl: null, chart: [], date: "",
      status: lifecycleStatus("not-tested", 0, "No baseline history is available.", [], { kind: "configure-run", label: "Start research", strategyId: strategy.id }),
      score: null, trades: 0 });
  }

  return candidates.filter(candidate => matches(candidate, filters)).sort(compareCandidates);
}

/** One ranked representative per script for existing summary surfaces. */
export function portfolioScriptCandidates(
  strategies: Strategy[], catalog: CollectiveCatalog, runs: RunSummary[],
  statuses: ReturnType<typeof strategyStageStatuses>, filters: Filters = {},
): PortfolioScriptCandidate[] {
  const selected = new Map<string, PortfolioScriptCandidate>();
  for (const candidate of collectCandidates(strategies, catalog, runs, statuses, filters, false)) {
    if (selected.has(candidate.strategyId)) continue;
    const { strategyId, name, symbol, timeframe, item, run, status, pnl, chart, date } = candidate;
    selected.set(strategyId, { strategyId, name, symbol, timeframe, item, run, status, pnl, chart, date });
  }
  return [...selected.values()];
}

/** The Add picker retains every exact history; ranking only orders the options. */
export function portfolioScriptGroups(
  strategies: Strategy[], catalog: CollectiveCatalog, runs: RunSummary[],
  statuses: ReturnType<typeof strategyStageStatuses>, filters: Filters = {},
): PortfolioScriptGroup[] {
  const groups = new Map<string, PortfolioScriptGroup>();
  for (const candidate of collectCandidates(strategies, catalog, runs, statuses, filters, true)) {
    const group = groups.get(candidate.strategyId) || { strategyId: candidate.strategyId, name: candidate.name, options: [] };
    const { strategyId, name, symbol, timeframe, item, run, status, pnl, chart, date } = candidate;
    group.options.push({ strategyId, name, symbol, timeframe, item, run, status, pnl, chart, date });
    groups.set(candidate.strategyId, group);
  }
  return [...groups.values()];
}

/** New selections replace overlapping variants without rewriting saved combinations. */
export function selectPortfolioHistory(
  copies: Record<string, number>, catalog: CollectiveCatalog, runs: RunSummary[],
  chosen: CollectiveItem, strategyId: string,
): Record<string, number> {
  const next = { ...copies };
  for (const item of catalog.items) {
    if (item.id !== chosen.id && item.symbol === chosen.symbol && item.timeframe === chosen.timeframe
      && portfolioItemStrategyId(item, runs) === strategyId) delete next[item.id];
  }
  next[chosen.id] = 1;
  return next;
}

export function portfolioItemStrategyId(item: CollectiveItem, runs: RunSummary[]): string {
  const byRun = new Map(runs.map(run => [run.id, run.input.strategy.id]));
  const linked = new Set((item.source_run_ids || []).map(id => byRun.get(id)).filter(Boolean));
  return linked.size === 1 ? [...linked][0]! : item.key.split("__")[0];
}

export function exactPortfolioItemForRun(catalog: CollectiveCatalog, run: RunSummary): CollectiveItem | undefined {
  return catalog.items.find(item => item.source_run_ids?.length === 1 && item.source_run_ids[0] === run.id
    && item.coverage?.length === 1 && item.coverage[0].start === run.input.start
    && item.coverage[0].end === run.input.end && !item.latest_replay && !item.research_integrity_error);
}
