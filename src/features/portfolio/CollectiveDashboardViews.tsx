import {
  Badge,
  Button,
  Group,
  ScrollArea,
  Select,
  Table,
  Text,
} from '@mantine/core';
import {
  IconChevronLeft,
  IconChevronRight,
  IconPlus,
} from '@tabler/icons-react';
import type { CollectiveDashboardModel } from './useCollectiveDashboardModel';
import type { PortfolioPnlPeriod } from '../../../shared/ts/portfolioPeriods.ts';
import { collectiveProgress } from '../../../shared/ts/progress.ts';
import { StrategyStageBadge } from '../../shared/ui/StrategyStageBadge';
import {
  formatMoney as money,
  formatPercent as pct,
  coverageEndExplanation,
  gateStateColor as stateColor,
  signedClass as signed,
  valueTone as tone,
  weekday,
} from './collectiveViewModel';
import {
  CollectiveCalendar as Calendar,
  CollectivePnlChart as PnlChart,
} from './CollectivePresentation';
import { PortfolioPeriodSelector } from './PortfolioPeriodSelector';

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

export function CollectiveOverviewView({ model }: { model: Model }) {
  const {
    annual,
    chartMode,
    pnlPeriod,
    periodMetrics,
    periodPoints,
    periodPnl,
    periodStart,
    result,
    selected,
    setChartMode,
    setPnlPeriod,
    settings,
    totals,
    volatility,
  } = model;
  if (!result || !periodMetrics) return <CollectiveEmptyState model={model} />;
  const periodBaseline = periodPoints.reduce((total, point) => total + point.baseline, 0);

  return (
    <>
      <div className='wb-kpis' data-testid='portfolio-metrics'>
        <div className='wb-kpi lead'>
          <span className='wb-kpi-label'>Combined net P&amp;L · {periodLabels[pnlPeriod]}</span>
          <span className={`wb-kpi-value ${signed(periodPnl)}`} data-testid='portfolio-pnl'>
            {money(periodPnl)}
          </span>
          <span className='wb-kpi-note'>
            {pct(periodPnl / result.capital)} on total portfolio capital · {periodStart} to {settings.end}
          </span>
        </div>
        <div className='wb-kpi'>
          <span className='wb-kpi-label'>Maximum drawdown</span>
          <span className='wb-kpi-value'>
            {money(periodMetrics.maxDrawdownDollars)}
          </span>
          <span className='wb-kpi-note'>
            {pct(Math.abs(periodMetrics.maxDrawdown))} ·{' '}
            {settings.basis === 'marked'
              ? 'daily closes'
              : 'closed trades only'}
          </span>
        </div>
        <div className='wb-kpi'>
          <span className='wb-kpi-label'>Combination score</span>
          <span className='wb-kpi-value'>
            {periodMetrics.recoveryFactor?.toFixed(2) || 'Undefined'}
          </span>
          <span className='wb-kpi-note'>
            Period net P&amp;L ÷ max drawdown dollars
          </span>
        </div>
        <div className='wb-kpi'>
          <span className='wb-kpi-label'>Profit factor</span>
          <span className='wb-kpi-value'>
            {periodMetrics.profitFactor?.toFixed(2) ?? 'No finite ratio'}
          </span>
          <span className='wb-kpi-note'>Closed-trade gains ÷ losses</span>
        </div>
      </div>
      <div className='wb-kpi-sub'>
        <span>
          Winning trades{' '}
          <b>{periodMetrics.winRate == null ? 'none' : pct(periodMetrics.winRate)}</b> of{' '}
          {periodMetrics.trades.toLocaleString()}
        </span>
        <span>
          Positive days{' '}
          <b>
            {periodMetrics.positiveDays} / {periodMetrics.activeDays}
          </b>
        </span>
        <span>
          Total portfolio capital <b>{money(result.capital)}</b>
        </span>
        {settings.policy.enabled && (
          <span>
            {volatility
              ? 'Effect of volatility scaling'
              : 'Effect of pause rule'}{' '}
            <b className={signed(periodPnl - periodBaseline)}>
              {money(periodPnl - periodBaseline)}
            </b>{' '}
            vs always-on {money(periodBaseline)}
            {volatility && ` · average size ×${result.exposure.toFixed(2)}`}
          </span>
        )}
      </div>
      {pnlPeriod !== 'all' && settings.policy.enabled && volatility && (
        <Text size='xs' c='dimmed' mb='sm'>
          Average size uses the full selected history.
        </Text>
      )}
      <section className='wb-card'>
        <div className='wb-card-head'>
          <h2>Portfolio P&amp;L</h2>
          <Select
            aria-label='P&L chart mode'
            size='xs'
            w={220}
            maw='100%'
            value={chartMode}
            onChange={(value) => setChartMode(value || 'cumulative')}
            data={[
              { value: 'cumulative', label: 'Cumulative by market' },
              { value: 'daily', label: 'Daily P&L bars' },
            ]}
          />
        </div>
        <PnlChart
          points={periodPoints}
          mode={chartMode}
          comparison={settings.policy.enabled}
          period={pnlPeriod}
          onPeriodChange={setPnlPeriod}
        />
      </section>
      <div className='wb-two'>
        <section className='wb-card'>
          <h2>P&amp;L by market · {periodLabels[pnlPeriod]}</h2>
          <Table data-testid='market-contributions' mt={6}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Market</Table.Th>
                <Table.Th ta='right'>Books</Table.Th>
                <Table.Th ta='right'>Net P&amp;L</Table.Th>
                <Table.Th w='28%' />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {Object.entries(totals)
                .sort()
                .map(([symbol, pnl]) => {
                  const scale = Math.max(
                    1,
                    ...Object.values(totals).map(Math.abs),
                  );
                  return (
                    <Table.Tr key={symbol}>
                      <Table.Td>{symbol}</Table.Td>
                      <Table.Td ta='right'>
                        {
                          selected.filter((item) => item.symbol === symbol)
                            .length
                        }
                      </Table.Td>
                      <Table.Td ta='right' c={tone(pnl)} className='mono'>
                        {money(pnl)}
                      </Table.Td>
                      <Table.Td>
                        <div
                          className='collective-bar'
                          style={{
                            width: `${(Math.abs(pnl) / scale) * 100}%`,
                            background: tone(pnl),
                          }}
                        />
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
            </Table.Tbody>
          </Table>
        </section>
        <section className='wb-card'>
          <h2>P&amp;L by year · {periodLabels[pnlPeriod]}</h2>
          <Table mt={6}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Year</Table.Th>
                <Table.Th ta='right'>Net P&amp;L</Table.Th>
                <Table.Th w='35%' />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {Object.entries(annual)
                .sort()
                .map(([year, pnl]) => {
                  const scale = Math.max(
                    1,
                    ...Object.values(annual).map(Math.abs),
                  );
                  return (
                    <Table.Tr key={year}>
                      <Table.Td>
                        {year}
                        {periodStart > `${year}-01-01` || settings.end < `${year}-12-31` ? (
                          <Text span size='xs' c='dimmed'>
                            {' '}
                            partial
                          </Text>
                        ) : null}
                      </Table.Td>
                      <Table.Td ta='right' c={tone(pnl)} className='mono'>
                        {money(pnl)}
                      </Table.Td>
                      <Table.Td>
                        <div
                          className='collective-bar'
                          style={{
                            width: `${(Math.abs(pnl) / scale) * 100}%`,
                            background: tone(pnl),
                          }}
                        />
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
            </Table.Tbody>
          </Table>
        </section>
      </div>
    </>
  );
}

export function CollectiveCalendarView({ model }: { model: Model }) {
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
            <h2 className='wb-day-label'>
              {weekday(day)} {day}
            </h2>
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
            <Table mt='sm'>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Strategy / chart</Table.Th>
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
                            {item.name}
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
                    {component.name}
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
