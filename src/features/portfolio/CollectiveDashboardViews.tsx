import { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  ScrollArea,
  SegmentedControl,
  Table,
  Text,
} from '@mantine/core';
import {
  IconChevronLeft,
  IconChevronRight,
  IconMinus,
  IconPlus,
  IconRefresh,
  IconX,
} from '@tabler/icons-react';
import { href } from '../../app/navigation';
import type { RecentForm } from './recentForm';
import type { CollectiveDashboardModel } from './useCollectiveDashboardModel';
import type { PortfolioPnlPeriod } from '../../../shared/ts/portfolioPeriods.ts';
import { collectiveProgress } from '../../../shared/ts/progress.ts';
import { StrategyStageBadge } from '../../shared/ui/StrategyStageBadge';
import {
  formatMoney as money,
  formatPercent as pct,
  coverageEndExplanation,
  gateStateColor as stateColor,
  portfolioUpdatePresentation,
  signedClass as signed,
  valueTone as tone,
} from './collectiveViewModel';
import {
  CollectiveCalendar as Calendar,
  CollectivePnlChart as PnlChart,
} from './CollectivePresentation';
import { PortfolioPeriodSelector } from './PortfolioPeriodSelector';
import { DayTradeViewer } from './DayTradeViewer';
import { strategyTitle } from "../../../shared/ts/formatting.ts";

type Model = CollectiveDashboardModel;
const periodLabels: Record<PortfolioPnlPeriod, string> = {
  all: 'All time',
  '1y': '1 year',
  ytd: 'YTD',
  '6m': '6 months',
  '1m': '1 month',
};

export function CollectiveEmptyState({ model }: { model: Model }) {
  const { computed, histories, selected, setPickerOpen, settings, testedWindow, tracking, useCommon } = model;
  const [rerun, setRerun] = useState<{ phase: 'idle' | 'starting' | 'started' | 'error'; message?: string }>({ phase: 'idle' });
  const runnable = selected.flatMap((item) => (item.source_run_ids?.length ? [item.source_run_ids[item.source_run_ids.length - 1]] : []));
  const rerunStrategies = async () => {
    setRerun({ phase: 'starting' });
    try {
      for (const id of runnable) {
        const response = await fetch(`/api/workbench/runs/${encodeURIComponent(id)}/retry`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: '{}',
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.error || `Could not start run ${id}`);
      }
      const skipped = selected.length - runnable.length;
      setRerun({
        phase: 'started',
        message: `Started ${runnable.length} ${runnable.length === 1 ? 'run' : 'runs'}${skipped ? ` (${skipped} without a saved run were skipped)` : ''}. When they finish, use the refresh button next to “Updated” above to load the new results.`,
      });
    } catch (error) {
      setRerun({ phase: 'error', message: error instanceof Error ? error.message : String(error) });
    }
  };
  const endExplanation = computed.coverageGap
    ? coverageEndExplanation(selected, histories, settings, testedWindow, tracking)
    : null;
  return (
    <section className='wb-card'>
      <h2>
        {selected.length ? 'Combined book unavailable' : 'No books selected'}
      </h2>
      <p className='wb-card-sub'>
        {selected.length
          ? computed.coverageGap
            ? endExplanation || (testedWindow.start
              ? `All selected books cover ${testedWindow.start} to ${testedWindow.end}. Apply this continuous tested window to calculate the combined book.`
              : 'These configurations have no common tested window. Remove a configuration or choose different histories.')
            : 'Review the message above, then adjust the dates, calibration, or replay settings.'
          : 'Add tested strategies to see their combined P&L, calendar and contributions.'}
      </p>
      {computed.coverageGap && (
        <Button
          mt='md'
          variant='light'
          onClick={testedWindow.start ? useCommon : () => setPickerOpen(true)}
        >
          {testedWindow.start
            ? 'Apply common tested window'
            : 'Review configurations'}
        </Button>
      )}
      {selected.length > 0 && (
        <>
          <Button mt='md' ml={computed.coverageGap ? 'xs' : 0} variant='default' leftSection={<IconRefresh size={14} />}
            loading={rerun.phase === 'starting'} disabled={!runnable.length || rerun.phase === 'started'} onClick={() => void rerunStrategies()}
            title={runnable.length ? 'Rerun each selected strategy with its saved settings' : 'None of the selected strategies has a saved run to repeat'}>
            Run strategies again
          </Button>
          {rerun.message && (
            <Text size='sm' mt='sm' c={rerun.phase === 'error' ? 'red' : 'dimmed'} role={rerun.phase === 'error' ? 'alert' : 'status'}>
              {rerun.message} {rerun.phase === 'started' && <a href={href('runs')}>View runs</a>}
            </Text>
          )}
        </>
      )}
      {!selected.length && (
        <Button
          mt='md'
          variant='light'
          leftSection={<IconPlus size={14} />}
          onClick={() => setPickerOpen(true)}
        >
          Add strategies
        </Button>
      )}
    </section>
  );
}

