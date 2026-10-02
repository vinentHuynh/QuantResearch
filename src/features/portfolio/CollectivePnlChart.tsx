import { useEffect, useId, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Text } from "@mantine/core";
import type { DailyPoint } from "../../../shared/ts/portfolio.ts";
import type { PortfolioPnlPeriod } from "../../../shared/ts/portfolioPeriods.ts";
import { formatMoney as money, valueTone as tone } from "./collectiveViewModel";
import { chartDateTicks, formatChartAxisDate, formatChartAxisMoney, niceChartScale, rebaseChartPoints, type RebasedChartPoint } from "./collectiveChartScale";
import { PortfolioPeriodSelector } from "./PortfolioPeriodSelector";

const CHART_COLORS = ["#367ca5", "#9a628b", "#a8741f", "#4f7f3f", "#587382"];
const COMBINED_COLOR = "#17765c";
const BASELINE_COLOR = "#687484";

type ChartSeries = { key: string; label: string; color: string };

function seriesValue(point: RebasedChartPoint, key: string): number {
  if (key === "combined") return point.cumulative;
  if (key === "baseline") return point.baselineCumulative;
  return point.markets[key.slice(7)] || 0;
}

function closestPoint(points: RebasedChartPoint[], time: number): number {
  let low = 0;
  let high = points.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (points[middle].time < time) low = middle + 1;
    else high = middle;
  }
  if (low > 0 && Math.abs(points[low - 1].time - time) <= Math.abs(points[low].time - time)) return low - 1;
  return low;
}

