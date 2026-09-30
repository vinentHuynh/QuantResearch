import { PageHeader } from "../../shared/ui/PageHeader";
import { RefreshButton, WorkbenchAlerts } from "../workspace/WorkbenchChrome";
import type { WorkbenchController } from "../workspace/useWorkbenchController";
import { StrategyScorecards } from "./StrategyScorecards";

export function ScorecardsPage({ controller }: { controller: WorkbenchController }) {
  const {
    action,
    dashboardRefresh,
    go,
    inspect,
    setResearchSelection,
    state,
  } = controller;
  return (
    <>
      <PageHeader crumb="Portfolio" title="Strategy scorecards" actions={<RefreshButton controller={controller} />} />
      <WorkbenchAlerts controller={controller} />
      <div className="wb-content">
        <StrategyScorecards
          refreshKey={dashboardRefresh}
          openEvaluation={(id) => {
            setResearchSelection(id);
            go("evaluations");
          }}
          inspectRun={(id) => {
            const run = state?.runs.find((candidate) => candidate.id === id);
            if (run) void action(() => inspect(run));
          }}
        />
      </div>
    </>
  );
}
