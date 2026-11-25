import { lazy, Suspense, type ReactNode } from "react";
import { href } from "../../app/navigation";
import { workbenchRequest as request } from "../../shared/api/workbench";
import { PageSectionProvider, type PageSection } from "../../shared/ui/PageHeader";
import { CollectiveDashboard } from "../portfolio/CollectiveDashboardPage";
import { useResearchRows } from "../strategies/researchRows";
import { ConnectingPage, WorkbenchAlerts } from "./WorkbenchChrome";
import type { WorkbenchController } from "./useWorkbenchController";

const ResearchPage = lazy(() => import("../evaluations/ResearchPage").then((module) => ({ default: module.ResearchPage })));
const EventStudies = lazy(() => import("../event-studies/EventStudiesPage").then((module) => ({ default: module.EventStudies })));
const RunsPage = lazy(() => import("../runs/RunsPage").then((module) => ({ default: module.RunsPage })));
const NewRunPage = lazy(() => import("../new-run/NewRunPage").then((module) => ({ default: module.NewRunPage })));
const StrategiesPage = lazy(() => import("../strategies/StrategiesPage").then((module) => ({ default: module.StrategiesPage })));
const StrategiesOverview = lazy(() => import("../strategies/StrategiesOverview").then((module) => ({ default: module.StrategiesOverview })));
const ArchivedConfigurations = lazy(() => import("../strategies/StrategiesOverview").then((module) => ({ default: module.ArchivedConfigurations })));
const StrategyDetail = lazy(() => import("../strategies/StrategyDetail").then((module) => ({ default: module.StrategyDetail })));
const DatasetsPage = lazy(() => import("../datasets/DatasetsPage").then((module) => ({ default: module.DatasetsPage })));

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
  const rows = useResearchRows(state);

  if (route.page === "portfolio") {
    return (
      <CollectiveDashboard
        researchState={state}
        refreshResearch={controller.refresh}
        refreshKey={dashboardRefresh}
        view={route.sub}
        pickerOpen={controller.portfolioPickerOpen}
        setPickerOpen={controller.setPortfolioPickerOpen}
        alerts={<WorkbenchAlerts controller={controller} />}
      />
    );
  }
  if (!state) return <ConnectingPage controller={controller} />;
  const alerts = <WorkbenchAlerts controller={controller} />;
  const archiveConfiguration = (runId: string, archived: boolean) => void action(async () => {
    await request(`/configurations/${archived ? "archive" : "unarchive"}`, { run_id: runId });
    controller.setSelected([]);
    controller.setComparison(null);
    setNotice(archived
      ? "Setup archived with its matching runs. Find it under Strategies › Archived."
      : "Setup restored. Individually archived runs stay in the run archive.");
  });
  const scan = () => void action(async () => {
    await request("/discover", {});
    setNotice("Strategy folder scanned.");
  });

  let content: ReactNode;
  if (route.page === "strategies") {
    const archivedRows = rows.filter((row) => row.archived).length;
    const section: PageSection = {
      title: "Strategies",
      description: "Every runnable strategy, grouped by what it needs next.",
      tabsLabel: "Strategy views",
      hidePageTabs: true,
      tabs: [
        { label: "Strategies", count: rows.length - archivedRows, active: route.sub === "list", href: href("strategies") },
        { label: "Scripts", count: state.strategies.length, active: route.sub === "scripts", href: href("strategies", "scripts") },
        { label: "Source library", count: state.library?.total, active: route.sub === "library", href: href("strategies", "library") },
        { label: "Archived", count: (state.archived_scripts || []).length + archivedRows, active: route.sub === "archive", href: href("strategies", "archive") },
      ],
    };
    if (route.sub === "detail") {
      let id = route.detail;
      try { id = decodeURIComponent(route.detail); } catch { /* keep the raw id */ }
      content = <StrategyDetail row={rows.find((row) => row.id === id)} controller={controller} onArchive={archiveConfiguration} />;
    } else {
      content = (
        <PageSectionProvider section={section}>
          {route.sub === "list" ? (
            <StrategiesOverview
              state={state}
              rows={rows}
              busy={busy}
              onScan={scan}
              alerts={alerts}
              onCleanup={(ids) => void action(async () => {
                setDeletion(await request("/runs/delete-preview", { ids }));
              })}
            />
          ) : (
            <StrategiesPage
              controller={controller}
              before={route.sub === "archive" && (
                <ArchivedConfigurations state={state} rows={rows} busy={busy} onRestore={(runId) => archiveConfiguration(runId, false)} />
              )}
            />
          )}
        </PageSectionProvider>
      );
    }
  } else if (route.page === "runs") {
    const running = state.runs.filter((run) => ["Running", "Queued", "Summarizing"].includes(run.status)).length;
    const evaluations = route.sub === "evaluations";
    const section: PageSection = {
      title: "Runs",
      description: `Every backtest and evaluation · ${state.limits.concurrency} workers, up to ${state.limits.maxBatch} jobs per launch · ${running} running`,
      tabsLabel: "Run types",
      tabs: [
        { label: "Backtests", count: controller.latestHistory.length.toLocaleString(), active: !evaluations, href: href("runs") },
        { label: "Evaluations", count: (state.evaluations || []).length, active: evaluations, href: href("runs", "evaluations") },
      ],
    };
    content = (
      <PageSectionProvider section={section}>
        {evaluations ? (
          <ResearchPage
            key={route.detail}
            initialRunId={route.detail.startsWith("plan~") ? route.detail.slice(5) : undefined}
            selectedId={researchSelection}
            onSelect={setResearchSelection}
            alerts={alerts}
            runs={state.runs}
            evaluations={state.evaluations || []}
            regimes={state.regimes || []}
            refresh={refresh}
            inspect={(run) => void action(() => inspect(run))}
          />
        ) : (
          <RunsPage controller={controller} />
        )}
      </PageSectionProvider>
    );
  } else if (route.page === "data") {
    const markets = new Set(state.datasets.map((dataset) => dataset.symbol)).size;
    const section: PageSection = {
      title: "Data",
      description: "Market data your backtests run on, and studies of price patterns in it.",
      tabsLabel: "Data views",
      tabs: [
        { label: "Market data", count: markets, active: route.sub !== "studies", href: href("data") },
        { label: "Pattern studies", active: route.sub === "studies", href: href("data", "studies") },
      ],
    };
    content = (
      <PageSectionProvider section={section}>
        {route.sub === "studies" ? <EventStudies datasets={state.datasets} /> : <DatasetsPage controller={controller} />}
      </PageSectionProvider>
    );
  } else if (route.page === "new-run") {
    content = <NewRunPage controller={controller} />;
  }
  return <Suspense fallback={loadingPage}>{content}</Suspense>;
}
