import type { CollectiveItem } from "./portfolio.ts";
import type { DashboardRow } from "./dashboard.ts";

// Milestones describe evidence for a configuration, never an entire adapter's
// profitability. Execution and review are independent of these milestones.
export type ResearchStage = 0 | 1 | 2 | 3;
export const researchStages = [
  { stage: 1, label: "Backtested", description: "A completed simulation is recorded. Profitability and validation are separate." },
  { stage: 2, label: "Evaluation passed", description: "Declared later-period baseline and stress checks passed, with no unresolved matching failures." },
  { stage: 3, label: "Robustness checked", description: "The historical execution and nearby-parameter checklist also passed." },
] as const;
export const stageLabel = (stage: ResearchStage) => stage ? researchStages[stage - 1].label : "Not tested";
export const stageColor = (stage: ResearchStage) => stage >= 2 ? "teal" : stage ? "blue" : "gray";
export const progressScope = "Progress belongs to a source version, symbol, timeframe, session and parameter configuration. A failure on another configuration does not invalidate a passing one.";

export function collectiveProgress(item: CollectiveItem) {
  const stage: ResearchStage = item.benchmark ? 1 : item.feasible && item.working ? 3 : item.working ? 2 : 1;
  return {
    stage,
    label: item.benchmark ? "Benchmark" : stageLabel(stage),
    next: item.benchmark ? "Use as a comparison reference."
      : stage === 3 ? "Track the frozen configuration on new data."
      : stage === 2 ? "Complete execution and nearby-parameter checks."
      : "Inspect recorded findings, then complete or repair the baseline and stress evaluation.",
  };
}

export function scorecardStage(row: DashboardRow): ResearchStage {
  if (row.status === "Retest required") return 0;
  if (row.status === "Research candidate") return 2;
  return row.scenarios.length ? 1 : 0;
}