const wholeMoney = (value: number) =>
  `${value < 0 ? '−' : value > 0 ? '+' : ''}$${Math.abs(Math.round(value)).toLocaleString('en-US')}`;

function YearBars({ annual, start, end }: { annual: Record<string, number>; start: string; end: string }) {
  const entries = Object.entries(annual).sort();
  const scale = Math.max(1, ...entries.map(([, pnl]) => Math.abs(pnl)));
  return (
    <div className='wb-year-bars' role='list' aria-label='P&L by year'>
      {entries.map(([year, pnl]) => {
        const partial = start > `${year}-01-01` || end < `${year}-12-31`;
        return (
          <div className='wb-year-bar' role='listitem' key={year} aria-label={`${year}${partial ? ' (partial year)' : ''}: ${money(pnl)}`}>
            <span className={`wb-year-value ${signed(pnl)}`}>{wholeMoney(pnl)}</span>
            <div className='wb-year-track'>
              <i className={pnl < 0 ? 'is-loss' : 'is-gain'} style={{ height: `${Math.max(2, (Math.abs(pnl) / scale) * 100)}%` }} />
            </div>
            <span className='wb-year-label'>{year}{partial && <small> partial</small>}</span>
          </div>
        );
      })}
    </div>
  );
}

export type AddedSummary = {
  count: number;
  copies: Record<string, number>;
  was: { net: number | null; drawdown: number | null; ratio: number | null; winRate: number | null };
};

