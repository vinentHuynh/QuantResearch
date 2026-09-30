import { Shell } from "../../app/Shell";
import type { Run, RunSummary } from "../../../shared/ts/workbenchModels.ts";
import { RunDialogs } from "../runs/RunDialogs";
import { WorkbenchRoutes } from "./WorkbenchRoutes";
import { useWorkbenchController } from "./useWorkbenchController";
import "./workbench.css";

export type { Run, RunSummary };

/** The active product shell. Domain UI lives with its feature; this component
 * only composes navigation, route content, and the shared run dialogs. */
export function Workbench() {
  const controller = useWorkbenchController();
  return (
    <Shell
      route={controller.route}
      counts={controller.navCounts}
      onSearch={controller.search}
    >
      <WorkbenchRoutes controller={controller} />
      <RunDialogs controller={controller} />
    </Shell>
  );
}
