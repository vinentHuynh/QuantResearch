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
  /** Portfolio continuation runs: shown as Tracking, never as research evidence. */
  tracking?: boolean;
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

// Presentation vocabulary. Kinds, `label` and API payloads above stay as they
// are; screens show this two-part label instead: the stage a configuration is
// on, and what is happening there.
export type StatusState = "next" | "running" | "blocked" | "rerun" | "failed" | "ready" | "benchmark" | "tracking";
export const statusStageNames = ["Backtest", "Evaluation", "Robustness", "Forward test", "Ready"] as const;
export const statusStateLabels: Record<StatusState, string> = {
  next: "Next up", running: "Running", blocked: "Blocked", rerun: "Needs rerun", failed: "Failed", ready: "Ready", benchmark: "Benchmark", tracking: "Tracking",
};
const statusStateColors: Record<StatusState, string> = {
  next: "blue", running: "cyan", blocked: "orange", rerun: "grape", failed: "red", ready: "green", benchmark: "gray", tracking: "gray",
};
export const statusStateDescriptions: Record<StatusState, string> = {
  next: "The next step is ready to start.",
  running: "A backtest, evaluation or forward test is in progress.",
  blocked: "This stage was attempted and open checks remain.",
  rerun: "Evidence isn't current: the code changed, the history isn't linked to a research run, or runs need repair.",
  failed: "It failed a check that was declared before the test.",
  ready: "Passed all five stages.",
  benchmark: "Kept for comparison only. No stage.",
  tracking: "Portfolio continuation. It doesn't count as research evidence.",
};
export type StatusDisplay = { state: StatusState; stage: ResearchStage; stageName: string; stateLabel: string; label: string; color: string; description: string };
type StatusDisplayInput = Pick<StrategyStageStatus, "kind" | "stage"> & Partial<Pick<StrategyStageStatus, "blockedStage" | "failedStage" | "tracking">>;

export function statusDisplay(status: StatusDisplayInput): StatusDisplay {
  const plain = (state: StatusState): StatusDisplay => ({ state, stage: status.stage, stageName: "", stateLabel: statusStateLabels[state], label: statusStateLabels[state], color: statusStateColors[state], description: statusStateDescriptions[state] });
  const at = (stage: number, state: StatusState): StatusDisplay => {
    const on = Math.min(5, Math.max(1, stage)) as 1 | 2 | 3 | 4 | 5;
    const stageName = statusStageNames[on - 1];
    return { state, stage: on, stageName, stateLabel: statusStateLabels[state], label: state === "ready" ? "Ready" : `${stageName} · ${statusStateLabels[state]}`, color: statusStateColors[state], description: statusStateDescriptions[state] };
  };
  if (status.kind === "benchmark") return plain("benchmark");
  if (status.tracking) return plain("tracking");
  switch (status.kind) {
    case "not-tested": return at(1, "next");
    case "backtest-running": return at(1, "running");
    case "validation-pending": return at(2, "next");
    case "evaluation-running": return at(2, "running");
    case "failed-checks": return at(status.failedStage || status.stage + 1, "failed");
    case "retest-required": return at(1, "rerun");
    case "needs-review": return status.blockedStage ? at(status.blockedStage, "blocked") : at(1, "rerun");
    case "evaluation-passed": return at(3, "next");
    case "robustness-validated": return at(4, "next");
    case "forward-testing": return at(4, "running");
    case "forward-tested": return at(5, "next");
    case "practical-ready": return at(5, "ready");
    default: return at(1, "rerun");
  }
}

/** Filter wording for the lifecycle kinds, in the same vocabulary as statusDisplay. */
export const statusFilterLabels: Record<StrategyStageKind, string> = {
  "not-tested": "Backtest · Next up", "backtest-running": "Backtest · Running", "validation-pending": "Evaluation · Next up", "evaluation-running": "Evaluation · Running",
  "failed-checks": "Failed", "retest-required": "Needs rerun · code changed", "needs-review": "Blocked, or needs rerun", "evaluation-passed": "Robustness · Next up",
  "robustness-validated": "Forward test · Next up", "forward-testing": "Forward test · Running", "forward-tested": "Ready · Next up", "practical-ready": "Ready", benchmark: "Benchmark",
};

/** A pass on one configuration never conceals obsolete or failing evidence on another. */
export function combinedLifecycleStatus(statuses: StrategyStageStatus[], action?: StrategyNextAction): StrategyStageStatus {
  const order: StrategyStageKind[] = ["retest-required", "failed-checks", "needs-review", "not-tested", "backtest-running", "evaluation-running", "validation-pending", "evaluation-passed", "robustness-validated", "forward-testing", "forward-tested", "practical-ready", "benchmark"];
  const selected = [...statuses].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind))[0];
  if (!selected) return lifecycleStatus("needs-review", 0, "No linked configuration evidence is available.", ["Link the recorded baseline runs."], action);
  return { ...selected, checks: [...new Set(statuses.flatMap(status => status.checks))], action: action || selected.action };
}
