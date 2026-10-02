import type { ResearchStage } from "./progress.ts";

export type StrategyStageKind = "not-tested" | "backtest-running" | "validation-pending" | "evaluation-running" | "failed-checks" | "retest-required" | "needs-review" | "evaluation-passed" | "robustness-validated" | "forward-testing" | "forward-tested" | "practical-ready" | "benchmark";
export type StrategyNextAction = {
  kind: "configure-run" | "plan-evaluation" | "open-evaluation" | "inspect-run" | "review-readiness" | "open-portfolio" | "find-source";
  label: string;
  runId?: string;
  evaluationId?: string;
  strategyId?: string;
};
export type StrategyStageStatus = {
  kind: StrategyStageKind;
  stage: ResearchStage;
  label: string;
  color: string;
  finding: string;
  checks: string[];
  action?: StrategyNextAction;
  readiness?: import("./readiness.ts").ReadinessReview;
  failedStage?: ResearchStage;
  blockedStage?: ResearchStage;
  assessment?: import("./stageAssessments.ts").StageAssessment;
};
export const strategyStageLabels: Record<StrategyStageKind, string> = {
  "not-tested": "Not backtested", "backtest-running": "Backtest in progress", "validation-pending": "Backtested · awaiting evaluation", "evaluation-running": "Evaluation in progress", "failed-checks": "Failed checks · revise strategy",
  "retest-required": "Retest required", "needs-review": "Needs review", "evaluation-passed": "Historical evaluation passed",
  "robustness-validated": "Robustness and execution validated", "forward-testing": "Forward testing",
  "forward-tested": "Forward testing complete · readiness review needed", "practical-ready": "Ready for practical use", benchmark: "Benchmark",
};
export function lifecycleStatus(kind: StrategyStageKind, stage: ResearchStage, finding: string, checks: string[] = [], action?: StrategyNextAction): StrategyStageStatus {
  return { kind, stage, label: strategyStageLabels[kind], color: kind === "practical-ready" ? "green" : ["evaluation-passed", "robustness-validated", "forward-tested"].includes(kind) ? "teal" : kind === "failed-checks" ? "red" : ["needs-review", "retest-required"].includes(kind) ? "orange" : ["validation-pending", "backtest-running", "evaluation-running", "forward-testing"].includes(kind) ? "blue" : "gray", finding, checks, action };
}

/** A pass on one configuration never conceals obsolete or failing evidence on another. */
export function combinedLifecycleStatus(statuses: StrategyStageStatus[], action?: StrategyNextAction): StrategyStageStatus {
  const order: StrategyStageKind[] = ["retest-required", "failed-checks", "needs-review", "not-tested", "backtest-running", "evaluation-running", "validation-pending", "evaluation-passed", "robustness-validated", "forward-testing", "forward-tested", "practical-ready", "benchmark"];
  const selected = [...statuses].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind))[0];
  if (!selected) return lifecycleStatus("needs-review", 0, "No linked configuration evidence is available.", ["Link the recorded baseline runs."], action);
  return { ...selected, checks: [...new Set(statuses.flatMap(status => status.checks))], action: action || selected.action };
}