export function CollectiveOverviewView({ model, recentForm, onSettings, added, onUndo, onDismiss }: {
  model: Model;
  recentForm: Record<string, RecentForm>;
  onSettings: () => void;
  added?: AddedSummary | null;
  onUndo?: () => void;
  onDismiss?: () => void;
}) {
  const {
    annual,
    chartMode,
    choose,
    periodComponents,
    periodMetrics,
    periodPoints,
    periodPnl,
    periodStart,
    pnlPeriod,
    result,
    retryTracking,
    selected,
    setChartMode,
    setPickerOpen,
    setPnlPeriod,
    settings,
    tracking,
    volatility,
  } = model;
  if (!result || !periodMetrics) return <CollectiveEmptyState model={model} />;
  const periodBaseline = periodPoints.reduce((total, point) => total + point.baseline, 0);
  const view = chartMode === 'daily' || chartMode === 'years' ? chartMode : 'cumulative';
  const components = new Map(periodComponents.map((component) => [component.id, component]));
  const worstSingle = [...periodComponents].sort((a, b) => b.maxDrawdownDollars - a.maxDrawdownDollars)[0];
  const ratio = periodMetrics.recoveryFactor;
  const setCopies = (id: string, value: number) =>
    choose({ ...settings.copies, [id]: Math.min(100, Math.max(1, value)) });

  const was = added?.was;
  return (
    <>
      {added && (
        <div className='wb-added-banner' role='status'>
          <span><b>{added.count} {added.count === 1 ? 'strategy' : 'strategies'} added</b> · the figures below include {added.count === 1 ? 'it' : 'them'}</span>
          <button type='button' className='wb-link-button' onClick={onUndo}>Undo</button>
          <button type='button' className='wb-link-button' aria-label='Dismiss' onClick={onDismiss}>Dismiss</button>
        </div>
      )}
      <section className='wb-kpi-cards' data-testid='portfolio-metrics' aria-label='Key figures'>
        <div className='wb-kpi-card'>
          <span className='wb-kpi-label'>Net P&amp;L · {periodLabels[pnlPeriod]}</span>
          <span className={`wb-kpi-value ${signed(periodPnl)}`} data-testid='portfolio-pnl'>{wholeMoney(periodPnl)}</span>
          <span className='wb-kpi-note'>{pct(periodPnl / result.capital)} on starting capital{was?.net != null && <> · Was {wholeMoney(was.net)}</>}</span>
        </div>
        <div className='wb-kpi-card'>
          <span className='wb-kpi-label'>Max drawdown</span>
          <span className='wb-kpi-value wb-loss'>{wholeMoney(-periodMetrics.maxDrawdownDollars)}</span>
          <span className='wb-kpi-note'>
            {pct(Math.abs(periodMetrics.maxDrawdown))} below peak · {settings.basis === 'marked' ? 'daily closes' : 'closed trades only'}
            {was?.drawdown != null && <> · Was {wholeMoney(-was.drawdown)}</>}
          </span>
        </div>
        <div className='wb-kpi-card'>
          <span className='wb-kpi-label'>Return ÷ drawdown</span>
          <span className='wb-kpi-value'>{ratio?.toFixed(2) ?? '—'}</span>
          <span className='wb-kpi-note'>{ratio != null ? `$${ratio.toFixed(2)} earned per $1 of drawdown` : 'No drawdown in this period'}{was?.ratio != null && <> · Was {was.ratio.toFixed(2)}</>}</span>
        </div>
        <div className='wb-kpi-card'>
          <span className='wb-kpi-label'>Win rate</span>
          <span className='wb-kpi-value'>{periodMetrics.winRate == null ? '—' : pct(periodMetrics.winRate)}</span>
          <span className='wb-kpi-note'>
            of {periodMetrics.trades.toLocaleString()} trades · profit factor {periodMetrics.profitFactor?.toFixed(2) ?? '—'}
            {was?.winRate != null && <> · Was {pct(was.winRate)}</>}
          </span>
        </div>
      </section>
      {settings.policy.enabled && (
        <Text size='sm' c='dimmed' mb='sm'>
          {volatility ? 'Effect of volatility scaling' : 'Effect of the pause rule'}{' '}
          <b className={signed(periodPnl - periodBaseline)}>{money(periodPnl - periodBaseline)}</b> vs always-on{' '}
          {money(periodBaseline)}
          {volatility && ` · average size ×${result.exposure.toFixed(2)}`}. Change it under Risk.
        </Text>
      )}
      <section className='wb-card' aria-label='P&L chart'>
        <div className='wb-card-head'>
          <div>
            <h2>P&amp;L</h2>
            <Text size='xs' c='dimmed'>
              {selected.length === 1
                ? `${strategyTitle(selected[0].name)} · ${selected[0].symbol} ${selected[0].timeframe}`
                : `${selected.length} strategies · ${periodStart} to ${settings.end}`}
            </Text>
          </div>
          <SegmentedControl
            aria-label='Chart view'
            size='xs'
            value={view}
            onChange={setChartMode}
            data={[
              { value: 'cumulative', label: 'Cumulative' },
              { value: 'daily', label: 'Daily' },
              { value: 'years', label: 'By year' },
            ]}
          />
        </div>
        {view === 'years' ? (
          <YearBars annual={annual} start={periodStart} end={settings.end} />
        ) : (
          <PnlChart
            points={periodPoints}
            mode={view}
            comparison={settings.policy.enabled}
            period={pnlPeriod}
            onPeriodChange={setPnlPeriod}
            showPeriod={false}
          />
        )}
      </section>
      <section className='wb-card' aria-label='Strategies'>
        <div className='wb-card-head'>
          <h2>
            Strategies <span className='wb-group-count'>{selected.length}</span>
          </h2>
          <Button size='xs' leftSection={<IconPlus size={14} />} onClick={() => setPickerOpen(true)}>
            Add strategy
          </Button>
        </div>
        <ScrollArea>
          <div className='wb-strategy-table' role='table' aria-label='Strategies in this portfolio' data-testid='selected-strategies'>
            <div role='row' className='is-head'>
              {['Strategy', 'Size', 'Net P&L', 'Max drawdown', 'Share of P&L', 'Recent form', ''].map((heading, index) => (
                <span role='columnheader' key={index}>{heading || <span className='visually-hidden'>Remove</span>}</span>
              ))}
            </div>
            {selected.map((item) => {
              const component = components.get(item.id);
              const copies = settings.copies[item.id] || 1;
              const update = tracking?.items[item.id];
              const updateNote = portfolioUpdatePresentation(item, update);
              const form = recentForm[item.id];
              const share = component && periodPnl ? component.pnl / periodPnl : null;
              const name = strategyTitle(item.name);
              return (
                <div role='row' key={item.id} className='wb-strategy-table-row'>
                  <div role='cell' className='wb-strategy-cell'>
                    <strong className='wb-book-name'>{name}</strong>
                    <span className='wb-strategy-cell-meta'>
                      <span className='wb-book-symbol'>{item.symbol}</span> {item.timeframe} · {item.start} – {update?.simulated_through || item.end}
                      {updateNote.attention && <span className='wb-book-update-attention' title={updateNote.title}> · {updateNote.label}</span>}
                      {update?.status === 'failed' && (
                        <button type='button' className='wb-link-button' onClick={() => void retryTracking(item.id)}> Retry update</button>
                      )}
                    </span>
                    <StrategyStageBadge {...collectiveProgress(item)} compact />
                  </div>
                  <div role='cell' className='wb-size-stepper'>
                    <ActionIcon size='sm' variant='default' aria-label={`Decrease size of ${name}`} disabled={copies <= 1} onClick={() => setCopies(item.id, copies - 1)}>
                      <IconMinus size={12} />
                    </ActionIcon>
                    <span aria-label={`Size ${copies} times`}>{copies}×</span>
                    <ActionIcon size='sm' variant='default' aria-label={`Increase size of ${name}`} disabled={copies >= 100} onClick={() => setCopies(item.id, copies + 1)}>
                      <IconPlus size={12} />
                    </ActionIcon>
                  </div>
                  <span role='cell' className={`mono ${component ? signed(component.pnl) : ''}`}>{component ? wholeMoney(component.pnl) : '—'}</span>
                  <span role='cell' className='mono wb-loss'>{component ? wholeMoney(-component.maxDrawdownDollars) : '—'}</span>
                  <span role='cell' className='mono'>{share == null ? '—' : `${Math.round(share * 100)}%`}</span>
                  <span role='cell'>
                    {form ? <a className={`wb-form is-${form.tone}`} href={href('portfolio', 'risk')}>{form.label}</a> : '—'}
                  </span>
                  <span role='cell'>
                    <ActionIcon
                      variant='subtle'
                      color='gray'
                      size='sm'
                      aria-label={`Remove ${name} ${item.symbol} ${item.timeframe}`}
                      title='Remove from portfolio'
                      onClick={() => {
                        const next = { ...settings.copies };
                        delete next[item.id];
                        choose(next);
                      }}
                    >
                      <IconX size={14} />
                    </ActionIcon>
                  </span>
                </div>
              );
            })}
          </div>
        </ScrollArea>
        {selected.length === 1 ? (
          <button type='button' className='wb-add-hint' onClick={() => setPickerOpen(true)}>
            <IconPlus size={14} /> Add another strategy to see how they combine. Drawdowns often offset each other.
          </button>
        ) : worstSingle && periodMetrics.maxDrawdownDollars < worstSingle.maxDrawdownDollars ? (
          <Text size='sm' c='dimmed' mt='sm'>
            The combined drawdown ({money(-periodMetrics.maxDrawdownDollars)}) is smaller than {strategyTitle(worstSingle.name)}’s
            alone ({money(-worstSingle.maxDrawdownDollars)}): their losing stretches don’t line up. Adjust <b>Size</b> to lean on
            the steadier strategies.
          </Text>
        ) : null}
      </section>
      <footer className='wb-portfolio-foot'>
        {settings.basis === 'marked' ? 'Daily P&L marked at close (UTC)' : 'P&L counted when trades close (UTC)'}, net of
        recorded fees and slippage. Each strategy runs as its own book: no position netting or shared margin.{' '}
        <button type='button' className='wb-link-button' onClick={onSettings}>Change accounting or export</button>
      </footer>
    </>
  );
}

