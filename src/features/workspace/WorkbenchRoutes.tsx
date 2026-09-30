import { workbenchRequest as request } from "../../shared/api/workbench";
import { CollectiveDashboard } from "../portfolio/CollectiveDashboardPage";
import { ScorecardsPage } from "../scorecards/ScorecardsPage";
import { ResearchPage } from "../evaluations/ResearchPage";
import { EventStudies } from "../event-studies/EventStudiesPage";
import { RunsPage } from "../runs/RunsPage";
import { NewRunPage } from "../new-run/NewRunPage";
import { StrategiesPage } from "../strategies/StrategiesPage";
import { DatasetsPage } from "../datasets/DatasetsPage";
import { WatchlistPage } from "../watchlist/WatchlistPage";
import { ConnectingPage, WorkbenchAlerts } from "./WorkbenchChrome";
import { WorkspaceOverview } from "./WorkspaceOverview";
import type { WorkbenchController } from "./useWorkbenchController";

export function WorkbenchRoutes({ controller }: { controller: WorkbenchController }) {
  const {
    action,
    dashboardRefresh,
    inspect,
    refresh,
    researchSelection,
    route,
    setDeletion,
    setResearchSelection,
    state,
  } = controller;

  if (route.page === "portfolio") {
    return (
      <CollectiveDashboard
        refreshKey={dashboardRefresh}
        view={route.sub}
        alerts={<WorkbenchAlerts controller={controller} />}
      />
    );
  }
  if (route.page === "scorecards") return <ScorecardsPage controller={controller} />;
  if (!state) return <ConnectingPage controller={controller} />;
  if (route.page === "workspace") {
    return (
      <WorkspaceOverview
        state={state}
        onInspect={(run) => void action(() => inspect(run))}
        onCleanup={(ids) =>
          void action(async () => {
            setDeletion(await request("/runs/delete-preview", { ids }));
          })
        }
      />
    );
  }
  if (route.page === "evaluations") {
    return (
      <ResearchPage
        selectedId={researchSelection}
        onSelect={setResearchSelection}
        alerts={<WorkbenchAlerts controller={controller} />}
        runs={state.runs}
        evaluations={state.evaluations || []}
        regimes={state.regimes || []}
        refresh={refresh}
        inspect={(run) => void action(() => inspect(run))}
      />
    );
  }
  if (route.page === "runs") return <RunsPage controller={controller} />;
  if (route.page === "event-studies") return <EventStudies datasets={state.datasets} />;
  if (route.page === "new-run") return <NewRunPage controller={controller} />;
  if (route.page === "scripts") return <StrategiesPage controller={controller} />;
  if (route.page === "datasets") return <DatasetsPage controller={controller} />;
  return <WatchlistPage controller={controller} />;
}