export function CollectivePnlChart({ points, mode, comparison, period, onPeriodChange }: {
  points: DailyPoint[];
  mode: string;
  comparison: boolean;
  period: PortfolioPnlPeriod;
  onPeriodChange: (period: PortfolioPnlPeriod) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const plotRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(1040);
  const clipId = useId().replace(/:/g, "");
  const symbols = useMemo(() => [...new Set(points.flatMap((point) => Object.keys(point.bySymbol)))].sort(), [points]);
  const chartPoints = useMemo(() => rebaseChartPoints(points, symbols), [points, symbols]);
  const visible = chartPoints;
  const series = useMemo<ChartSeries[]>(() => mode === "daily" ? [] : [
    { key: "combined", label: "Combined book", color: COMBINED_COLOR },
    ...symbols.map((symbol, index) => ({ key: `market:${symbol}`, label: symbol, color: CHART_COLORS[index % CHART_COLORS.length] })),
    ...(comparison ? [{ key: "baseline", label: "Always on", color: BASELINE_COLOR }] : []),
  ], [mode, symbols, comparison]);
  const active = useMemo(() => {
    const shown = series.filter((item) => !hidden.has(item.key));
    return shown.length ? shown : series.filter((item) => item.key === "combined");
  }, [series, hidden]);
  const scale = useMemo(() => niceChartScale(
    mode === "daily" ? visible.map((point) => point.pnl) : visible.flatMap((point) => active.map((item) => seriesValue(point, item.key))),
    mode === "daily",
  ), [visible, active, mode]);

  useEffect(() => {
    const element = plotRef.current;
    if (!element) return;
    const update = () => setChartWidth(Math.max(280, Math.round(element.getBoundingClientRect().width)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const height = chartWidth < 500 ? 300 : 348;
  const tickStep = Math.abs(scale.ticks[1] - scale.ticks[0]) || 1;
  const maxAbs = Math.max(Math.abs(scale.min), Math.abs(scale.max));
  const axisLabels = scale.ticks.map((value) => formatChartAxisMoney(value, tickStep, maxAbs));
  const left = Math.max(76, Math.max(...axisLabels.map((label) => label.length)) * 7 + 14);
  const right = 20;
  const top = 34;
  const bottom = height - 56;
  const plotWidth = Math.max(1, chartWidth - left - right);
  const firstTime = visible[0]?.time ?? 0;
  const lastTime = visible.at(-1)?.time ?? firstTime;
  const xTime = (time: number) => lastTime === firstTime
    ? left + plotWidth / 2
    : left + ((time - firstTime) / (lastTime - firstTime)) * plotWidth;
  const y = (value: number) => bottom - ((value - scale.min) / (scale.max - scale.min)) * (bottom - top);
  const line = (key: string) => visible.map((point) => `${xTime(point.time)},${y(seriesValue(point, key))}`).join(" ");
  const hovered = hover == null ? null : visible[Math.max(0, Math.min(visible.length - 1, hover))];
  const dateTicks = visible.length ? chartDateTicks(visible[0].date, visible.at(-1)!.date, plotWidth) : [];
  const spanDays = (lastTime - firstTime) / (24 * 60 * 60 * 1000);
  const tickGapDays = dateTicks.length > 1
    ? (Date.parse(`${dateTicks[1]}T00:00:00Z`) - Date.parse(`${dateTicks[0]}T00:00:00Z`)) / (24 * 60 * 60 * 1000)
    : spanDays;

  const inspectPointer = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!visible.length) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const pointerX = ((event.clientX - rect.left) / rect.width) * chartWidth;
    const fraction = Math.max(0, Math.min(1, (pointerX - left) / plotWidth));
    setHover(closestPoint(visible, firstTime + fraction * (lastTime - firstTime)));
  };
  const toggleSeries = (key: string) => {
    if (!hidden.has(key) && active.length <= 1) return;
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className="collective-chart">
      <div className="collective-chart-toolbar">
        <span className="collective-chart-axis-title">{mode === "daily" ? "Daily P&L (USD)" : "Cumulative P&L (USD)"}</span>
        <PortfolioPeriodSelector value={period} onChange={(value) => { onPeriodChange(value); setHover(null); }} />
      </div>
      <div className="collective-chart-plot" ref={plotRef}>
        <svg
          viewBox={`0 0 ${chartWidth} ${height}`}
          width={chartWidth}
          height={height}
          style={{ height }}
          role="img"
          tabIndex={0}
          aria-label={mode === "daily" ? "Daily P&L chart. Use left and right arrow keys to inspect days." : "Cumulative portfolio and market P&L chart. Use left and right arrow keys to inspect days."}
          onPointerMove={inspectPointer}
          onPointerDown={inspectPointer}
          onClick={inspectPointer}
          onPointerLeave={(event) => { if (event.pointerType === "mouse") setHover(null); }}
          onFocus={() => setHover((current) => current ?? (visible.length ? visible.length - 1 : null))}
          onBlur={() => setHover(null)}
          onKeyDown={(event) => {
            if (!visible.length) return;
            let next: number;
            if (event.key === "ArrowLeft") next = Math.max(0, (hover ?? visible.length - 1) - 1);
            else if (event.key === "ArrowRight") next = Math.min(visible.length - 1, (hover ?? 0) + 1);
            else if (event.key === "Home") next = 0;
            else if (event.key === "End") next = visible.length - 1;
            else return;
            event.preventDefault();
            setHover(next);
          }}
        >
          <defs><clipPath id={clipId}><rect x={left} y={top} width={plotWidth} height={bottom - top} /></clipPath></defs>
          {scale.ticks.map((value, index) => (
            <g key={value}>
              <line x1={left} x2={chartWidth - right} y1={y(value)} y2={y(value)} className={value === 0 ? "collective-zero-grid" : "collective-grid"} />
              <text x={left - 10} y={y(value) + 4} textAnchor="end" className="collective-axis-text">{axisLabels[index]}</text>
            </g>
          ))}
          {dateTicks.map((date) => (
            <g key={date}>
              <line x1={xTime(Date.parse(`${date}T00:00:00Z`))} x2={xTime(Date.parse(`${date}T00:00:00Z`))} y1={top} y2={bottom} className="collective-date-grid" />
              <text x={xTime(Date.parse(`${date}T00:00:00Z`))} y={bottom + 24} textAnchor="middle" className="collective-axis-text">{formatChartAxisDate(date, tickGapDays, spanDays)}</text>
            </g>
          ))}
          <line x1={left} x2={left} y1={top} y2={bottom} className="collective-axis-line" />
          <line x1={left} x2={chartWidth - right} y1={bottom} y2={bottom} className="collective-axis-line" />
          <g clipPath={`url(#${clipId})`}>
            {mode === "daily" ? visible.map((point) => (
              <line key={point.date} x1={xTime(point.time)} x2={xTime(point.time)} y1={y(0)} y2={y(point.pnl)} stroke={tone(point.pnl)} strokeWidth={Math.max(1, Math.min(8, plotWidth / Math.max(1, visible.length) * 0.7))} />
            )) : (
              <>
                {active.some((item) => item.key === "combined") && scale.min <= 0 && scale.max >= 0 && visible.length > 1 && (
                  <polygon points={`${xTime(firstTime)},${y(0)} ${line("combined")} ${xTime(lastTime)},${y(0)}`} fill={COMBINED_COLOR} fillOpacity="0.06" />
                )}
                {active.map((item) => (
                  <polyline key={item.key} points={line(item.key)} fill="none" stroke={item.color} strokeWidth={item.key === "combined" ? 3 : 2} strokeDasharray={item.key === "baseline" ? "7 5" : undefined} strokeLinejoin="round" strokeLinecap="round" />
                ))}
              </>
            )}
            {hovered && (
              <>
                <line x1={xTime(hovered.time)} x2={xTime(hovered.time)} y1={top} y2={bottom} stroke="#6b7b73" strokeDasharray="4 4" />
                {mode === "daily" ? (
                  <circle cx={xTime(hovered.time)} cy={y(hovered.pnl)} r="4" fill={tone(hovered.pnl)} stroke="#fff" strokeWidth="2" />
                ) : active.map((item) => (
                  <circle key={item.key} cx={xTime(hovered.time)} cy={y(seriesValue(hovered, item.key))} r="4" fill={item.color} stroke="#fff" strokeWidth="2" />
                ))}
              </>
            )}
          </g>
        </svg>
        {hovered && (
          <div className="collective-chart-tooltip" style={{ left: Math.max(4, Math.min(chartWidth - (chartWidth < 500 ? 208 : 220), xTime(hovered.time) + 12)) }}>
            <strong>{hovered.date}</strong>
            {mode === "daily" ? <span><i style={{ background: tone(hovered.pnl) }} />Daily <b>{money(hovered.pnl)}</b></span> : active.map((item) => (
              <span key={item.key}><i style={{ background: item.color }} />{item.label} <b>{money(seriesValue(hovered, item.key))}</b></span>
            ))}
            {mode !== "daily" && <small>Daily change {money(hovered.pnl)}</small>}
          </div>
        )}
      </div>
      <div className="collective-chart-footer">
        {mode === "daily" ? (
          <div className="collective-chart-legend"><span><i style={{ background: "#16634f" }} />Gain</span><span><i style={{ background: "#b3412e" }} />Loss</span></div>
        ) : (
          <div className="collective-chart-legend" aria-label="Chart series">
            {series.map((item) => (
              <button type="button" key={item.key} aria-pressed={active.some((shown) => shown.key === item.key)} onClick={() => toggleSeries(item.key)} title={`Show or hide ${item.label}`}>
                <i style={{ background: item.color }} />{item.label}
              </button>
            ))}
          </div>
        )}
        <Text size="xs" c="dimmed">Hover, tap, or use arrow keys to inspect a day</Text>
      </div>
      <span className="visually-hidden" aria-live="polite">{hovered ? mode === "daily"
        ? `${hovered.date}, daily ${money(hovered.pnl)}`
        : `${hovered.date}, ${active.map((item) => `${item.label} ${money(seriesValue(hovered, item.key))}`).join(", ")}, daily change ${money(hovered.pnl)}`
        : ""}</span>
    </div>
  );
}
