import type { Dispatch, ReactNode, SetStateAction } from 'react';
import {
  ActionIcon,
  Alert,
  Button,
  Drawer,
  Group,
  Loader,
  Text,
} from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { IconChevronLeft, IconRefresh } from '@tabler/icons-react';
import { PageHeader } from '../../shared/ui/PageHeader';
import type { WorkbenchState } from '../workspace/workbenchModel';
import { href } from '../../app/navigation';
import { CombinationControls } from './CombinationControls';
import { StrategyPickerControls } from './StrategyPickerControls';
import {
  CollectiveCalendarView,
  CollectiveContributionsView,
  CollectiveOverviewView,
} from './CollectiveDashboardViews';
import { PauseSizingView } from './PauseSizingView';
import { useCollectiveDashboardModel } from './useCollectiveDashboardModel';
import {
  collectiveViews as VIEWS,
  formatMoney as money,
  type CollectiveViewName as ViewName,
} from './collectiveViewModel';
import './collective.css';

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
  const current: ViewName = (VIEWS as readonly string[]).includes(view)
    ? (view as ViewName)
    : 'overview';
  const isMobile = useMediaQuery('(max-width: 900px)');
  const model = useCollectiveDashboardModel({ refreshKey, view, researchState, pickerOpen, setPickerOpen });
  const {
    accountingLabel,
    catalog,
    choose,
    computed,
    deleteCombination,
    error,
    exportCombination,
    exportDaily,
    focusRunId,
    importState,
    followLatestEnd,
    loadCombination,
    loading,
    marketCount,
    markets,
    railCollapsed,
    refreshEvidence,
    refreshing,
    retryTracking,
    result,
    saveCombination,
    savedBookName,
    savedBooks,
    selectedSavedBookId,
    search,
    selected,
    setMarkets,
    setMonth,
    setRailCollapsed,
    setSavedBookName,
    setSearch,
    setSettings,
    setSheetOpen,
    setTimeframe,
    settings,
    sheetOpen,
    testedWindow,
    tracking,
    timeframe,
    useCommon,
  } = model;
  const collapsed =
    railCollapsed ?? (current === 'calendar' || current === 'pause');

  const railBody = (
    <CombinationControls
      capital={settings.capital}
      catalog={catalog}
      choose={choose}
      deleteCombination={deleteCombination}
      exportCombination={exportCombination}
      exportDaily={exportDaily}
      followLatestEnd={followLatestEnd}
      hasResult={!!result}
      isMobile={isMobile}
      loadCombination={loadCombination}
      result={result}
      retryTracking={retryTracking}
      saveCombination={saveCombination}
      savedBookName={savedBookName}
      savedBooks={savedBooks}
      selectedSavedBookId={selectedSavedBookId}
      selected={selected}
      setMonth={setMonth}
      setPickerOpen={setPickerOpen}
      setRailCollapsed={setRailCollapsed}
      setSavedBookName={setSavedBookName}
      setSettings={setSettings}
      setSheetOpen={setSheetOpen}
      settings={settings}
      testedWindow={testedWindow}
      tracking={tracking}
      useCommon={useCommon}
    />
  );
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
  const titleByView: Record<ViewName, string> = {
    overview: 'Overview',
    calendar: 'Calendar',
    contributions: 'Contributions',
    pause: 'Pause & sizing',
  };

  return (
    <>
      <PageHeader
        crumb='Portfolio'
        title='Combined portfolio'
        actions={
          <>
            {catalog && (
              <span className='wb-stamp'>
                Evidence refreshed{' '}
                {new Date(catalog.generated_at).toLocaleString(undefined, {
                  day: 'numeric',
                  month: 'short',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
            )}
            <Button
              variant='default'
              size='xs'
              leftSection={<IconRefresh size={14} />}
              loading={refreshing}
              onClick={() => void refreshEvidence()}
            >
              Refresh evidence
            </Button>
          </>
        }
        tabsLabel='Portfolio views'
        tabs={VIEWS.map((portfolioView) => ({
          label: titleByView[portfolioView],
          href: href('portfolio', portfolioView),
          active: current === portfolioView,
        }))}
      />
      {alerts}
      <div className={`wb-with-rail${collapsed ? ' collapsed' : ''}`}>
        <div className='wb-content collective-dashboard'>
          {error && (
            <Alert color='red' title='Collective evidence'>
              {error}
            </Alert>
          )}
          {!catalog ? (
            loadingState
          ) : (
            <>
              <p className='wb-context'>
                {selected.length} {selected.length === 1 ? 'book' : 'books'} ·{' '}
                {marketCount} {marketCount === 1 ? 'market' : 'markets'} ·{' '}
                {settings.start} to {settings.end} · {accountingLabel}, net of
                recorded costs
              </p>
              {computed.error && !computed.coverageGap && (
                <Alert
                  color={loading ? 'blue' : 'yellow'}
                  title='Combined book'
                >
                  {computed.error}
                </Alert>
              )}
              {current === 'overview' && (
                <CollectiveOverviewView model={model} />
              )}
              {result?.depleted && (
                <Alert
                  color='orange'
                  title='Starting capital exhausted in this history'
                  mt='md'
                >
                  Combined equity reaches zero or below at this exposure. The
                  replay continues through those losses; it does not simulate
                  margin liquidation.
                </Alert>
              )}
              {current === 'calendar' && (
                <CollectiveCalendarView model={model} />
              )}
              {current === 'contributions' && (
                <CollectiveContributionsView model={model} />
              )}
              {current === 'pause' && <PauseSizingView model={model} />}
              <details className='wb-portfolio-method'>
                <summary>How this portfolio is calculated</summary>
                <Text size='xs' c='dimmed' mt='xs'>
                  {settings.policy.enabled ? 'Pause and sizing controls replay recorded trades; they do not rerun strategy signals.' : catalog.definitions.pnl}{' '}
                  Histories come from verified ledgers. Missing dates block aggregation;
                  daily drawdown omits intraday extremes. Books are independent, with
                  no position netting or shared margin model. These historical results
                  were inspected during strategy selection.
                </Text>
              </details>
            </>
          )}
        </div>
        {!isMobile &&
          (collapsed ? (
            <aside
              className='wb-rail-strip'
              aria-label='Combination, collapsed'
            >
              <ActionIcon
                variant='light'
                aria-label='Expand combination'
                onClick={() => setRailCollapsed(false)}
              >
                <IconChevronLeft size={15} />
              </ActionIcon>
              <span className='vertical'>
                Combination · {selected.length}{' '}
                {selected.length === 1 ? 'book' : 'books'}
              </span>
            </aside>
          ) : (
            <aside className='wb-rail' aria-label='Combination'>
              {railBody}
            </aside>
          ))}
      </div>
      {isMobile && (
        <div className='wb-rail-summary'>
          <div>
            <b>
              Combination · {selected.length}{' '}
              {selected.length === 1 ? 'book' : 'books'}
            </b>
            <small>
              {money(settings.capital)} ·{' '}
              {settings.basis === 'marked' ? 'marked daily' : 'closed trades'}
            </small>
          </div>
          <Button variant='light' onClick={() => setSheetOpen(true)}>
            Edit
          </Button>
        </div>
      )}
      <Drawer
        opened={pickerOpen}
        onClose={() => setPickerOpen(false)}
        position='right'
        size={isMobile ? '100%' : 'min(1200px, 90vw)'}
        title={<span className='collective-drawer-title'>Add strategies</span>}
      >
        {picker || (catalog ? <Group><Loader size='sm' /><Text>Loading research history…</Text></Group> : loadingState)}
      </Drawer>
      <Drawer
        opened={!!isMobile && sheetOpen}
        onClose={() => setSheetOpen(false)}
        position='bottom'
        size='auto'
        aria-label='Combination'
        styles={{
          content: {
            height: 'auto',
            maxHeight: '92vh',
            borderRadius: '16px 16px 0 0',
          },
        }}
        classNames={{ body: 'collective-sheet' }}
      >
        {railBody}
        <Button fullWidth mt='md' onClick={() => setSheetOpen(false)}>
          Done
        </Button>
      </Drawer>
    </>
  );
}
