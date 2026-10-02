import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  chartDateTicks,
  formatChartAxisDate,
  formatChartAxisMoney,
  niceChartScale,
  rebaseChartPoints,
  visibleChartPoints,
} from '../../src/features/portfolio/collectiveChartScale.ts';

const dated = (...dates) => dates.map((date) => ({ date }));
const datesOf = (points) => points.map((point) => point.date);

function assertReadableScale(scale, values) {
  assert.ok(Number.isFinite(scale.min));
  assert.ok(Number.isFinite(scale.max));
  assert.ok(scale.max > scale.min);
  assert.ok(Array.isArray(scale.ticks));
  assert.ok(scale.ticks.length >= 2);
  assert.ok(scale.ticks.every(Number.isFinite));
  for (const value of values) {
    assert.ok(scale.min <= value && value <= scale.max, `${value} is outside the chart scale`);
  }

  const steps = scale.ticks.slice(1).map((tick, index) => tick - scale.ticks[index]);
  assert.ok(steps.every((step) => step > 0));
  const step = steps[0];
  assert.ok(steps.every((other) => Math.abs(other - step) <= step * 1e-8));
  const normalized = step / 10 ** Math.floor(Math.log10(step));
  assert.ok(
    [1, 2, 2.5, 5, 10].some((nice) => Math.abs(normalized - nice) < 1e-8),
    `tick interval ${step} should be a readable rounded amount`,
  );
}

test('chart ranges use inclusive calendar boundaries, including month ends', () => {
  const points = dated(
    '2025-03-30',
    '2025-03-31',
    '2025-09-29',
    '2025-09-30',
    '2025-12-30',
    '2025-12-31',
    '2026-02-27',
    '2026-02-28',
    '2026-03-31',
  );

  assert.deepEqual(datesOf(visibleChartPoints(points, '1m')), [
    '2026-02-28',
    '2026-03-31',
  ]);
  assert.deepEqual(datesOf(visibleChartPoints(points, '3m')), [
    '2025-12-31',
    '2026-02-27',
    '2026-02-28',
    '2026-03-31',
  ]);
  assert.deepEqual(datesOf(visibleChartPoints(points, '6m')), [
    '2025-09-30',
    '2025-12-30',
    '2025-12-31',
    '2026-02-27',
    '2026-02-28',
    '2026-03-31',
  ]);
  assert.deepEqual(datesOf(visibleChartPoints(points, '1y')), datesOf(points.slice(1)));
  assert.deepEqual(datesOf(visibleChartPoints(points, 'all')), datesOf(points));

  const leapYear = dated('2024-02-28', '2024-02-29', '2024-03-31');
  assert.deepEqual(datesOf(visibleChartPoints(leapYear, '1m')), [
    '2024-02-29',
    '2024-03-31',
  ]);
  assert.deepEqual(visibleChartPoints([], 'all'), []);
});

test('period chart totals start from the selected days and agree with period P&L', () => {
  const points = [
    { date: '2026-08-30', pnl: -20, baseline: -10, cumulative: 980, baselineCumulative: 490, bySymbol: { ES: -15, NQ: -5 } },
    { date: '2026-09-30', pnl: 30, baseline: 25, cumulative: 1010, baselineCumulative: 515, bySymbol: { ES: 20, NQ: 10 } },
  ];
  const chart = rebaseChartPoints(points, ['ES', 'NQ']);
  assert.deepEqual(chart.map((point) => point.cumulative), [-20, 10]);
  assert.deepEqual(chart.map((point) => point.baselineCumulative), [-10, 15]);
  assert.deepEqual(chart.map((point) => point.markets), [
    { ES: -15, NQ: -5 },
    { ES: 5, NQ: 5 },
  ]);
  assert.equal(chart.at(-1).cumulative, points.reduce((sum, point) => sum + point.pnl, 0));
});

test('full view includes zero and labels its dollar axis with rounded steps', () => {
  const values = [-40_100, 0, 122_300, 284_700];
  const scale = niceChartScale(values, true);

  assertReadableScale(scale, values);
  assert.ok(scale.ticks.some((tick) => tick === 0));
  assert.ok(scale.ticks[0] >= scale.min);
  assert.ok(scale.ticks.at(-1) <= scale.max);
});

test('a zoomed positive view scales to visible points rather than a hidden outlier or zero', () => {
  const points = [
    { date: '2025-01-01', cumulative: -1_000_000 },
    { date: '2026-08-01', cumulative: 125_432 },
    { date: '2026-08-15', cumulative: 125_837 },
    { date: '2026-08-31', cumulative: 126_177 },
  ];
  const visible = visibleChartPoints(points, '1m');
  const values = visible.map((point) => point.cumulative);
  const scale = niceChartScale(values, false);

  assert.deepEqual(datesOf(visible), datesOf(points.slice(1)));
  assertReadableScale(scale, values);
  assert.ok(scale.min > 0, 'zoomed positive data should use the available vertical space');
  assert.ok(scale.max < 200_000, 'the hidden outlier should not affect visible scale');
});

test('flat and empty data still produce finite nonzero chart domains', () => {
  const flat = niceChartScale([42, 42, 42], false);
  const empty = niceChartScale([], true);

  assertReadableScale(flat, [42]);
  assertReadableScale(empty, [0]);
  assert.ok(empty.ticks.includes(0));
});

test('tight zoom levels give each dollar tick a distinct label', () => {
  for (const values of [[125_432, 125_500], [1_250_000, 1_251_000]]) {
    const scale = niceChartScale(values);
    const step = scale.ticks[1] - scale.ticks[0];
    const maximum = Math.max(Math.abs(scale.min), Math.abs(scale.max));
    const labels = scale.ticks.map((value) => formatChartAxisMoney(value, step, maximum));
    assert.equal(new Set(labels).size, labels.length, labels.join(', '));
  }
});

test('submonthly date ticks include a day even on a wide six-month view', () => {
  const ticks = chartDateTicks('2026-04-01', '2026-09-28', 1600);
  const gapDays = (Date.parse(ticks[1]) - Date.parse(ticks[0])) / 86_400_000;
  const labels = ticks.map((date) => formatChartAxisDate(date, gapDays));
  assert.ok(gapDays < 28);
  assert.equal(new Set(labels).size, labels.length, labels.join(', '));
});

test('narrow one-month charts still show both end dates', () => {
  const ticks = chartDateTicks('2026-08-28', '2026-09-28', 210);
  assert.deepEqual(ticks, ['2026-08-28', '2026-09-28']);
  assert.deepEqual(ticks.map((date) => formatChartAxisDate(date, 31, 31)), ['Aug 28', 'Sep 28']);
});
