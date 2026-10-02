import type { CollectiveCatalog, CollectiveItem } from "./portfolio.ts";
import type { RunSummary } from "./workbenchModels.ts";
import { strategyStageLabels, type StrategyStageKind } from "./strategyLifecycle.ts";
import type { StrategyStageStatus } from "./strategyLifecycle.ts";
import { runConfigurationKey } from "./evidence.ts";

export type PortfolioCandidateGroup = StrategyStageKind;
export type PortfolioPickerTab = "passed" | "progress" | "failed";
export function portfolioPickerTab(kind: StrategyStageKind): PortfolioPickerTab {
  if (kind === "failed-checks") return "failed";
  return ["evaluation-passed", "robustness-validated", "forward-testing", "forward-tested", "practical-ready", "benchmark"].includes(kind) ? "passed" : "progress";
}
export function portfolioStageRank(status: StrategyStageStatus) {
  if (status.kind === "benchmark") return -1;
  return status.kind === "failed-checks" ? status.failedStage || Math.min(5, status.stage + 1) : status.stage;
}
export function comparePortfolioCandidates(left: { status: StrategyStageStatus; score?: number | null; trades?: number; date?: string }, right: { status: StrategyStageStatus; score?: number | null; trades?: number; date?: string }) {
  return portfolioStageRank(right.status) - portfolioStageRank(left.status)
    || (right.score ?? -Infinity) - (left.score ?? -Infinity)
    || (right.trades ?? 0) - (left.trades ?? 0)
    || (right.date || "").localeCompare(left.date || "");
}
export const portfolioCandidateGroups = ["not-tested", "backtest-running", "validation-pending", "evaluation-running", "evaluation-passed", "robustness-validated", "forward-testing", "forward-tested", "practical-ready", "failed-checks", "retest-required", "needs-review", "benchmark"] as const;
export const portfolioCandidateLabels = strategyStageLabels;
export const portfolioCandidateDescriptions: Record<PortfolioCandidateGroup, string> = {
  "not-tested": "Complete a development backtest before planning an evaluation.",
  "backtest-running": "Development simulations are queued or running. Review the results before evaluating.",
  "validation-pending": "Development backtests are complete. Next, test later data with declared baseline and stress checks.",
  "evaluation-running": "Later-period evaluation checks are queued, running or being summarized. A pass is not established yet.",
  "evaluation-passed": "All declared evaluation checks passed for the current source and settings. Robustness is a separate milestone; an evaluation pass does not mean thoroughly tested.",
  "robustness-validated": "Robustness and execution evidence has been reviewed. Next, freeze a prospective paper-testing plan before collecting new observations.",
  "forward-testing": "A prospective paper-testing plan is frozen. Record and reconcile new observations against its criteria.",
  "forward-tested": "Recorded prospective observations met the frozen criteria. Complete the practical operating review next.",
  "practical-ready": "All five development stages are recorded for these settings, including forward testing and acceptance of the practical operating checklist. Inspect the evidence and its scope before use.",
  "failed-checks": "Matching checks failed. Review the findings, revise the strategy or settings, and retest.",
  "retest-required": "The execution source changed. Retest the current version before relying on earlier results.",
  "needs-review": "Missing links, execution errors, zero-trade results or incomplete evidence need review.",
  benchmark: "Passive comparison histories are shown separately from strategy development.",
};

/** The picker is a candidate shortlist, while the full catalog remains preserved. */
export function portfolioCandidateGroup(item: CollectiveItem): PortfolioCandidateGroup {
  if (item.research_integrity_error) return "needs-review";
  if (item.benchmark) return "benchmark";
  return item.research_status?.kind || "needs-review";
}

export function canAddPortfolioCandidate(item: CollectiveItem) {
  // Portfolio membership is a user choice. Validation stage is shown in Research;
  // any intact recorded history can be combined, including a losing history.
  return !item.research_integrity_error;
}

export function portfolioCandidateKey(item: CollectiveItem) {
  return JSON.stringify([item.key.split("__")[0], item.symbol, item.timeframe, item.session,
    Object.entries(item.parameters).sort(([left], [right]) => left.localeCompare(right))]);
}

/** Keep blocked and unfinished research visible. Deduplicate baselines within
 * each stage so an older-source blocker cannot disappear behind a current pass. */
export function portfolioCandidateShortlists(catalog: CollectiveCatalog | null) {
  const groups = Object.fromEntries(portfolioCandidateGroups.map(group => [group, [] as CollectiveItem[]])) as Record<PortfolioCandidateGroup, CollectiveItem[]>;
  const candidates = [...(catalog?.items || [])];
  candidates.sort((left, right) => portfolioCandidateGroups.indexOf(portfolioCandidateGroup(left)!) - portfolioCandidateGroups.indexOf(portfolioCandidateGroup(right)!)
    || right.end.localeCompare(left.end) || left.start.localeCompare(right.start) || left.id.localeCompare(right.id));
  const seen = new Set<string>();
  for (const item of candidates) {
    const key = JSON.stringify([portfolioCandidateGroup(item), portfolioCandidateKey(item)]);
    if (seen.has(key)) continue;
    seen.add(key);
    groups[portfolioCandidateGroup(item)!].push(item);
  }
  for (const group of portfolioCandidateGroups) groups[group].sort((left, right) => left.name.localeCompare(right.name) || left.symbol.localeCompare(right.symbol) || left.timeframe.localeCompare(right.timeframe));
  return groups;
}

/** Research must appear before an import exists, including first queued runs. */
export function portfolioResearchCandidates(catalog: CollectiveCatalog, runs: RunSummary[], statuses: { byRun: Map<string, StrategyStageStatus> }) {
  const linkedIds = new Set(catalog.items.flatMap(item => item.source_run_ids || []));
  const key = (run: RunSummary) => JSON.stringify([run.input.strategy.id, runConfigurationKey(run)]);
  const represented = new Set(runs.filter(run => linkedIds.has(run.id)).map(key));
  const seen = new Set<string>();
  return [...runs].sort((a, b) => b.created_at.localeCompare(a.created_at)).filter(run => {
    const configuration = key(run);
    if (!statuses.byRun.has(run.id) || represented.has(configuration) || seen.has(configuration)) return false;
    seen.add(configuration);
    return true;
  });
}

export function portfolioSourceVersionNote(item: CollectiveItem, runs: RunSummary[]) {
  const linked = runs.filter(run => item.source_run_ids?.includes(run.id));
  const versions = [...new Set(linked.map(run => run.input.execution_source_hash || run.input.source_hash || run.input.strategy.execution_source_hash || run.input.strategy.file_hash).filter(Boolean))];
  const recorded = versions.length ? `Recorded source ${versions.map(hash => hash.slice(0, 12)).join(", ")}.` : "Recorded source version is unavailable.";
  return `${recorded} ${item.research_status?.kind === "retest-required" ? "The current source needs retesting." : "Current-source validation is not established; review the history linkage."}`;
}
