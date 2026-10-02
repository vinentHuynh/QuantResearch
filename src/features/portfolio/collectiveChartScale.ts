import type { DailyPoint } from "../../../shared/ts/portfolio.ts";

export type RebasedChartPoint = DailyPoint & { time: number; markets: Record<string, number> };

/** Chart values are cumulative within the chosen P&L period, not since the full replay start. */
export function rebaseChartPoints(points: DailyPoint[], symbols: string[]): RebasedChartPoint[] {
  const totals: Record<string, number> = {};
  let cumulative = 0;
  let baselineCumulative = 0;
  return points.map((point) => {
    cumulative += point.pnl;
    baselineCumulative += point.baseline;
    const markets = Object.fromEntries(symbols.map((symbol) => {
      totals[symbol] = (totals[symbol] || 0) + (point.bySymbol[symbol] || 0);
      return [symbol, totals[symbol]];
    }));
    return { ...point, cumulative, baselineCumulative, time: Date.parse(`${point.date}T00:00:00Z`), markets };
  });
}

export type ChartRange = "1m" | "3m" | "6m" | "1y" | "all";

const rangeMonths: Record<Exclude<ChartRange, "all">, number> = {
  "1m": 1,
  "3m": 3,
  "6m": 6,
  "1y": 12,
};

export function visibleChartPoints<T extends { date: string }>(points: T[], range: ChartRange): T[] {
  if (range === "all" || points.length === 0) return points;
  const [year, month, day] = points[points.length - 1].date.split("-").map(Number);
  const firstOfMonth = new Date(Date.UTC(year, month - 1 - rangeMonths[range], 1));
  const lastDay = new Date(Date.UTC(firstOfMonth.getUTCFullYear(), firstOfMonth.getUTCMonth() + 1, 0)).getUTCDate();
  firstOfMonth.setUTCDate(Math.min(day, lastDay));
  const cutoff = firstOfMonth.toISOString().slice(0, 10);
  return points.filter((point) => point.date >= cutoff);
}

export function niceChartScale(values: number[], includeZero = false): { min: number; max: number; ticks: number[] } {
  const finite = values.filter(Number.isFinite);
  if (finite.length === 0) return { min: -1, max: 1, ticks: [-1, 0, 1] };

  let low = Math.min(...finite);
  let high = Math.max(...finite);
  if (includeZero) {
    low = Math.min(low, 0);
    high = Math.max(high, 0);
  }
  if (low === high) {
    const padding = Math.max(1, Math.abs(low) * 0.05);
    low -= padding;
    high += padding;
  }
  const padding = (high - low) * 0.025;
  low -= padding;
  high += padding;
  const roughStep = (high - low) / 6;
  const magnitude = Math.pow(10, Math.floor(Math.log10(roughStep)));
  const steps = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50].map((factor) => factor * magnitude);
  let best = { step: steps[0], min: 0, max: 0, count: Infinity, score: Infinity };
  for (const step of steps) {
    const min = Math.floor(low / step) * step;
    const max = Math.ceil(high / step) * step;
    const count = Math.round((max - min) / step) + 1;
    if (count < 3 || count > 9) continue;
    const extraSpace = (max - min - (high - low)) / (high - low);
    const score = Math.abs(count - 7) * 0.4 + extraSpace * 4 + Math.max(0, count - 8) * 2;
    if (score < best.score) best = { step, min, max, count, score };
  }
  const ticks = Array.from({ length: best.count }, (_, index) =>
    Number((best.min + index * best.step).toPrecision(12)),
  );
  return { min: ticks[0], max: ticks[ticks.length - 1], ticks };
}

export function formatChartAxisMoney(value: number, step: number, maximum: number): string {
  if (value === 0) return "$0";
  let unit = 1;
  let suffix = "";
  for (const [candidate, label] of [[1_000_000, "M"], [1_000, "K"]] as const) {
    if (maximum < candidate || step / candidate < 0.01) continue;
    const scaledStep = step / candidate;
    const decimals = [0, 1, 2].find((digits) =>
      Math.abs(scaledStep * 10 ** digits - Math.round(scaledStep * 10 ** digits)) < 1e-8,
    );
    if (decimals !== undefined) {
      unit = candidate;
      suffix = label;
      break;
    }
  }
  const scaledStep = step / unit;
  const decimals = [0, 1, 2].find((digits) =>
    Math.abs(scaledStep * 10 ** digits - Math.round(scaledStep * 10 ** digits)) < 1e-8,
  ) ?? 2;
  const amount = (Math.abs(value) / unit).toLocaleString("en-US", { maximumFractionDigits: decimals });
  return `${value < 0 ? "-" : ""}$${amount}${suffix}`;
}

export function formatChartAxisDate(date: string, tickGapDays: number, spanDays = Infinity): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
    timeZone: "UTC",
    month: "short",
    ...(tickGapDays < 28 || spanDays <= 45 ? { day: "numeric" as const } : { year: "numeric" as const }),
  });
}

const DAY = 24 * 60 * 60 * 1000;

export function chartDateTicks(start: string, end: string, plotWidth: number): string[] {
  const startTime = Date.parse(`${start}T00:00:00Z`);
  const endTime = Date.parse(`${end}T00:00:00Z`);
  if (!Number.isFinite(startTime) || !Number.isFinite(endTime) || endTime <= startTime) return start ? [start] : [];
  const spanDays = (endTime - startTime) / DAY;
  const desired = spanDays / Math.max(2, Math.floor(plotWidth / 120));
  const intervals = [
    { unit: "day", step: 1, days: 1 },
    { unit: "day", step: 2, days: 2 },
    { unit: "day", step: 7, days: 7 },
    { unit: "day", step: 14, days: 14 },
    { unit: "month", step: 1, days: 30 },
    { unit: "month", step: 2, days: 61 },
    { unit: "month", step: 3, days: 91 },
    { unit: "month", step: 6, days: 183 },
    { unit: "month", step: 12, days: 365 },
    { unit: "month", step: 24, days: 730 },
  ] as const;
  const interval = intervals.find((candidate) => candidate.days >= desired) || intervals[intervals.length - 1];
  const ticks: string[] = [];
  if (interval.unit === "day") {
    const first = Math.ceil(startTime / (DAY * interval.step)) * DAY * interval.step;
    for (let time = first; time <= endTime; time += DAY * interval.step) {
      ticks.push(new Date(time).toISOString().slice(0, 10));
    }
  } else {
    const firstDate = new Date(startTime);
    const monthIndex = firstDate.getUTCFullYear() * 12 + firstDate.getUTCMonth();
    for (let index = Math.ceil(monthIndex / interval.step) * interval.step; ; index += interval.step) {
      const time = Date.UTC(Math.floor(index / 12), index % 12, 1);
      if (time > endTime) break;
      if (time >= startTime) ticks.push(new Date(time).toISOString().slice(0, 10));
    }
  }
  return ticks.length >= 2 ? ticks : [start, end];
}
