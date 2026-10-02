import type { CollectiveItem } from "./portfolio.ts";
import type { DashboardRow } from "./dashboard.ts";

// Milestones describe evidence for a configuration, never an entire adapter's
// profitability. Execution and review are independent of these milestones.
export type ResearchStage = 0 | 1 | 2 | 3 | 4 | 5;
export const researchStages = [
  { stage: 1, label: "Development backtest", description: "Research rules and settings on development data. Completing a simulation establishes historical execution." },
  { stage: 2, label: "Historical evaluation passed", description: "Every declared historical evaluation check passed for the current source and settings. Next: robustness and execution validation." },
  { stage: 3, label: "Robustness and execution validated", description: "A named reviewer recorded evidence for parameter sensitivity, market/regime coverage, realistic execution and costs, and risk/capital limits." },
  { stage: 4, label: "Forward testing", description: "Freeze a prospective paper-testing plan before its test window. Record and reconcile new observations against the predeclared criteria." },
  { stage: 5, label: "Ready for practical use", description: "The forward test met its frozen criteria and a named reviewer accepted the operating plan, risk controls, monitoring and execution setup for this configuration." },
] as const;
export const stageLabel = (stage: ResearchStage) => stage ? researchStages[stage - 1].label : "Not backtested";
export const stageColor = (stage: ResearchStage) => stage >= 2 ? "teal" : stage ? "blue" : "gray";
export const progressScope = "Progress belongs to a source version, symbol, timeframe, session and parameter configuration. A failure on another configuration does not invalidate a passing one.";

export function collectiveProgress(item: CollectiveItem) {
  if (item.research_status) return { ...item.research_status, next: item.research_status.checks.join(" ") || item.research_status.finding };
  const stage: ResearchStage = 1;
  return {
    stage,
    label: item.benchmark ? "Benchmark" : "Needs review",
    next: item.benchmark ? "Use as a comparison reference."
      : "Link this imported history to the exact current research configuration before assigning its stage.",
  };
}

export function scorecardStage(row: DashboardRow): ResearchStage {
  if (row.status === "Retest required") return 0;
  if (row.status === "Research candidate") return 2;
  return row.scenarios.length ? 1 : 0;
}
