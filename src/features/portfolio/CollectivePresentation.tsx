import { useState } from "react";
import { ActionIcon, Group, Text, TextInput } from "@mantine/core";
import { IconChevronLeft, IconChevronRight } from "@tabler/icons-react";
import type { DailyPoint } from "../../../shared/ts/portfolio.ts";
import {
  formatCompactMoney as compact,
  formatMoney as money,
  valueTone as tone,
} from "./collectiveViewModel";

export function CollectivePnlChart({
  points,
  mode,
  comparison,
}: {
  points: DailyPoint[];
  mode: string;
  comparison: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const symbols = [...new Set(points.flatMap((point) => Object.keys(point.bySymbol)))].sort();
  const colors = ["#3f7fa3", "#97638a", "#a8741f", "#4f7f3f", "#587382"];
  const totals: Record<string, number> = {};
  const marketCurves = points.map((point) =>
    Object.fromEntries(
      symbols.map((symbol) => {
        totals[symbol] = (totals[symbol] || 0) + (point.bySymbol[symbol] || 0);
        return [symbol, totals[symbol]];
      }),
    ),
  );
  const values = points.flatMap((point, index) =>
    mode === "daily"
      ? [point.pnl]
      : [
          point.cumulative,
          ...(comparison ? [point.baselineCumulative] : []),
          ...symbols.map((symbol) => marketCurves[index][symbol]),
        ],
  );
  const low = Math.min(0, ...values);
  const high = Math.max(0, ...values);
  const span = high - low || 1;
  const x = (index: number) => 72 + (index / Math.max(1, points.length - 1)) * 940;
  const y = (value: number) => 285 - ((value - low) / span) * 255;
  const polyline = (get: (point: DailyPoint, index: number) => number) =>
    points.map((point, index) => `${x(index)},${y(get(point, index))}`).join(" ");
  const hovered = hover == null ? null : points[Math.max(0, Math.min(points.length - 1, hover))];
  const ticks = [low, (low + high) / 2, high];
  return (
    <div className="collective-chart">
      <svg
        viewBox="0 0 1040 330"
        role="img"
        aria-label={mode === "daily" ? "Combined daily P&L chart" : "Combined cumulative P&L and market curves"}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setHover(
            Math.round(
              ((((event.clientX - rect.left) / rect.width) * 1040 - 72) / 940) *
                (points.length - 1),
            ),
          );
        }}
      >
        {ticks.map((value, index) => (
          <g key={index}>
            <line x1="72" x2="1012" y1={y(value)} y2={y(value)} stroke="#e7ece8" />
            <text x="64" y={y(value) + 4} textAnchor="end" fontSize="12" fill="#66756c">{compact(value)}</text>
          </g>
        ))}
        <line x1="72" x2="1012" y1={y(0)} y2={y(0)} stroke="#aebbb2" strokeDasharray="4 4" />
        {mode === "daily" ? (
          points.map((point, index) => (
            <line
              key={point.date}
              x1={x(index)}
              x2={x(index)}
              y1={y(0)}
              y2={y(point.pnl)}
              stroke={tone(point.pnl)}
              strokeWidth={Math.max(0.6, 800 / points.length)}
            />
          ))
        ) : (
          <>
            <polygon
              points={`${x(0)},${y(0)} ${polyline((point) => point.cumulative)} ${x(points.length - 1)},${y(0)}`}
              fill="#1e7a62"
              fillOpacity="0.08"
            />
            {symbols.map((symbol, index) => (
              <polyline
                key={symbol}
                points={polyline((_, pointIndex) => marketCurves[pointIndex][symbol])}
                fill="none"
                stroke={colors[index % colors.length]}
                strokeWidth="1.5"
                opacity=".85"
              />
            ))}
            {comparison && (
              <polyline points={polyline((point) => point.baselineCumulative)} fill="none" stroke="#7c8393" strokeWidth="2" strokeDasharray="6 5" />
            )}
            <polyline points={polyline((point) => point.cumulative)} fill="none" stroke="#1e7a62" strokeWidth="3" strokeLinejoin="round" />
            {points.length > 0 && (
              <circle cx={x(points.length - 1)} cy={y(points[points.length - 1].cumulative)} r="4.5" fill="#1e7a62" stroke="#fff" strokeWidth="1.5" />
            )}
          </>
        )}
        {hovered && (
          <line x1={x(points.indexOf(hovered))} x2={x(points.indexOf(hovered))} y1="30" y2="290" stroke="#64766b" strokeDasharray="3 3" />
        )}
        <text x="72" y="316" fontSize="12" fill="#66756c">{points[0]?.date}</text>
        <text x="1012" y="316" textAnchor="end" fontSize="12" fill="#66756c">{points.at(-1)?.date}</text>
      </svg>
      <Group gap="md" justify="space-between">
        <Group gap="md">
          <Text size="xs" fw={700} c="#16634f">Combined book</Text>
          {mode !== "daily" && symbols.map((symbol, index) => (
            <Text key={symbol} size="xs" fw={600} c={colors[index % colors.length]}>{symbol}</Text>
          ))}
          {comparison && <Text size="xs" c="dimmed">Dashed: always on</Text>}
        </Group>
        <Text size="xs" className="collective-hover">
          {hovered
            ? `${hovered.date} · daily ${money(hovered.pnl)} · cumulative ${money(hovered.cumulative)}`
            : "Move over the chart to inspect a day"}
        </Text>
      </Group>
    </div>
  );
}

