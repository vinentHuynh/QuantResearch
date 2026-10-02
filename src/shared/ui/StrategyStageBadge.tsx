import { useMemo, type ReactNode } from "react";
import { Badge, Button, Text, Tooltip } from "@mantine/core";
import { strategyStageStatuses } from "../../../shared/ts/stageStatus.ts";
import type { StrategyNextAction, StrategyStageStatus } from "../../../shared/ts/strategyLifecycle.ts";
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

export function StrategyStageBadge({ stage, label, finding, color, checks = [], action, showFinding = false, showAction = false }: {
  stage: ResearchStage; label?: string; finding?: string; color?: string; checks?: string[]; action?: StrategyNextAction; showFinding?: boolean; showAction?: boolean;
}) {
  const text = label || stageLabel(stage);
  const description = finding || (stage ? researchStages[stage - 1].description : "No completed backtest is recorded for this configuration.");
  return <div className="wb-strategy-stage" aria-label={`Strategy stage: ${text}`}>
    <Tooltip label={description} multiline w={300} withArrow>
      <Badge className="wb-stage-badge" color={color || stageColor(stage)} variant="light" radius="xs">{text}</Badge>
    </Tooltip>
    {showFinding && finding && <Text size="xs" c="dimmed" mt={3}>{finding}</Text>}
    {showFinding && checks.length > 0 && <details className="wb-stage-checks"><summary>Checks to complete ({checks.length})</summary>{checks.map((check, index) => <Text key={index} size="xs" mt={4}>{check}</Text>)}</details>}
    {showAction && action && <StrategyNextActionButton action={action} />}
  </div>;
}

export function StrategyNextActionButton({ action }: { action: StrategyNextAction }) {
  const { onAction } = useStrategyStages();
  return onAction ? <Button className="wb-stage-action" size="compact-xs" variant="subtle" mt={4} onClick={event => { event.stopPropagation(); onAction(action); }}>{action.label}</Button>
    : <Button className="wb-stage-action" size="compact-xs" variant="subtle" mt={4} component="a" href={action.kind === "plan-evaluation" ? href("evaluations", `plan~${action.runId}`) : action.kind === "open-portfolio" ? href("portfolio") : action.runId ? href("runs", action.runId) : href("scripts", "library")}>{action.label}</Button>;
}

export function RunStageBadge({ runId, showFinding = false, showAction = showFinding }: { runId: string; showFinding?: boolean; showAction?: boolean }) {
  const status = useStrategyStages().statuses.byRun.get(runId);
  return status ? <StrategyStageBadge {...status} showFinding={showFinding} showAction={showAction} /> : <Text size="xs" c="dimmed">Stage loading…</Text>;
}

export function EvaluationStageBadge({ evaluationId, showFinding = false }: { evaluationId: string; showFinding?: boolean }) {
  const status = useStrategyStages().statuses.byEvaluation.get(evaluationId);
  return status ? <StrategyStageBadge {...status} showFinding={showFinding} /> : <Text size="xs" c="dimmed">Stage loading…</Text>;
}
