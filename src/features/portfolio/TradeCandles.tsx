import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Button, Group, SegmentedControl } from "@mantine/core";
import type { Candle, ChartTrade } from "../../../shared/ts/tradeChart";
import { niceChartScale } from "./collectiveChartScale";

const MINUTE = 60000;
const DAY = 1440 * MINUTE;
const H = 340,
  TOP = 20,
  BOTTOM = 304,
  LEFT = 8;
const entryColor = "#225995",
  exitColor = "#7357a3",
  stopColor = "#ac4537",
  targetColor = "#14765d";
const price = (n: number) =>
  n.toLocaleString("en-US", { maximumFractionDigits: 4 });
const clock = (n: number) => new Date(n).toISOString().slice(11, 16);
type Window = { start: number; span: number };
type Gesture = {
  points: Map<number, number>;
  initial: Window;
  center: number;
  distance: number;
};

function aggregate(candles: Candle[], minutes: number) {
  const rows: Candle[] = [];
  for (const candle of candles) {
    const time =
      Math.floor(candle.time / (minutes * MINUTE)) * minutes * MINUTE;
    const last = rows.at(-1);
    if (last?.time === time) {
      last.high = Math.max(last.high, candle.high);
      last.low = Math.min(last.low, candle.low);
      last.close = candle.close;
    } else rows.push({ ...candle, time });
  }
  return rows;
}

function bounded(
  start: number,
  span: number,
  lower: number,
  upper: number,
): Window {
  span = Math.min(DAY, Math.max(10 * MINUTE, span));
  return { start: Math.max(lower, Math.min(upper - span, start)), span };
}

