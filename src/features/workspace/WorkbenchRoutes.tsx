import { lazy, Suspense, type ReactNode } from "react";
import { workbenchRequest as request } from "../../shared/api/workbench";
import { CollectiveDashboard } from "../portfolio/CollectiveDashboardPage";
import { ConnectingPage, WorkbenchAlerts } from "./WorkbenchChrome";
import type { WorkbenchController } from "./useWorkbenchController";

const ScorecardsPage = lazy(() => import("../scorecards/ScorecardsPage").then((module) => ({ default: module.ScorecardsPage })));
const ResearchPage = lazy(() => import("../evaluations/ResearchPage").then((module) => ({ default: module.ResearchPage })));
const EventStudies = lazy(() => import("../event-studies/EventStudiesPage").then((module) => ({ default: module.EventStudies })));
const RunsPage = lazy(() => import("../runs/RunsPage").then((module) => ({ default: module.RunsPage })));
const NewRunPage = lazy(() => import("../new-run/NewRunPage").then((module) => ({ default: module.NewRunPage })));
const StrategiesPage = lazy(() => import("../strategies/StrategiesPage").then((module) => ({ default: module.StrategiesPage })));
const DatasetsPage = lazy(() => import("../datasets/DatasetsPage").then((module) => ({ default: module.DatasetsPage })));
const WorkspaceOverview = lazy(() => import("./WorkspaceOverview").then((module) => ({ default: module.WorkspaceOverview })));

const loadingPage = <div className="wb-content"><div className="wb-card">Loading page…</div></div>;

export function WorkbenchRoutes({ controller }: { controller: WorkbenchController }) {
  const {
    action,
    busy,
    dashboardRefresh,
    inspect,
    refresh,
    researchSelection,
    route,
    setDeletion,
    setResearchSelection,
    setNotice,
    state,
  } = controller;

  if (route.page === "portfolio") {
    return (
      <CollectiveDashboard
        researchState={state}
        refreshKey={dashboardRefresh}
        view={route.sub}
        pickerOpen={controller.portfolioPickerOpen}
        setPickerOpen={controller.setPortfolioPickerOpen}
        alerts={<WorkbenchAlerts controller={controller} />}
      />
    );
  }
  if (route.page === "scorecards") return <Suspense fallback={loadingPage}><ScorecardsPage controller={controller} /></Suspense>;
  if (!state) return <ConnectingPage controller={controller} />;
  const workspace = <WorkspaceOverview
    state={state}
    busy={busy}
    alerts={<WorkbenchAlerts controller={controller} />}
    onInspect={(run) => void action(() => inspect(run))}
    onCleanup={(ids) => void action(async () => {
      setDeletion(await request("/runs/delete-preview", { ids }));
    })}
    onArchiveConfiguration={(runId, archived) => void action(async () => {
      await request(`/configurations/${archived ? "archive" : "unarchive"}`, { run_id: runId });
      controller.setSelected([]);
      controller.setComparison(null);
      setNotice(archived
        ? "Configuration archived with its matching runs. Find it in Archive."
        : "Configuration restored. Individually archived runs remain in Archive.");
    })}
  />;
  let content: ReactNode;
  if (route.page === "workspace") {
    content = workspace;
  } else if (route.page === "evaluations") {
    content = (
      <ResearchPage
        key={route.sub}
        initialRunId={route.sub.startsWith("plan~") ? route.sub.slice(5) : undefined}
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
  } else if (route.page === "runs") content = <RunsPage controller={controller} />;
  else if (route.page === "event-studies") content = <EventStudies datasets={state.datasets} />;
  else if (route.page === "new-run") content = <NewRunPage controller={controller} />;
  else if (route.page === "scripts") content = <StrategiesPage controller={controller} />;
  else if (route.page === "datasets") content = <DatasetsPage controller={controller} />;
  else content = workspace;
  return <Suspense fallback={loadingPage}>{content}</Suspense>;
}
