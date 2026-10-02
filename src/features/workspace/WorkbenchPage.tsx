import { lazy, Suspense } from "react";
import { Shell } from "../../app/Shell";
import { StrategyStageProvider } from "../../shared/ui/StrategyStageBadge";
import type { Run, RunSummary } from "../../../shared/ts/workbenchModels.ts";
import { WorkbenchRoutes } from "./WorkbenchRoutes";
import { useWorkbenchController } from "./useWorkbenchController";
import "./workbench.css";

export type { Run, RunSummary };

const RunDialogs = lazy(() => import("../runs/RunDialogs").then((module) => ({ default: module.RunDialogs })));

/** The active product shell. Domain UI lives with its feature; this component
 * only composes navigation, route content, and the shared run dialogs. */
export function Workbench() {
  const controller = useWorkbenchController();
  return (
    <StrategyStageProvider state={controller.state} onAction={controller.stageAction}><Shell
      route={controller.route}
      counts={controller.navCounts}
      onSearch={controller.search}
      onSearchOpen={() => { if (!controller.state) void controller.refresh(); }}
    >
      <WorkbenchRoutes controller={controller} />
      {(controller.detail || controller.deletion) && (
        <Suspense fallback={null}><RunDialogs controller={controller} /></Suspense>
      )}
    </Shell></StrategyStageProvider>
  );
}
