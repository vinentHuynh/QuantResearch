import { useMemo, type ReactNode } from "react";
import { Button, Text, Tooltip } from "@mantine/core";
import { strategyStageStatuses } from "../../../shared/ts/stageStatus.ts";
import { statusDisplay, type StrategyNextAction, type StrategyStageKind, type StrategyStageStatus } from "../../../shared/ts/strategyLifecycle.ts";
import type { StageAssessment } from "../../../shared/ts/stageAssessments.ts";
import { firstSentence } from "../../../shared/ts/formatting.ts";
import { stageColor, stageLabel, researchStages, type ResearchStage } from "../../../shared/ts/progress.ts";
import type { WorkbenchState } from "../../features/workspace/workbenchModel";
import { StrategyStageContext, useStrategyStages } from "./strategyStageContext";
import { href } from "../../app/navigation";

export function StrategyStageProvider({ state, onAction, children }: { state: WorkbenchState | null; onAction?: (action: StrategyNextAction) => void; children: ReactNode }) {
  const statuses = useMemo(() => state
    ? strategyStageStatuses(state.strategies, state.runs, state.evaluations || [])
    : { byRun: new Map<string, StrategyStageStatus>(), byEvaluation: new Map<string, StrategyStageStatus>(), configurations: new Map<string, StrategyStageStatus>() }, [state]);
  return <StrategyStageContext.Provider value={{ statuses, onAction }}>{children}</StrategyStageContext.Provider>;
}

export function StrategyStageBadge({ stage, label, finding, color, checks = [], action, showFinding = false, showAction = false, compact = false, kind, blockedStage, failedStage, tracking, assessment }: {
  stage: ResearchStage; label?: string; finding?: string; color?: string; checks?: string[]; action?: StrategyNextAction; showFinding?: boolean; showAction?: boolean; compact?: boolean;
  kind?: StrategyStageKind; blockedStage?: ResearchStage; failedStage?: ResearchStage; tracking?: boolean; assessment?: StageAssessment;
}) {
  // Stored labels stay unchanged; screens show the shared "stage · state" wording.
  const display = kind ? statusDisplay({ kind, stage, blockedStage, failedStage, tracking }) : null;
  const text = display?.label || label || stageLabel(stage);
  const description = finding || display?.description || (stage ? researchStages[stage - 1].description : "No completed backtest is recorded for this configuration.");
  return <div className="wb-strategy-stage" aria-label={`Strategy stage: ${text}`}>
    <Tooltip label={description} multiline w={300} withArrow>
      <span className={`wb-status-chip wb-stage-badge is-${display?.state || "plain"}`} data-color={display?.color || color || stageColor(stage)}>{text}</span>
    </Tooltip>
    {showFinding && display?.state !== "tracking" && <ResearchNote finding={finding || ""} checks={checks} assessment={assessment} compact={compact} />}
    {showAction && action && <StrategyNextActionButton action={action} />}
  </div>;
}

/** A research note in scan order: summary, open checks, reviewer, then the full findings collapsed. */
export function ResearchNote({ finding, checks = [], assessment, compact = false }: { finding: string; checks?: string[]; assessment?: StageAssessment; compact?: boolean }) {
  const summary = assessment?.summary?.trim() || firstSentence(finding);
  // Dense lists (the run table) keep one line per row; the full note lives on the run and strategy pages.
  if (compact) return summary || checks.length ? <Text size="xs" c="dimmed" mt={3} className="wb-note-compact">
    {summary}{checks.length > 0 && <>{summary ? " · " : ""}<strong>{checks.length} open check{checks.length === 1 ? "" : "s"}</strong></>}
  </Text> : null;
  const hasMore = finding.trim().length > summary.length;
  if (!summary && !checks.length) return null;
  return <div className="wb-research-note">
    {summary && <Text size="sm" fw={500} className="wb-note-summary">{summary}</Text>}
    {checks.length > 0 && <div className="wb-note-checks">
      <Text size="xs" fw={700} c="dimmed" className="wb-note-label">Open checks · {checks.length}</Text>
      <ul>{checks.map((check, index) => <li key={index}><Text size="xs" span>{check}</Text></li>)}</ul>
    </div>}
    {assessment && <Text size="xs" c="dimmed">Reviewed by {assessment.reviewer} · {assessment.recordedAt.slice(0, 10)}</Text>}
    {hasMore && <details className="wb-note-findings"><summary>Full findings</summary><Text size="xs" mt={4}>{finding}</Text></details>}
  </div>;
}

export function StrategyNextActionButton({ action }: { action: StrategyNextAction }) {
  const { onAction } = useStrategyStages();
  return onAction ? <Button className="wb-stage-action" size="compact-xs" variant="subtle" mt={4} onClick={event => { event.stopPropagation(); onAction(action); }}>{action.label}</Button>
    : <Button className="wb-stage-action" size="compact-xs" variant="subtle" mt={4} component="a" href={action.kind === "plan-evaluation" ? href("evaluations", `plan~${action.runId}`) : action.kind === "open-portfolio" ? href("portfolio") : action.runId ? href("runs", action.runId) : href("scripts", "library")}>{action.label}</Button>;
}

export function RunStageBadge({ runId, showFinding = false, showAction = showFinding, compact = false }: { runId: string; showFinding?: boolean; showAction?: boolean; compact?: boolean }) {
  const status = useStrategyStages().statuses.byRun.get(runId);
  return status ? <StrategyStageBadge {...status} showFinding={showFinding} showAction={showAction} compact={compact} /> : <Text size="xs" c="dimmed">Stage loading…</Text>;
}

export function EvaluationStageBadge({ evaluationId, showFinding = false }: { evaluationId: string; showFinding?: boolean }) {
  const status = useStrategyStages().statuses.byEvaluation.get(evaluationId);
  return status ? <StrategyStageBadge {...status} showFinding={showFinding} /> : <Text size="xs" c="dimmed">Stage loading…</Text>;
}