export function CollectiveCalendarView({ model }: { model: Model }) {
  const [chartOpen, setChartOpen] = useState(false);
  const {
    day,
    month,
    result,
    selected,
    selectedDay,
    setDay,
    setMonth,
    settings,
  } = model;
  if (!result) return <CollectiveEmptyState model={model} />;
  const dayIndex = day
    ? result.points.findIndex((point) => point.date === day)
    : -1;

  return (
    <div className='wb-calendar-layout'>
      <Calendar
        points={result.points}
        month={month}
        onMonth={setMonth}
        onDay={setDay}
        selected={day}
      />
      <section className='wb-card' aria-live='polite'>
        {selectedDay ? (
          <>
            <Group justify='space-between' gap='xs'>
              <h2 className='wb-day-label'>
                {new Date(`${day}T00:00:00Z`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })}
              </h2>
              <Button size='compact-sm' variant='light' onClick={() => setChartOpen(true)}>
                View chart
              </Button>
            </Group>
            <div
              className='wb-day-total'
              style={{ color: tone(selectedDay.pnl) }}
            >
              {money(selectedDay.pnl)}
            </div>
            <Text size='sm' c='dimmed'>
              {selectedDay.trades} closed trades ·{' '}
              {settings.basis === 'marked'
                ? 'marked changes can occur without an exit.'
                : 'only trades closing this day contribute.'}
            </Text>
            <Text size='xs' fw={600} c='dimmed' mt='md' tt='uppercase'>By strategy</Text>
            <Table mt={4}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Strategy</Table.Th>
                  <Table.Th ta='right'>Contribution</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {[...selected]
                  .sort(
                    (a, b) =>
                      Math.abs(selectedDay.byStrategy[b.id] || 0) -
                      Math.abs(selectedDay.byStrategy[a.id] || 0),
                  )
                  .map((item) => {
                    const value = selectedDay.byStrategy[item.id] || 0;
                    return (
                      <Table.Tr key={item.id}>
                        <Table.Td>
                          <Text size='sm' fw={600}>
                            {strategyTitle(item.name)}
                          </Text>
                          <StrategyStageBadge {...collectiveProgress(item)} />
                          <Text size='xs' c='dimmed'>
                            {item.symbol} · {item.timeframe}
                          </Text>
                        </Table.Td>
                        <Table.Td
                          ta='right'
                          c={value ? tone(value) : 'dimmed'}
                          className='mono'
                        >
                          {money(value)}
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
              </Table.Tbody>
            </Table>
            <Group justify='space-between' mt='md'>
              <Button
                size='compact-sm'
                variant='default'
                leftSection={<IconChevronLeft size={13} />}
                disabled={dayIndex <= 0}
                onClick={() => {
                  const previous = result.points[dayIndex - 1].date;
                  setDay(previous);
                  setMonth(previous.slice(0, 7));
                }}
              >
                Previous day
              </Button>
              <Button
                size='compact-sm'
                variant='default'
                rightSection={<IconChevronRight size={13} />}
                disabled={dayIndex < 0 || dayIndex >= result.points.length - 1}
                onClick={() => {
                  const next = result.points[dayIndex + 1].date;
                  setDay(next);
                  setMonth(next.slice(0, 7));
                }}
              >
                Next day
              </Button>
            </Group>
          </>
        ) : (
          <>
            <h2>Pick a day</h2>
            <p className='wb-card-sub'>
              Click any covered date to see each strategy’s contribution to
              that day.
            </p>
          </>
        )}
      </section>
      {chartOpen && selectedDay && model.chartItems.length > 0 &&
        <DayTradeViewer day={day} items={model.chartItems}
          initialId={[...model.chartItems].sort((a, b) =>
            (selectedDay.byStrategyTrades?.[b.id] || 0) - (selectedDay.byStrategyTrades?.[a.id] || 0))[0].id}
          copies={settings.copies} replays={result.tradeReplays} limits={settings}
          previous={result.points[dayIndex - 1]?.date} next={result.points[dayIndex + 1]?.date}
          onDay={value => { setDay(value); setMonth(value.slice(0, 7)); }} onClose={() => setChartOpen(false)}/>}
    </div>
  );
}

export function CollectiveContributionsView({ model }: { model: Model }) {
  const {
    accountingLabel,
    periodComponents,
    periodStart,
    pnlPeriod,
    result,
    selected,
    setPnlPeriod,
    settings,
    volatility,
  } = model;
  if (!result) return <CollectiveEmptyState model={model} />;

  return (
    <section className='wb-card'>
      <div className='wb-card-head'>
        <div>
          <h2>Every strategy’s contribution</h2>
          <Text size='xs' c='dimmed'>
            {periodStart} to {settings.end} · {accountingLabel}
          </Text>
        </div>
        <PortfolioPeriodSelector value={pnlPeriod} onChange={setPnlPeriod} />
      </div>
      <ScrollArea>
        <Table miw={1040} data-testid='strategy-contributions' highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Strategy</Table.Th>
              <Table.Th>Chart</Table.Th>
              <Table.Th ta='right'>Net P&amp;L</Table.Th>
              <Table.Th ta='right'>Maximum drawdown</Table.Th>
              <Table.Th ta='right'>Return contribution</Table.Th>
              <Table.Th ta='right'>Always on</Table.Th>
              <Table.Th ta='right'>Closed trades</Table.Th>
              <Table.Th ta='right'>Skipped</Table.Th>
              <Table.Th>At cutoff</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {periodComponents.map((component) => (
              <Table.Tr key={component.id}>
                <Table.Td>
                  <Text size='sm' fw={600}>
                    {strategyTitle(component.name)}
                  </Text>
                  {selected.find((item) => item.id === component.id) && (
                    <StrategyStageBadge
                      {...collectiveProgress(
                        selected.find((item) => item.id === component.id)!,
                      )}
                    />
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size='sm'>
                    {component.symbol} · {component.timeframe}
                  </Text>
                  <Text size='xs' c='dimmed'>
                    {component.session}
                  </Text>
                </Table.Td>
                <Table.Td ta='right' c={tone(component.pnl)} className='mono'>
                  {money(component.pnl)}
                </Table.Td>
                <Table.Td
                  ta='right'
                  c={component.maxDrawdownDollars > 0 ? 'red' : undefined}
                  className='mono'
                >
                  {money(component.maxDrawdownDollars)}
                </Table.Td>
                <Table.Td ta='right' c={tone(component.pnl)} className='mono'>
                  {pct(component.pnl / result.capital)}
                </Table.Td>
                <Table.Td ta='right' className='mono'>
                  {money(component.baseline)}
                </Table.Td>
                <Table.Td ta='right'>{component.trades}</Table.Td>
                <Table.Td ta='right'>{component.skipped}</Table.Td>
                <Table.Td>
                  <Badge
                    color={stateColor[component.state]}
                    radius='xs'
                    variant='light'
                  >
                    {settings.policy.enabled
                      ? component.state === 'Active'
                        ? 'Enabled'
                        : component.state
                      : 'Always on'}
                  </Badge>
                  {volatility && settings.policy.enabled && (
                    <Text size='xs' c='dimmed'>
                      average size ×{component.exposure.toFixed(2)}
                    </Text>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
      <Text size='xs' c='dimmed' mt='sm'>
        Maximum drawdown is each strategy's largest peak-to-trough dollar loss
        over the displayed period, using {accountingLabel}, selected copies and
        active replay settings. Individual drawdowns do not add up to portfolio
        drawdown.
      </Text>
    </section>
  );
}
