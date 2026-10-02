import { runConfigurationKey, testingEvidence } from "./evidence.ts";
import { combinedLifecycleStatus, lifecycleStatus, type StrategyStageStatus } from "./strategyLifecycle.ts";
import type { EvaluationView, RunSummary, Strategy } from "./workbenchModels.ts";
import type { CollectiveItem } from "./portfolio.ts";
import type { DashboardRow } from "./dashboard.ts";
export type { StrategyStageStatus } from "./strategyLifecycle.ts";

export function isCurrentStrategyRun(run: RunSummary, strategy?: Pick<Strategy, "id" | "file_hash" | "execution_source_hash">) {
  return !!strategy && run.input.strategy.id === strategy.id && (run.input.protocol === 2
    ? (run.input.execution_source_hash || run.input.source_hash || run.input.strategy.execution_source_hash || run.input.strategy.file_hash) === (strategy.execution_source_hash || strategy.file_hash)
    : run.input.strategy.file_hash === strategy.file_hash);
}

/** Display the configuration's evidence milestone independently of run purpose
 * and execution status. Use the same calculation as Scripts & library. */
export function strategyStageStatuses(strategies: Pick<Strategy, "id" | "file_hash" | "execution_source_hash">[], runs: RunSummary[], evaluations: EvaluationView[]) {
  const configurations = new Map<string, StrategyStageStatus>();
  for (const strategy of strategies) {
    const evidence = testingEvidence(strategy, runs, evaluations);
    for (const config of evidence.configurations) {
      configurations.set(JSON.stringify([strategy.id, config.key]), config.lifecycle);
    }
  }
  const byRun = new Map<string, StrategyStageStatus>();
  for (const run of runs) {
    if (run.input.portfolio_replay) {
      byRun.set(run.id, lifecycleStatus("needs-review", 1,
        "Exploratory portfolio continuation; earlier research milestones do not validate these later dates."));
      continue;
    }
    if (run.input.strategy.id === "buy-hold") {
      byRun.set(run.id, lifecycleStatus("benchmark", run.status === "Succeeded" ? 1 : 0, "Passive comparison benchmark; not a strategy advancement stage."));
      continue;
    }
    const strategy = strategies.find((candidate) => candidate.id === run.input.strategy.id);
    byRun.set(run.id, (isCurrentStrategyRun(run, strategy) && configurations.get(JSON.stringify([run.input.strategy.id, runConfigurationKey(run)]))) || lifecycleStatus("retest-required", 0,
      "The tested execution source differs from the current strategy, or its adapter is no longer registered.",
      ["Backtest the current source, then complete its declared evaluation."],
      strategy ? { kind: "configure-run", label: "Retest current source", runId: run.id, strategyId: strategy.id }
        : { kind: "find-source", label: "Find strategy source" }));
  }
  const byEvaluation = new Map<string, StrategyStageStatus>();
  for (const evaluation of evaluations) {
    const ids = [...new Set(evaluation.folds.flatMap(fold => fold.tests))];
    const statuses = ids.map(id => byRun.get(id) || lifecycleStatus("needs-review", 0, "A declared evaluation run is missing.", [`Restore or rerun missing child ${id}.`]));
    byEvaluation.set(evaluation.id, combinedLifecycleStatus(statuses, { kind: "open-evaluation", label: "Review evaluation", evaluationId: evaluation.id }));
  }
  return { byRun, byEvaluation, configurations };
}

export function portfolioStageStatus(item: CollectiveItem, runs: RunSummary[], statuses: ReturnType<typeof strategyStageStatuses>): StrategyStageStatus {
  if (item.research_integrity_error) return lifecycleStatus("needs-review", 1, item.research_integrity_error, ["Repair or refresh the verified history."]);
  if (item.benchmark) return lifecycleStatus("benchmark", 1, "Passive comparison history; excluded from strategy advancement.");
  const ids = item.source_run_ids || [];
  if (!ids.length) return lifecycleStatus("needs-review", 1,
    "This imported history is not linked to current research runs. Saved historical eligibility does not establish a current pass.",
    ["Link the exact source version, market, timeframe, session and parameters to research runs."], { kind: "find-source", label: "Find source & configure research" });
  const linked = ids.map(id => runs.find(run => run.id === id));
  if (linked.some(run => !run)) return lifecycleStatus("needs-review", 1, "Some source runs for this history are missing.", ["Restore or rerun the missing source records."], { kind: "find-source", label: "Find strategy source" });
  const known = linked.filter((run): run is RunSummary => !!run);
  const keys = new Set(known.map(run => JSON.stringify([run.input.strategy.id, runConfigurationKey(run)])));
  const sameSettings = known.every(run => run.input.dataset.symbol === item.symbol && run.input.timeframe === item.timeframe && run.input.session === item.session
    && Object.keys(run.input.parameters).length === Object.keys(item.parameters).length
    && Object.entries(run.input.parameters).every(([key, value]) => JSON.stringify(value) === JSON.stringify(item.parameters[key])));
  if (keys.size !== 1 || !sameSettings) return lifecycleStatus("needs-review", 1,
    "This history combines different source versions or settings. Review its linked configurations separately.", ["Choose or import a baseline for one exact configuration."], { kind: "inspect-run", label: "Review source configuration", runId: known[0].id });
  return combinedLifecycleStatus(ids.map(id => statuses.byRun.get(id)!).filter(Boolean));
}

export function scorecardLifecycle(row: DashboardRow, statuses: ReturnType<typeof strategyStageStatuses>) {
  if (row.status === "Benchmark") return lifecycleStatus("benchmark", 1, "Passive comparison benchmark.");
  return (row.evaluation_id && statuses.byEvaluation.get(row.evaluation_id)) || lifecycleStatus("not-tested", 0, "No linked evaluation for these scorecard settings.", ["Choose a backtest configuration and plan an evaluation."], { kind: "find-source", label: "Choose research configuration" });
}
