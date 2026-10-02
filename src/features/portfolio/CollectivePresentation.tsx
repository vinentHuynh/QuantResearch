import { ActionIcon, Group, TextInput } from "@mantine/core";
import { IconChevronLeft, IconChevronRight } from "@tabler/icons-react";
import type { DailyPoint } from "../../../shared/ts/portfolio.ts";
import {
  formatCompactMoney as compact,
  formatMoney as money,
  valueTone as tone,
} from "./collectiveViewModel";

export { CollectivePnlChart } from "./CollectivePnlChart";

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
