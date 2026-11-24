import { useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import { Alert, Drawer, Group, Loader, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import type { WorkbenchState } from '../workspace/workbenchModel';
import { StrategyPickerControls } from './StrategyPickerControls';
import { CollectiveCalendarView, CollectiveOverviewView } from './CollectiveDashboardViews';
import { PortfolioHeader, type PortfolioView } from './PortfolioHeader';
import { PortfolioSettingsDrawer } from './PortfolioSettingsDrawer';
import { RiskView } from './RiskView';
import { useRecentForm } from './recentForm';
import { useCollectiveDashboardModel } from './useCollectiveDashboardModel';
import './collective.css';
import './portfolioRedesign.css';

export function CollectiveDashboard({
  researchState,
  refreshKey,
  view,
  alerts,
  pickerOpen,
  setPickerOpen,
}: {
  researchState?: WorkbenchState | null;
  refreshKey: number;
  view: string;
  alerts?: ReactNode;
  pickerOpen: boolean;
  setPickerOpen: Dispatch<SetStateAction<boolean>>;
}) {
  const current: PortfolioView = view === 'calendar' || view === 'risk' ? view : 'overview';
  const isMobile = useMediaQuery('(max-width: 900px)');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const model = useCollectiveDashboardModel({ refreshKey, view, researchState, pickerOpen, setPickerOpen });
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
    result,
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
  } = model;
  const recentForm = useRecentForm(model);
  const watchCount = Object.values(recentForm).filter((form) => form.tone === 'watch' || form.tone === 'weak').length;

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
      <PortfolioHeader model={model} view={current} watchCount={watchCount} onSettings={() => setSettingsOpen(true)} />
      {alerts}
      <div className='wb-content collective-dashboard wb-portfolio'>
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
            {result?.depleted && (
              <Alert color='orange' title='Starting capital runs out in this history'>
                Combined equity reaches zero or below at this size. The replay continues through those losses; it does not
                simulate margin liquidation.
              </Alert>
            )}
            {current === 'overview' && (
              <CollectiveOverviewView model={model} recentForm={recentForm} onSettings={() => setSettingsOpen(true)} />
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
        size={isMobile ? '100%' : 'min(1200px, 90vw)'}
        title={<span className='collective-drawer-title'>Add strategies</span>}
      >
        {picker || (catalog ? <Group><Loader size='sm' /><Text>Loading research history…</Text></Group> : loadingState)}
      </Drawer>
      <PortfolioSettingsDrawer model={model} opened={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
}
