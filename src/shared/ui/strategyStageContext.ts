import { createContext, useContext } from "react";
import type { strategyStageStatuses } from "../../../shared/ts/stageStatus.ts";
import type { StrategyNextAction } from "../../../shared/ts/strategyLifecycle.ts";

export const StrategyStageContext = createContext<{
  statuses: ReturnType<typeof strategyStageStatuses>;
  onAction?: (action: StrategyNextAction) => void;
}>({ statuses: { byRun: new Map(), byEvaluation: new Map(), configurations: new Map() } });
export const useStrategyStages = () => useContext(StrategyStageContext);
