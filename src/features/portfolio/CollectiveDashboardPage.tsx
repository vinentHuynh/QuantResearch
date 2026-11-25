import { href } from "../../app/navigation";
import { useEffect, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import { Alert, Button, Drawer, Group, Loader, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import type { WorkbenchState } from '../workspace/workbenchModel';
import { StrategyPickerControls } from './StrategyPickerControls';
import { CollectiveCalendarView, CollectiveOverviewView } from './CollectiveDashboardViews';
import { PortfolioHeader, type PortfolioView } from './PortfolioHeader';
import { PortfolioSettingsDrawer } from './PortfolioSettingsDrawer';
import { RiskView } from './RiskView';
import { useRecentForm } from './recentForm';
import { useCollectiveDashboardModel } from './useCollectiveDashboardModel';
import type { AddedSummary } from './CollectiveDashboardViews';
import './collective.css';
import './portfolioRedesign.css';

export function CollectiveDashboard({
  researchState,
  refreshResearch,
  refreshKey,
  view,
  alerts,
  pickerOpen,
  setPickerOpen,
}: {
  researchState?: WorkbenchState | null;
  /** Reloads the Workbench's runs; the Portfolio page does not poll on its own. */
  refreshResearch?: () => Promise<void>;
  refreshKey: number;
  view: string;
  alerts?: ReactNode;
  pickerOpen: boolean;
  setPickerOpen: Dispatch<SetStateAction<boolean>>;
}) {
  const current: PortfolioView = view === 'calendar' || view === 'risk' ? view : 'overview';
  const isMobile = useMediaQuery('(max-width: 900px)');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const model = useCollectiveDashboardModel({ refreshKey, view, researchState, refreshResearch, pickerOpen, setPickerOpen });
  const {
    catalog,
    choose,
    computed,
    error,
    focusRunId,
    importState,
    loading,
    markets,
    refreshEvidence,
    refreshing,
    retryTracking,
    search,
    selected,
    setMarkets,
    setSearch,
    setSettings,
    setTimeframe,
    settings,
    timeframe,
    tracking,
    periodMetrics,
    periodPnl,
  } = model;
  const snapshot = useRef<AddedSummary['was'] & { copies: Record<string, number> } | null>(null);
  const wasOpen = useRef(false);
  const [added, setAdded] = useState<AddedSummary | null>(null);
  const strategyCount = (copies: Record<string, number>) => Object.values(copies).filter((n) => n > 0).length;
  useEffect(() => {
    if (pickerOpen && !wasOpen.current) {
      snapshot.current = periodMetrics ? { copies: settings.copies, net: periodPnl, drawdown: periodMetrics.maxDrawdownDollars, ratio: periodMetrics.recoveryFactor ?? null, winRate: periodMetrics.winRate ?? null } : { copies: settings.copies, net: null, drawdown: null, ratio: null, winRate: null };
    }
    if (!pickerOpen && wasOpen.current && snapshot.current) {
      const gained = strategyCount(settings.copies) - strategyCount(snapshot.current.copies);
      const { copies, ...was } = snapshot.current;
      setAdded(gained > 0 ? { count: gained, copies, was } : null);
    }
    wasOpen.current = pickerOpen;
  }, [pickerOpen]); // eslint-disable-line react-hooks/exhaustive-deps
  const recentForm = useRecentForm(model);
  const watchCount = Object.values(recentForm).filter((form) => form.tone === 'watch' || form.tone === 'weak').length;
  const removeStrategies = (ids: string[]) => {
    choose((copies) => {
      const remaining = { ...copies };
      for (const id of ids) delete remaining[id];
      return remaining;
    });
    setAdded(null);
  };

  const loadingState = (
    <Group>
      <Loader size='sm' />
      <Text>Loading strategy catalog…</Text>
    </Group>
  );
  const picker = catalog && researchState && (
    <StrategyPickerControls
      catalog={catalog}
      choose={choose}
      focusRunId={focusRunId}
      importState={importState}
      markets={markets}
      pickerOpen={pickerOpen}
      search={search}
      selected={selected}
      runs={researchState?.runs}
      strategies={researchState?.strategies}
      refreshEvidence={refreshEvidence}
      refreshing={refreshing}
      retryTracking={retryTracking}
      setMarkets={setMarkets}
      setPickerOpen={setPickerOpen}
      setSearch={setSearch}
      setSettings={setSettings}
      setTimeframe={setTimeframe}
      settings={settings}
      timeframe={timeframe}
      tracking={tracking}
    />
  );

  return (
    <>
      <PortfolioHeader
        model={model}
        view={current}
        watchCount={watchCount}
        onSettings={() => setSettingsOpen(true)}
        onRemoveStrategies={removeStrategies}
      />
      {alerts}
      <div className='wb-content collective-dashboard wb-portfolio'>
        {model.historyUpdate && (
          <Alert color={model.historyUpdate.phase === 'error' ? 'red' : model.historyUpdate.phase === 'done' ? 'teal' : 'blue'}
            title={model.historyUpdate.phase === 'error' ? 'Portfolio recalculation needs attention' : model.historyUpdate.phase === 'done' ? 'Portfolio recalculated' : 'Recalculating portfolio'}
            role={model.historyUpdate.phase === 'error' ? 'alert' : 'status'}>
            {model.historyUpdate.message}
            {model.canRetryRecalculation && <Button size="compact-xs" variant="light" ml="xs" disabled={refreshing}
              onClick={() => void model.recalculatePortfolio(true)}>Retry recalculation</Button>}
            {model.historyUpdate.phase !== 'done' && <> <a href={href('runs')} target='_blank' rel='noreferrer'>View runs</a></>}
          </Alert>
        )}
        {error && (
          <Alert color='red' title='Portfolio data'>
            {error}
          </Alert>
        )}
        {!catalog ? (
          loadingState
        ) : (
          <>
            {computed.error && !computed.coverageGap && (
              <Alert color={loading ? 'blue' : 'yellow'} title='Combined result'>
                {computed.error}
              </Alert>
            )}
            {current === 'overview' && (
              <CollectiveOverviewView
                model={model}
                recentForm={recentForm}
                onSettings={() => setSettingsOpen(true)}
                onRemoveStrategies={removeStrategies}
                added={added}
                onUndo={() => { if (added) choose(added.copies); setAdded(null); }}
                onDismiss={() => setAdded(null)}
              />
            )}
            {current === 'calendar' && <CollectiveCalendarView model={model} />}
            {current === 'risk' && <RiskView model={model} />}
          </>
        )}
      </div>
      <Drawer
        opened={pickerOpen}
        onClose={() => setPickerOpen(false)}
        position='right'
        size={isMobile ? '100%' : 'min(960px, 90vw)'}
        title={<span className='collective-drawer-title'>Add strategies</span>}
      >
        {picker || (catalog ? <Group><Loader size='sm' /><Text>Loading research history…</Text></Group> : loadingState)}
      </Drawer>
      <PortfolioSettingsDrawer model={model} opened={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
}
