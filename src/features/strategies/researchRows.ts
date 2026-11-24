import { useMemo } from "react";
import type { RunSummary, Strategy } from "../../../shared/ts/workbenchModels.ts";
import { runConfigurationKey, testingEvidence } from "../../../shared/ts/evidence.ts";
import { lifecycleStatus, statusDisplay, type StrategyStageStatus } from "../../../shared/ts/strategyLifecycle.ts";
import { isCurrentStrategyRun } from "../../../shared/ts/stageStatus.ts";
import { isConfigurationArchived } from "../../../shared/ts/researchArchive.ts";
import { strategySourceTags } from "../../../shared/ts/formatting.ts";
import type { WorkbenchState } from "../workspace/workbenchModel";

type Configuration = ReturnType<typeof testingEvidence>["configurations"][number];

/** One strategy tested in one market, timeframe and session. */
export type ResearchRow = {
  id: string;
  strategy: Strategy;
  config?: Configuration;
  status: StrategyStageStatus;
  archived: boolean;
};

export function researchRows(state: WorkbenchState): ResearchRow[] {
  return state.strategies
    .flatMap<ResearchRow>((strategy) => {
      const evidence = testingEvidence(strategy, state.runs, state.evaluations || []);
      if (!evidence.configurations.length)
        return [{
          id: strategy.id,
          strategy,
          config: undefined,
          archived: false,
          status: lifecycleStatus("not-tested", 0, "No backtest recorded.", [], {
            kind: "configure-run",
            label: "Configure backtest",
            strategyId: strategy.id,
          }),
        }];
      return evidence.configurations.map((config) => ({
        id: `${strategy.id}:${config.key}`,
        strategy,
        config,
        status: config.lifecycle,
        archived: isConfigurationArchived(strategy.id, config.key, state.research_archive),
      }));
    })
    .sort((a, b) => b.status.stage - a.status.stage || a.strategy.name.localeCompare(b.strategy.name));
}

export function useResearchRows(state: WorkbenchState | null) {
  return useMemo(() => (state ? researchRows(state) : []), [state]);
}

/** Every recorded attempt of a configuration on current strategy code. */
export function rowAttempts(state: WorkbenchState, row: ResearchRow): RunSummary[] {
  if (!row.config) return [];
  return state.runs
    .filter((run) =>
      run.input.strategy.id === row.strategy.id &&
      isCurrentStrategyRun(run, row.strategy) &&
      runConfigurationKey(run) === row.config?.key)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function rowEvaluations(state: WorkbenchState, attempts: RunSummary[]) {
  const ids = new Set(attempts.map((run) => run.id));
  return (state.evaluations || []).filter((evaluation) =>
    evaluation.folds.some((fold) => [...fold.training, ...fold.tests].some((id) => ids.has(id))));
}

export type RowGroupId = "ready" | "forward" | "robustness" | "evaluate" | "rerun" | "untested" | "failed" | "tracking" | "benchmark";

export const rowGroups: { id: RowGroupId; title: string; hint: string }[] = [
  { id: "ready", title: "Ready", hint: "Passed every stage. Keep tracking them in the portfolio." },
  { id: "forward", title: "In forward testing", hint: "A frozen paper test is running or ready to review." },
  { id: "robustness", title: "At robustness", hint: "Passed evaluation. Clear the open checks to pass robustness." },
  { id: "evaluate", title: "Ready to evaluate", hint: "Backtested. Plan an evaluation on later data, with pass criteria set first." },
  { id: "rerun", title: "Needs a rerun", hint: "Made with older code or not linked to a research run. Rerun before trusting the numbers." },
  { id: "untested", title: "Not tested yet", hint: "No backtest recorded. Configure one to start." },
  { id: "failed", title: "Failed", hint: "Failed checks that were set before the test. Revise the rules or archive." },
  { id: "tracking", title: "Tracking", hint: "Exploratory continuations kept up to date for the portfolio." },
  { id: "benchmark", title: "Benchmarks", hint: "Reference strategies to compare against." },
];

/** Which group a row belongs to: what it needs next. */
export function rowGroup(row: ResearchRow): RowGroupId {
  const display = statusDisplay(row.status);
  if (display.state === "benchmark") return "benchmark";
  if (display.state === "tracking") return "tracking";
  if (display.state === "failed") return "failed";
  if (display.state === "rerun") return "rerun";
  if (row.status.kind === "not-tested") return "untested";
  if (display.state === "ready") return "ready";
  if (display.stage >= 4) return "forward";
  if (display.stage === 3) return "robustness";
  return "evaluate";
}

export function rowMeta(row: ResearchRow, attempts: number) {
  const tags = strategySourceTags(row.strategy.name);
  return [
    row.config ? `${row.config.symbol} ${row.config.timeframe}` : row.strategy.timeframes.join(" · "),
    ...tags,
    row.config ? `${attempts} ${attempts === 1 ? "attempt" : "attempts"}` : "",
  ].filter(Boolean).join(" · ");
}