export function TradeCandles({
  day,
  candles,
  trades,
  focused,
  focusRevision,
  onFocus,
  limits,
  onDates,
}: {
  day: string;
  candles: Candle[];
  trades: ChartTrade[];
  focused: ChartTrade | undefined;
  focusRevision: number;
  onFocus: (index: number, timestamp: string) => void;
  limits: { start: string; end: string };
  onDates: (dates: string) => void;
}) {
  const midnight = Date.parse(day);
  const lower = Date.parse(limits.start),
    upper = Date.parse(limits.end) + DAY;
  const [minutes, setMinutes] = useState(1);
  const [range, setRange] = useState<Window>({ start: midnight, span: DAY });
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null);
  const [width, setWidth] = useState(1000);
  const area = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture>({
    points: new Map(),
    initial: range,
    center: 0,
    distance: 0,
  });
  const clip = useId();
  const right = width - 78;
  const plot = right - LEFT;
  useEffect(() => {
    const node = area.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(200, entry.contentRect.width)),
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!focused) return;
    const entry = Date.parse(focused.entry),
      exit = Date.parse(focused.exit);
    const from = Math.max(entry, midnight),
      to = Math.min(exit, midnight + DAY);
    const span = Math.max(90 * MINUTE, (to - from) * 1.4);
    setRange(bounded((from + to - span) / 2, span, midnight, midnight + DAY));
    setHover(null);
  }, [focused, focusRevision, midnight]);
  const firstDate = new Date(range.start).toISOString().slice(0, 10);
  const lastDate = new Date(range.start + range.span - 1)
    .toISOString()
    .slice(0, 10);
  useEffect(() => {
    onDates(firstDate === lastDate ? firstDate : firstDate + "," + lastDate);
  }, [firstDate, lastDate, onDates]);
  useEffect(() => {
    const node = area.current;
    if (!node) return;
    function wheel(e: WheelEvent) {
      e.preventDefault();
      const fraction = Math.max(
        0,
        Math.min(
          1,
          (e.clientX - node!.getBoundingClientRect().left - LEFT) / plot,
        ),
      );
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? plot : 1;
      setRange((old) => {
        if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY))
          return bounded(
            old.start + (((e.deltaX || e.deltaY) * unit) / plot) * old.span,
            old.span,
            lower,
            upper,
          );
        const span = bounded(
          old.start,
          old.span *
            Math.exp(Math.max(-1, Math.min(1, e.deltaY * unit * 0.003))),
          lower,
          upper,
        ).span;
        return bounded(
          old.start + (old.span - span) * fraction,
          span,
          lower,
          upper,
        );
      });
    }
    node.addEventListener("wheel", wheel, { passive: false });
    return () => node.removeEventListener("wheel", wheel);
  }, [lower, upper, plot]);
  const rows = useMemo(() => aggregate(candles, minutes), [candles, minutes]);
  const step = minutes * MINUTE;
  const end = range.start + range.span;
  const visible = rows.filter(
    (b) => b.time + step > range.start && b.time < end,
  );
  const active = trades.filter(
    (t) => Date.parse(t.entry) < end && Date.parse(t.exit) >= range.start,
  );
  const segments = active.flatMap((t) => {
    const start = Date.parse(t.entry),
      exit = Date.parse(t.exit);
    const levels = [
      { time: start, stop: t.stop, target: t.target },
      ...(t.changes || []),
    ];
    return levels.flatMap((level, i) => {
      const until = levels[i + 1]?.time ?? exit;
      if (level.time >= end || until < range.start) return [];
      return (
        [
          ["Stop", level.stop, stopColor],
          ["Target", level.target, targetColor],
        ] as const
      ).flatMap(([label, value, color]) =>
        value === undefined
          ? []
          : [{ id: t.index, label, color, value, from: level.time, to: until }],
      );
    });
  });
  const entryLines = active.flatMap((t) =>
    t.entryPrice === undefined
      ? []
      : [
          {
            id: t.index,
            value: t.entryPrice,
            from: Date.parse(t.entry),
            to: Date.parse(t.exit),
          },
        ],
  );
  const marks = active
    .flatMap((t) => [
      {
        trade: t,
        label: "Entry",
        time: Date.parse(t.entry),
        value: t.entryPrice,
        color: entryColor,
      },
      {
        trade: t,
        label: "Exit",
        time: Date.parse(t.exit),
        value: t.exitPrice,
        color: exitColor,
      },
    ])
    .filter((m) => m.time >= range.start && m.time < end);
  const scale = niceChartScale([
    ...visible.flatMap((b) => [b.low, b.high]),
    ...segments.map((s) => s.value),
    ...entryLines.map((s) => s.value),
    ...marks.flatMap((m) => (m.value === undefined ? [] : [m.value])),
  ]);
  const x = (time: number) => LEFT + ((time - range.start) / range.span) * plot;
  const y = (value: number) =>
    TOP + ((scale.max - value) / (scale.max - scale.min)) * (BOTTOM - TOP);
  const hoverTime = hover
    ? range.start + ((hover.x - LEFT) / plot) * range.span
    : 0;
  const hovered = hover
    ? visible.find((b) => hoverTime >= b.time && hoverTime < b.time + step)
    : null;
  const tickStep =
    ([1, 2, 5, 10, 15, 30, 60, 120, 240, 360, 720].find(
      (n) => ((n * MINUTE) / range.span) * plot >= 64,
    ) ?? 720) * MINUTE;
  const timeTicks = [];
  for (
    let t = Math.ceil(range.start / tickStep) * tickStep;
    t < end;
    t += tickStep
  )
    timeTicks.push(t);
  function zoom(factor: number) {
    setRange((old) => {
      const span = bounded(old.start, old.span * factor, lower, upper).span;
      return bounded(old.start + (old.span - span) / 2, span, lower, upper);
    });
  }
  function anchor(initial: Window) {
    const g = gesture.current,
      [a = 0, b = a] = g.points.values();
    g.initial = initial;
    g.center = (a + b) / 2;
    g.distance = Math.abs(a - b);
  }
  function pointer(e: ReactPointerEvent<SVGSVGElement>) {
    const bounds = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - bounds.left) / bounds.width) * width;
    const py = ((e.clientY - bounds.top) / bounds.height) * H;
    const g = gesture.current;
    if (e.type === "pointerdown") {
      if (e.button !== 0) return;
      e.currentTarget.focus();
      e.currentTarget.setPointerCapture(e.pointerId);
      g.points.set(e.pointerId, px);
      anchor(range);
    } else if (e.type === "pointermove" && g.points.has(e.pointerId)) {
      g.points.set(e.pointerId, px);
      const [a, b = a] = g.points.values();
      const span =
        g.distance && a !== b
          ? bounded(
              0,
              (g.initial.span * g.distance) / Math.abs(a - b),
              lower,
              upper,
            ).span
          : g.initial.span;
      const fixed =
        g.initial.start + ((g.center - LEFT) / plot) * g.initial.span;
      setRange(
        bounded(
          fixed - (((a + b) / 2 - LEFT) / plot) * span,
          span,
          lower,
          upper,
        ),
      );
      setHover(null);
    } else if (e.type === "pointermove") {
      setHover(
        px >= LEFT && px <= right && py >= TOP && py <= BOTTOM
          ? { x: px, y: py }
          : null,
      );
    } else {
      g.points.delete(e.pointerId);
      anchor(range);
    }
  }
  return (
    <div className="trade-candles">
      <Group justify="space-between" gap="xs">
        <SegmentedControl
          aria-label="Candle interval"
          size="xs"
          value={String(minutes)}
          data={[1, 5, 15, 60].map((n) => ({
            value: String(n),
            label: n === 60 ? "1h" : n + "m",
          }))}
          onChange={(v) => {
            const interval = Number(v);
            setMinutes(interval);
            setRange((old) => {
              const span = Math.min(
                DAY,
                Math.max(old.span, interval * MINUTE * 12),
              );
              return bounded(
                old.start + (old.span - span) / 2,
                span,
                lower,
                upper,
              );
            });
          }}
        />
        <Group gap={4}>
          <Button
            size="compact-sm"
            variant="default"
            aria-label="Zoom out"
            onClick={() => zoom(1.5)}
          >
            −
          </Button>
          <Button
            size="compact-sm"
            variant="default"
            aria-label="Zoom in"
            onClick={() => zoom(1 / 1.5)}
          >
            +
          </Button>
          <Button
            size="compact-sm"
            variant="default"
            onClick={() => setRange({ start: midnight, span: DAY })}
          >
            Fit day
          </Button>
        </Group>
      </Group>
      <div className="trade-ohlc">
        {hovered ? (
          <>
            {new Date(hovered.time).toISOString().slice(0, 10)} ·{" "}
            {clock(hovered.time)} UTC
            {(["open", "high", "low", "close"] as const).map((k) => (
              <span key={k}>
                {k[0].toUpperCase()} <b>{price(hovered[k])}</b>
              </span>
            ))}
          </>
        ) : (
          <>
            {firstDate} · {clock(range.start)} –{" "}
            {lastDate !== firstDate && lastDate + " "}
            {end % DAY === 0 ? "24:00" : clock(end)} UTC
          </>
        )}
      </div>
      <div ref={area} className="trade-canvas">
        <svg
          width="100%"
          height={H}
          viewBox={`0 0 ${width} ${H}`}
          tabIndex={0}
          role="group"
          aria-label="Intraday candlestick chart. Arrow keys pan, plus and minus zoom, Home fits the day."
          onPointerDown={pointer}
          onPointerMove={pointer}
          onPointerUp={pointer}
          onPointerCancel={pointer}
          onPointerLeave={() => setHover(null)}
          onDoubleClick={() => setRange({ start: midnight, span: DAY })}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft" || e.key === "ArrowRight")
              setRange((old) =>
                bounded(
                  old.start + old.span * (e.key === "ArrowLeft" ? -0.2 : 0.2),
                  old.span,
                  lower,
                  upper,
                ),
              );
            else if (e.key === "+" || e.key === "=") zoom(1 / 1.5);
            else if (e.key === "-") zoom(1.5);
            else if (e.key === "Home") setRange({ start: midnight, span: DAY });
            else return;
            e.preventDefault();
          }}
        >
          <defs>
            <clipPath id={clip}>
              <rect
                x={LEFT}
                y={TOP - 10}
                width={plot}
                height={BOTTOM - TOP + 20}
              />
            </clipPath>
          </defs>
          {scale.ticks.map((t) => (
            <g key={t}>
              <line x1={LEFT} x2={right} y1={y(t)} y2={y(t)} stroke="#e1e7e3" />
              <text x={right + 6} y={y(t) + 4}>
                {price(t)}
              </text>
            </g>
          ))}
          {timeTicks.map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={TOP} y2={BOTTOM} stroke="#eff2f0" />
              <text x={Math.max(20, x(t))} y={BOTTOM + 22} textAnchor="middle">
                {clock(t)}
              </text>
            </g>
          ))}
          <g clipPath={`url(#${clip})`}>
            {visible.length === 0 && (
              <text
                x={(LEFT + right) / 2}
                y={(TOP + BOTTOM) / 2}
                textAnchor="middle"
              >
                No candles in this time window
              </text>
            )}
            {visible.map((b) => {
              const mid = x(b.time + step / 2),
                w = Math.max(0.8, ((plot * step) / range.span) * 0.72);
              const color = b.close >= b.open ? "#168669" : "#bc544c";
              return (
                <g key={b.time} fill={color}>
                  <line
                    x1={mid}
                    x2={mid}
                    y1={y(b.high)}
                    y2={y(b.low)}
                    stroke={color}
                  />
                  <rect
                    x={mid - w / 2}
                    width={w}
                    y={y(Math.max(b.open, b.close))}
                    height={Math.max(1.2, Math.abs(y(b.open) - y(b.close)))}
                  />
                </g>
              );
            })}
            {entryLines.map((s) => (
              <line
                key={s.id}
                x1={Math.max(LEFT, x(s.from))}
                x2={Math.min(right, x(s.to))}
                y1={y(s.value)}
                y2={y(s.value)}
                stroke={entryColor}
                strokeDasharray="2 3"
              >
                <title>Entry {price(s.value)}</title>
              </line>
            ))}
            {segments.map((s, i) => (
              <line
                key={i}
                x1={Math.max(LEFT, x(s.from))}
                x2={Math.max(x(s.from) + 3, x(s.to))}
                y1={y(s.value)}
                y2={y(s.value)}
                stroke={s.color}
                strokeDasharray="5 3"
                strokeWidth={2}
              >
                <title>
                  {s.label} {price(s.value)}
                </title>
              </line>
            ))}
            {marks.map((m) => {
              const px = x(m.time),
                py =
                  m.value === undefined
                    ? TOP + (m.label === "Exit" ? 13 : 0)
                    : y(m.value);
              const d = m.label === "Entry" ? 1 : -1;
              const selected = focused?.index === m.trade.index;
              const labelOnLeft = px > right - 125;
              return (
                <g
                  key={m.trade.index + m.label}
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() =>
                    onFocus(m.trade.index, new Date(m.time).toISOString())
                  }
                  className="trade-marker"
                  fill={m.color}
                >
                  <title>
                    {m.label} · {clock(m.time)} UTC ·{" "}
                    {m.value === undefined
                      ? "Price unavailable"
                      : price(m.value)}
                  </title>
                  <path
                    d={`M ${px} ${py} l -5 ${8 * d} h 10 z`}
                    stroke="white"
                    strokeWidth={1}
                  />
                  {selected && (
                    <text
                      className="trade-marker-label"
                      x={px + (labelOnLeft ? -6 : 6)}
                      y={Math.max(TOP + 10, Math.min(BOTTOM - 2, py + d * 13))}
                      textAnchor={labelOnLeft ? "end" : "start"}
                      style={{ fill: m.color }}
                    >
                      {m.label}
                      {m.value !== undefined && " " + price(m.value)}
                    </text>
                  )}
                </g>
              );
            })}
            {hover && (
              <path
                d={`M ${hover.x} ${TOP} V ${BOTTOM} M ${LEFT} ${hover.y} H ${right}`}
                fill="none"
                stroke="#687b75"
                strokeDasharray="3 3"
              />
            )}
          </g>
          {hover && (
            <g className="trade-axis-tag">
              <rect x={right} y={hover.y - 9} width={76} height={18} />
              <text x={right + 4} y={hover.y + 4}>
                {price(
                  scale.max -
                    ((hover.y - TOP) / (BOTTOM - TOP)) *
                      (scale.max - scale.min),
                )}
              </text>
              <rect
                x={Math.max(1, hover.x - 22)}
                y={BOTTOM + 7}
                width={46}
                height={20}
              />
              <text
                x={Math.max(24, hover.x + 1)}
                y={BOTTOM + 21}
                textAnchor="middle"
              >
                {clock(hoverTime)}
              </text>
            </g>
          )}
        </svg>
      </div>
      <div className="trade-chart-key">
        <span style={{ color: entryColor }}>▲ Entry</span>
        <span style={{ color: exitColor }}>▼ Exit</span>
        <span style={{ color: stopColor }}>┄ Stop</span>
        <span style={{ color: targetColor }}>┄ Target</span>
        <small>Drag or Shift-scroll to pan · Scroll or pinch to zoom</small>
      </div>
    </div>
  );
}
