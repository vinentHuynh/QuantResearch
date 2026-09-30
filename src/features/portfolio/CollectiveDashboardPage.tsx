import type { ReactNode } from "react";
import {
  ActionIcon,
  Alert,
  Button,
  Drawer,
  Group,
  Loader,
  Text,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconChevronLeft, IconRefresh } from "@tabler/icons-react";
import { PageHeader } from "../../shared/ui/PageHeader";
import { href } from "../../app/navigation";
import { CombinationControls } from "./CombinationControls";
import { StrategyPickerControls } from "./StrategyPickerControls";
import {
  CollectiveCalendarView,
  CollectiveContributionsView,
  CollectiveOverviewView,
} from "./CollectiveDashboardViews";
import { PauseSizingView } from "./PauseSizingView";
import { useCollectiveDashboardModel } from "./useCollectiveDashboardModel";
import {
  collectiveViews as VIEWS,
  formatMoney as money,
  type CollectiveViewName as ViewName,
} from "./collectiveViewModel";
import "./collective.css";

export function CollectiveDashboard({
  refreshKey,
  view,
  alerts,
}: {
  refreshKey: number;
  view: string;
  alerts?: ReactNode;
}) {
  const current: ViewName = (VIEWS as readonly string[]).includes(view)
    ? (view as ViewName)
    : "overview";
  const isMobile = useMediaQuery("(max-width: 900px)");
  const model = useCollectiveDashboardModel({ refreshKey, view });
  const {
    accountingLabel,
    catalog,
    choose,
    computed,
    error,
    exportCombination,
    exportDaily,
    filter,
    hidden,
    latestEsNq,
    latestEsNqAvailable,
    latestEsNqWindow,
    loadCombination,
    loading,
    marketCount,
    markets,
    pickerOpen,
    previousSettings,
    railCollapsed,
    refreshEvidence,
    refreshing,
    restorePreviousCombination,
    result,
    saveCombination,
    savedBookName,
    savedBooks,
    search,
    selected,
    setFilter,
    setMarkets,
    setMonth,
    setPickerOpen,
    setRailCollapsed,
    setSavedBookName,
    setSearch,
    setSettings,
    setSheetOpen,
    setTimeframe,
    settings,
    sheetOpen,
    showingLatestEsNq,
    testedWindow,
    timeframe,
    useCommon,
    viewLatestEsNq,
    visible,
  } = model;
  const collapsed =
    railCollapsed ?? (current === "calendar" || current === "pause");

  const railBody = (
    <CombinationControls
      capital={settings.capital}
      catalog={catalog}
      choose={choose}
      exportCombination={exportCombination}
      exportDaily={exportDaily}
      hasResult={!!result}
      isMobile={isMobile}
      loadCombination={loadCombination}
      saveCombination={saveCombination}
      savedBookName={savedBookName}
      savedBooks={savedBooks}
      selected={selected}
      setMonth={setMonth}
      setPickerOpen={setPickerOpen}
      setRailCollapsed={setRailCollapsed}
      setSavedBookName={setSavedBookName}
      setSettings={setSettings}
      setSheetOpen={setSheetOpen}
      settings={settings}
      testedWindow={testedWindow}
      useCommon={useCommon}
    />
  );
  const loadingState = (
    <Group>
      <Loader size="sm" />
      <Text>Loading strategy catalogâ€¦</Text>
    </Group>
  );
  const picker = catalog && (
    <StrategyPickerControls
      catalog={catalog}
      choose={choose}
      filter={filter}
      hidden={hidden}
      isMobile={isMobile}
      markets={markets}
      search={search}
      selected={selected}
      setFilter={setFilter}
      setMarkets={setMarkets}
      setPickerOpen={setPickerOpen}
      setSearch={setSearch}
      setTimeframe={setTimeframe}
      settings={settings}
      timeframe={timeframe}
      visible={visible}
    />
  );
  const titleByView: Record<ViewName, string> = {
    overview: "Overview",
    calendar: "Calendar",
    contributions: "Contributions",
    pause: "Pause & sizing",
  };

  return (
    <>
      <PageHeader
        crumb="Portfolio"
        title="Combined portfolio"
        actions={
          <>
            {catalog && (
              <span className="wb-stamp">
                Evidence refreshed{" "}
                {new Date(catalog.generated_at).toLocaleString(undefined, {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
            <Button
              variant="default"
              size="xs"
              leftSection={<IconRefresh size={14} />}
              loading={refreshing}
              onClick={() => void refreshEvidence()}
            >
              Refresh evidence
            </Button>
          </>
        }
        tabsLabel="Portfolio views"
        tabs={VIEWS.map((portfolioView) => ({
          label: titleByView[portfolioView],
          href: href("portfolio", portfolioView),
          active: current === portfolioView,
        }))}
      />
      {alerts}
      <div className={`wb-with-rail${collapsed ? " collapsed" : ""}`}>
        <div className="wb-content collective-dashboard">
          {error && (
            <Alert color="red" title="Collective evidence">
              {error}
            </Alert>
          )}
          {!catalog ? (
            loadingState
          ) : (
            <>
              <p className="wb-context">
                {selected.length} {selected.length === 1 ? "book" : "books"} Â·{" "}
                {marketCount} {marketCount === 1 ? "market" : "markets"} Â·{" "}
                {settings.start} to {settings.end} Â· {accountingLabel}, net of
                recorded costs
              </p>
              {latestEsNqAvailable &&
                (!showingLatestEsNq || previousSettings) && (
                  <Alert
                    color="blue"
                    title={
                      showingLatestEsNq
                        ? "Viewing refreshed ES/NQ history"
                        : "September ES/NQ history is available"
                    }
                    mb="md"
                  >
                    <Group justify="space-between" align="center" gap="sm">
                      <Text size="sm">
                        {latestEsNq.length} ES/NQ books share a tested window
                        through {latestEsNqWindow.end}.
                        {!showingLatestEsNq &&
                          " Open that combination to see its September calendar."}
                      </Text>
                      <Group gap="xs">
                        {!showingLatestEsNq && (
                          <Button size="xs" onClick={viewLatestEsNq}>
                            View latest ES/NQ
                          </Button>
                        )}
                        {previousSettings && (
                          <Button
                            size="xs"
                            variant="default"
                            onClick={restorePreviousCombination}
                          >
                            Restore previous combination
                          </Button>
                        )}
                      </Group>
                    </Group>
                  </Alert>
                )}
              {computed.error && (
                <Alert
                  color={loading ? "blue" : "yellow"}
                  title="Combined book"
                >
                  {computed.error}
                </Alert>
              )}
              {current === "overview" && (
                <CollectiveOverviewView model={model} />
              )}
              {result?.depleted && (
                <Alert
                  color="orange"
                  title="Starting capital exhausted in this history"
                  mt="md"
                >
                  Combined equity reaches zero or below at this exposure. The
                  replay continues through those losses; it does not simulate
                  margin liquidation.
                </Alert>
              )}
              {current === "calendar" && (
                <CollectiveCalendarView model={model} />
              )}
              {current === "contributions" && (
                <CollectiveContributionsView model={model} />
              )}
              {current === "pause" && <PauseSizingView model={model} />}
              <Text size="xs" c="dimmed" mt="md">
                {settings.policy.enabled
                  ? "UTC closed-trade P&L, net of proportionally scaled recorded costs. Independent books with the selected entry, sizing and optional margin-assumption controls; no position netting or stateful execution rerun."
                  : catalog.definitions.pnl}{" "}
                Known gaps between test windows block aggregation. Zero on a
                covered day means no recorded change. Selections were made after
                inspecting these histories; this is not untouched portfolio
                validation. Histories are imported from verified full ledgers,
                with one baseline per strategy configuration; cost and execution
                variants are not added twice. Daily drawdown does not capture
                intraday extremes. Feasibility refers to the displayed
                historical checklist, not live approval. Configuration and
                selection are saved in this browser.
              </Text>
            </>
          )}
        </div>
        {!isMobile &&
          (collapsed ? (
            <aside className="wb-rail-strip" aria-label="Combination, collapsed">
              <ActionIcon
                variant="light"
                aria-label="Expand combination"
                onClick={() => setRailCollapsed(false)}
              >
                <IconChevronLeft size={15} />
              </ActionIcon>
              <span className="vertical">
                Combination Â· {selected.length}{" "}
                {selected.length === 1 ? "book" : "books"}
              </span>
            </aside>
          ) : (
            <aside className="wb-rail" aria-label="Combination">
              {railBody}
            </aside>
          ))}
      </div>
      {isMobile && (
        <div className="wb-rail-summary">
          <div>
            <b>
              Combination Â· {selected.length}{" "}
              {selected.length === 1 ? "book" : "books"}
            </b>
            <small>
              {money(settings.capital)} Â·{" "}
              {settings.basis === "marked" ? "marked daily" : "closed trades"}
            </small>
          </div>
          <Button variant="light" onClick={() => setSheetOpen(true)}>
            Edit
          </Button>
        </div>
      )}
      <Drawer
        opened={pickerOpen}
        onClose={() => setPickerOpen(false)}
        position="right"
        size={isMobile ? "100%" : 900}
        title={<span className="collective-drawer-title">Add strategies</span>}
      >
        {picker || loadingState}
      </Drawer>
      <Drawer
        opened={!!isMobile && sheetOpen}
        onClose={() => setSheetOpen(false)}
        position="bottom"
        size="auto"
        aria-label="Combination"
        styles={{
          content: {
            height: "auto",
            maxHeight: "92vh",
            borderRadius: "16px 16px 0 0",
          },
        }}
        classNames={{ body: "collective-sheet" }}
      >
        {railBody}
        <Button fullWidth mt="md" onClick={() => setSheetOpen(false)}>
          Done
        </Button>
      </Drawer>
    </>
  );
}
