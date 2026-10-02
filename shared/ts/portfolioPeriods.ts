import type { DailyPoint } from "./portfolio.ts";
import type { PortfolioResult } from "./collective.ts";

export type PortfolioPnlPeriod = "all" | "1y" | "ytd" | "6m" | "1m";

type DatedPnl = { date: string; pnl: number };

function isFullPortfolioPeriod(result: PortfolioResult, periodPoints: readonly DailyPoint[]): boolean {
  return periodPoints.length === result.points.length &&
    periodPoints.every((point, index) => point.date === result.points[index].date);
}

function daysInMonth(year: number, month: number): number {
  if (month === 2)
    return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

function monthsBefore(date: string, months: number): string {
  const [year, month, day] = date.split("-").map(Number);
  const monthIndex = year * 12 + month - 1 - months;
  const targetYear = Math.floor(monthIndex / 12);
  const targetMonth = monthIndex - targetYear * 12 + 1;
  const targetDay = Math.min(day, daysInMonth(targetYear, targetMonth));
  return `${String(targetYear).padStart(4, "0")}-${String(targetMonth).padStart(2, "0")}-${String(targetDay).padStart(2, "0")}`;
}

/** Both start and end dates are included. The selected window limits every period. */
export function portfolioPeriodStart(
  period: PortfolioPnlPeriod,
  selectedStart: string,
  selectedEnd: string,
): string {
  const requested = period === "all"
    ? selectedStart
    : period === "ytd"
      ? `${selectedEnd.slice(0, 4)}-01-01`
      : monthsBefore(selectedEnd, period === "1y" ? 12 : period === "6m" ? 6 : 1);
  return requested > selectedStart ? requested : selectedStart;
}

/** Select from a completed portfolio replay without resetting its path-dependent controls. */
export function portfolioPeriodPoints<T extends DatedPnl>(
  points: readonly T[],
  period: PortfolioPnlPeriod,
  selectedStart: string,
  selectedEnd: string,
): T[] {
  const start = portfolioPeriodStart(period, selectedStart, selectedEnd);
  return points.filter((point) => point.date >= start && point.date <= selectedEnd);
}

export function portfolioPeriodPnl(
  points: readonly DatedPnl[],
  period: PortfolioPnlPeriod,
  selectedStart: string,
  selectedEnd: string,
): number {
  return portfolioPeriodPoints(points, period, selectedStart, selectedEnd)
    .reduce((total, point) => total + point.pnl, 0);
}

/** Recompute summary metrics from the displayed daily replay window. */
export function portfolioPeriodMetrics(
  result: PortfolioResult,
  periodPoints: readonly DailyPoint[],
) {
  // Retain exact aggregate values when the selected window spans the replay.
  // Daily regrouping can change the last floating point digit of trade sums.
  if (isFullPortfolioPeriod(result, periodPoints)) return {
    maxDrawdownDollars: result.maxDrawdownDollars,
    maxDrawdown: result.maxDrawdown,
    recoveryFactor: result.recoveryFactor,
    profitFactor: result.profitFactor,
    winRate: result.winRate,
    trades: result.trades,
    positiveDays: result.positiveDays,
    activeDays: result.activeDays,
  };

  let cumulative = 0;
  let peak = result.capital;
  let maxDrawdownDollars = 0;
  let maxDrawdown = 0;
  let grossProfit = 0;
  let grossLoss = 0;
  let winningTrades = 0;
  let trades = 0;
  let positiveDays = 0;
  let activeDays = 0;
  let tradeOutcomesAvailable = true;
  for (const point of periodPoints) {
    cumulative += point.pnl;
    const equity = result.capital + cumulative;
    peak = Math.max(peak, equity);
    maxDrawdownDollars = Math.max(maxDrawdownDollars, peak - equity);
    maxDrawdown = Math.min(maxDrawdown, equity / peak - 1);
    trades += point.trades;
    if (point.pnl > 0) positiveDays++;
    if (point.pnl !== 0 || point.trades > 0) activeDays++;
    if (point.trades > 0 &&
      (point.grossProfit === undefined || point.grossLoss === undefined || point.winningTrades === undefined))
      tradeOutcomesAvailable = false;
    grossProfit += point.grossProfit || 0;
    grossLoss += point.grossLoss || 0;
    winningTrades += point.winningTrades || 0;
  }
  return {
    maxDrawdownDollars,
    maxDrawdown,
    recoveryFactor: maxDrawdownDollars ? cumulative / maxDrawdownDollars : null,
    profitFactor: tradeOutcomesAvailable && grossLoss > 0 ? grossProfit / grossLoss : null,
    winRate: tradeOutcomesAvailable && trades > 0 ? winningTrades / trades : null,
    trades,
    positiveDays,
    activeDays,
  };
}

/** Contributions over displayed days, retaining each strategy's cutoff state. */
export function portfolioPeriodComponents(
  result: PortfolioResult,
  periodPoints: readonly DailyPoint[],
): PortfolioResult["components"] {
  if (isFullPortfolioPeriod(result, periodPoints)) return result.components;
  return result.components.map((component) => {
    let pnl = 0;
    let baseline = 0;
    let peak = 0;
    let maxDrawdownDollars = 0;
    let trades = 0;
    let skipped = 0;
    let weightTotal = 0;
    for (const point of periodPoints) {
      pnl += point.byStrategy[component.id] || 0;
      baseline += point.byStrategyBaseline?.[component.id] || 0;
      trades += point.byStrategyTrades?.[component.id] || 0;
      skipped += point.byStrategySkipped?.[component.id] || 0;
      weightTotal += point.byStrategyWeight?.[component.id] || 0;
      peak = Math.max(peak, pnl);
      maxDrawdownDollars = Math.max(maxDrawdownDollars, peak - pnl);
    }
    return {
      ...component,
      pnl,
      baseline,
      maxDrawdownDollars,
      trades,
      skipped,
      exposure: trades + skipped ? weightTotal / (trades + skipped) : 0,
    };
  });
}