export function CollectiveCalendar({
  points,
  month,
  onMonth,
  onDay,
  selected,
}: {
  points: DailyPoint[];
  month: string;
  onMonth: (month: string) => void;
  onDay: (day: string) => void;
  selected: string;
}) {
  const [year, monthNumber] = month.split("-").map(Number);
  const offset = new Date(Date.UTC(year, monthNumber - 1, 1)).getUTCDay();
  const days = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  const lookup = new Map(points.map((point) => [point.date, point]));
  const inMonth = points.filter((point) => point.date.startsWith(month));
  const sum = inMonth.reduce((value, point) => value + point.pnl, 0);
  const scale = Math.max(1, ...inMonth.map((point) => Math.abs(point.pnl)));
  const title = new Date(Date.UTC(year, monthNumber - 1, 1)).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  const move = (offsetMonths: number) =>
    onMonth(new Date(Date.UTC(year, monthNumber - 1 + offsetMonths, 1)).toISOString().slice(0, 7));
  return (
    <section className="wb-card" aria-label="Daily P&L calendar">
      <div className="wb-card-head">
        <Group gap="xs" wrap="nowrap" className="collective-month-nav">
          <ActionIcon variant="default" size="lg" aria-label="Previous month" onClick={() => move(-1)}><IconChevronLeft size={16} /></ActionIcon>
          <h2 className="collective-month" id="collective-calendar">{title}</h2>
          <ActionIcon variant="default" size="lg" aria-label="Next month" onClick={() => move(1)}><IconChevronRight size={16} /></ActionIcon>
          <TextInput
            aria-label="Calendar month"
            type="month"
            size="xs"
            value={month}
            onChange={(event) => event.currentTarget.value && onMonth(event.currentTarget.value)}
            w={140}
            className="collective-month-input"
          />
        </Group>
        <div className="wb-month-sum">
          <span>Net <b style={{ color: tone(sum) }}>{money(sum)}</b></span>
          <span><b>{inMonth.filter((point) => point.pnl > 0).length}</b> up days</span>
          <span><b>{inMonth.filter((point) => point.pnl < 0).length}</b> down days</span>
        </div>
      </div>
      <div className="collective-calendar">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => <div className="calendar-heading" key={day}>{day}</div>)}
        {Array.from({ length: offset }, (_, index) => <div key={`blank${index}`} />)}
        {Array.from({ length: days }, (_, index) => {
          const day = `${month}-${String(index + 1).padStart(2, "0")}`;
          const point = lookup.get(day);
          const strength = point ? 0.07 + 0.5 * Math.min(1, Math.abs(point.pnl) / scale) : 0;
          return (
            <button
              key={day}
              aria-label={`${day}: ${point ? money(point.pnl) : "Outside test window"}`}
              aria-pressed={selected === day}
              disabled={!point}
              className={`calendar-day ${point ? point.pnl > 0 ? "gain" : point.pnl < 0 ? "loss" : "flat" : "uncovered"} ${selected === day ? "selected" : ""}`}
              style={
                point && point.pnl !== 0
                  ? { background: point.pnl > 0 ? `rgba(30,122,98,${strength.toFixed(2)})` : `rgba(179,65,46,${strength.toFixed(2)})` }
                  : undefined
              }
              onClick={() => onDay(day)}
            >
              <span className="calendar-date">{index + 1}</span>
              <strong>{point ? point.pnl === 0 ? "—" : (point.pnl > 0 ? "+" : "") + compact(point.pnl) : ""}</strong>
              <small>{point ? point.trades ? `${point.trades} closed` : "" : "Outside"}</small>
            </button>
          );
        })}
      </div>
      <div className="wb-legend">
        <span><i style={{ background: "rgba(30,122,98,.35)" }} />Gain</span>
        <span><i style={{ background: "rgba(179,65,46,.35)" }} />Loss</span>
        <span><i style={{ background: "#fff" }} />No recorded change</span>
        <span><i className="hatch" />Outside test window</span>
        <span style={{ marginLeft: "auto" }}>UTC days</span>
      </div>
    </section>
  );
}
