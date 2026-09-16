import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Chip,
  Drawer,
  Group,
  Loader,
  NumberInput,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Switch,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import {
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconDownload,
  IconPlus,
  IconRefresh,
  IconX,
} from "@tabler/icons-react";
import {
  calculatePortfolio,
  commonWindow,
  defaultPolicy,
  type CollectiveCatalog,
  type CollectiveSeries,
  type DailyPoint,
  type Dependence,
  type GatePolicy,
  type GateState,
} from "./collectiveModel";
import { PageHeader } from "./Shell";
import { href } from "./navigation";
import "./collective.css";

const money = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
const compact = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  });
const pct = (n: number) => `${(n * 100).toFixed(2)}%`;
const tone = (n: number) => (n < 0 ? "#b3412e" : "#16634f");
const signed = (n: number) => (n < 0 ? "wb-loss" : "wb-gain");
const stateColor: Record<GateState, string> = {
  Paused: "orange",
  Active: "teal",
  Reduced: "yellow",
  Raised: "blue",
};
const verdicts: Record<Dependence["verdict"], [string, string]> = {
  cluster: ["Losses cluster — a pause can help", "teal"],
  alternate: ["Outcomes alternate — a pause skips recoveries", "red"],
  none: ["No dependence — a pause costs expected return", "gray"],
  insufficient: ["Under 30 trades", "gray"],
};
const verdictCopy: Record<Dependence["verdict"], [string, string]> = {
  cluster: [
    "Losses cluster in this book",
    "Outcomes persist, so a loss-triggered pause has a statistical basis here. Check the comparison below before reading it as evidence.",
  ],
  alternate: [
    "Losses don’t cluster in this book",
    "Outcomes alternate, so a loss-triggered pause mostly skips recoveries. A worse result below is the expected outcome, not bad luck.",
  ],
  none: [
    "No loss dependence in this book",
    "Without persistence, a loss-triggered pause is expected to give up return.",
  ],
  insufficient: [
    "Too few trades to judge this book",
    "Fewer than 30 trades are available, so the runs test is not informative.",
  ],
};
const VIEWS = ["overview", "calendar", "contributions", "pause"] as const;
type ViewName = (typeof VIEWS)[number];
type Settings = {
  copies: Record<string, number>;
  start: string;
  end: string;
  basis: "marked" | "closed";
  policy: GatePolicy;
};
function saved(): Settings | null {
  try {
    const value = JSON.parse(
      localStorage.getItem("quant-collective-v1") || "null",
    );
    if (
      !value ||
      typeof value.copies !== "object" ||
      !value.start ||
      !value.end
    )
      return null;
    return {
      ...value,
      basis: value.basis === "closed" ? "closed" : "marked",
      policy: { ...defaultPolicy, ...value.policy },
    };
  } catch {
    return null;
  }
}
function download(filename: string, content: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
const csvCell = (value: unknown) => `"${String(value).replaceAll('"', '""')}"`;
const weekday = (date: string) =>
  new Date(date + "T00:00:00Z").toLocaleDateString("en-US", {
    weekday: "long",
    timeZone: "UTC",
  });

function PnlChart({
  points,
  mode,
  comparison,
}: {
  points: DailyPoint[];
  mode: string;
  comparison: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const symbols = [
    ...new Set(points.flatMap((p) => Object.keys(p.bySymbol))),
  ].sort();
  const colors = ["#3f7fa3", "#97638a", "#a8741f", "#4f7f3f", "#587382"];
  const totals: Record<string, number> = {};
  const marketCurves = points.map((p) =>
    Object.fromEntries(
      symbols.map((s) => {
        totals[s] = (totals[s] || 0) + (p.bySymbol[s] || 0);
        return [s, totals[s]];
      }),
    ),
  );
  const values = points.flatMap((p, i) =>
    mode === "daily"
      ? [p.pnl]
      : [
          p.cumulative,
          ...(comparison ? [p.baselineCumulative] : []),
          ...symbols.map((s) => marketCurves[i][s]),
        ],
  );
  const lo = Math.min(0, ...values),
    hi = Math.max(0, ...values),
    span = hi - lo || 1;
  const x = (i: number) => 72 + (i / Math.max(1, points.length - 1)) * 940;
  const y = (v: number) => 285 - ((v - lo) / span) * 255;
  const polyline = (get: (p: DailyPoint, i: number) => number) =>
    points.map((p, i) => `${x(i)},${y(get(p, i))}`).join(" ");
  const h =
    hover == null
      ? null
      : points[Math.max(0, Math.min(points.length - 1, hover))];
  const ticks = [lo, (lo + hi) / 2, hi];
  return (
    <div className="collective-chart">
      <svg
        viewBox="0 0 1040 330"
        role="img"
        aria-label={
          mode === "daily"
            ? "Combined daily P&L chart"
            : "Combined cumulative P&L and market curves"
        }
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setHover(
            Math.round(
              ((((e.clientX - r.left) / r.width) * 1040 - 72) / 940) *
                (points.length - 1),
            ),
          );
        }}
      >
        {ticks.map((v, i) => (
          <g key={i}>
            <line x1="72" x2="1012" y1={y(v)} y2={y(v)} stroke="#e7ece8" />
            <text
              x="64"
              y={y(v) + 4}
              textAnchor="end"
              fontSize="12"
              fill="#66756c"
            >
              {compact(v)}
            </text>
          </g>
        ))}
        <line
          x1="72"
          x2="1012"
          y1={y(0)}
          y2={y(0)}
          stroke="#aebbb2"
          strokeDasharray="4 4"
        />
        {mode === "daily" ? (
          points.map((p, i) => (
            <line
              key={p.date}
              x1={x(i)}
              x2={x(i)}
              y1={y(0)}
              y2={y(p.pnl)}
              stroke={tone(p.pnl)}
              strokeWidth={Math.max(0.6, 800 / points.length)}
            />
          ))
        ) : (
          <>
            <polygon
              points={`${x(0)},${y(0)} ${polyline((p) => p.cumulative)} ${x(points.length - 1)},${y(0)}`}
              fill="#1e7a62"
              fillOpacity="0.08"
            />
            {symbols.map((s, i) => (
              <polyline
                key={s}
                points={polyline((_, j) => marketCurves[j][s])}
                fill="none"
                stroke={colors[i % colors.length]}
                strokeWidth="1.5"
                opacity=".85"
              />
            ))}
            {comparison && (
              <polyline
                points={polyline((p) => p.baselineCumulative)}
                fill="none"
                stroke="#7c8393"
                strokeWidth="2"
                strokeDasharray="6 5"
              />
            )}
            <polyline
              points={polyline((p) => p.cumulative)}
              fill="none"
              stroke="#1e7a62"
              strokeWidth="3"
              strokeLinejoin="round"
            />
            {points.length > 0 && (
              <circle
                cx={x(points.length - 1)}
                cy={y(points[points.length - 1].cumulative)}
                r="4.5"
                fill="#1e7a62"
                stroke="#fff"
                strokeWidth="1.5"
              />
            )}
          </>
        )}
        {h && (
          <line
            x1={x(points.indexOf(h))}
            x2={x(points.indexOf(h))}
            y1="30"
            y2="290"
            stroke="#64766b"
            strokeDasharray="3 3"
          />
        )}
        <text x="72" y="316" fontSize="12" fill="#66756c">
          {points[0]?.date}
        </text>
        <text x="1012" y="316" textAnchor="end" fontSize="12" fill="#66756c">
          {points.at(-1)?.date}
        </text>
      </svg>
      <Group gap="md" justify="space-between">
        <Group gap="md">
          <Text size="xs" fw={700} c="#16634f">
            Combined book
          </Text>
          {mode !== "daily" &&
            symbols.map((s, i) => (
              <Text key={s} size="xs" fw={600} c={colors[i % colors.length]}>
                {s}
              </Text>
            ))}
          {comparison && (
            <Text size="xs" c="dimmed">
              Dashed: always on
            </Text>
          )}
        </Group>
        <Text size="xs" className="collective-hover">
          {h
            ? `${h.date} · daily ${money(h.pnl)} · cumulative ${money(h.cumulative)}`
            : "Move over the chart to inspect a day"}
        </Text>
      </Group>
    </div>
  );
}

function Calendar({
  points,
  month,
  onMonth,
  onDay,
  selected,
}: {
  points: DailyPoint[];
  month: string;
  onMonth: (m: string) => void;
  onDay: (d: string) => void;
  selected: string;
}) {
  const [year, m] = month.split("-").map(Number);
  const offset = new Date(Date.UTC(year, m - 1, 1)).getUTCDay();
  const days = new Date(Date.UTC(year, m, 0)).getUTCDate(),
    lookup = new Map(points.map((p) => [p.date, p]));
  const inMonth = points.filter((p) => p.date.startsWith(month));
  const sum = inMonth.reduce((v, p) => v + p.pnl, 0);
  const scale = Math.max(1, ...inMonth.map((p) => Math.abs(p.pnl)));
  const title = new Date(Date.UTC(year, m - 1, 1)).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  function move(n: number) {
    onMonth(new Date(Date.UTC(year, m - 1 + n, 1)).toISOString().slice(0, 7));
  }
  return (
    <section className="wb-card" aria-label="Daily P&L calendar">
      <div className="wb-card-head">
        <Group gap="xs" wrap="nowrap" className="collective-month-nav">
          <ActionIcon
            variant="default"
            size="lg"
            aria-label="Previous month"
            onClick={() => move(-1)}
          >
            <IconChevronLeft size={16} />
          </ActionIcon>
          <h2 className="collective-month" id="collective-calendar">
            {title}
          </h2>
          <ActionIcon
            variant="default"
            size="lg"
            aria-label="Next month"
            onClick={() => move(1)}
          >
            <IconChevronRight size={16} />
          </ActionIcon>
          <TextInput
            aria-label="Calendar month"
            type="month"
            size="xs"
            value={month}
            onChange={(e) =>
              e.currentTarget.value && onMonth(e.currentTarget.value)
            }
            w={140}
            className="collective-month-input"
          />
        </Group>
        <div className="wb-month-sum">
          <span>
            Net <b style={{ color: tone(sum) }}>{money(sum)}</b>
          </span>
          <span>
            <b>{inMonth.filter((p) => p.pnl > 0).length}</b> up days
          </span>
          <span>
            <b>{inMonth.filter((p) => p.pnl < 0).length}</b> down days
          </span>
        </div>
      </div>
      <div className="collective-calendar">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
          <div className="calendar-heading" key={d}>
            {d}
          </div>
        ))}
        {Array.from({ length: offset }, (_, i) => (
          <div key={"blank" + i} />
        ))}
        {Array.from({ length: days }, (_, i) => {
          const day = `${month}-${String(i + 1).padStart(2, "0")}`,
            p = lookup.get(day);
          const strength = p ? 0.07 + 0.5 * Math.min(1, Math.abs(p.pnl) / scale) : 0;
          return (
            <button
              key={day}
              aria-label={`${day}: ${p ? money(p.pnl) : "Outside test window"}`}
              aria-pressed={selected === day}
              disabled={!p}
              className={`calendar-day ${p ? (p.pnl > 0 ? "gain" : p.pnl < 0 ? "loss" : "flat") : "uncovered"} ${selected === day ? "selected" : ""}`}
              style={
                p && p.pnl !== 0
                  ? {
                      background:
                        p.pnl > 0
                          ? `rgba(30,122,98,${strength.toFixed(2)})`
                          : `rgba(179,65,46,${strength.toFixed(2)})`,
                    }
                  : undefined
              }
              onClick={() => onDay(day)}
            >
              <span className="calendar-date">{i + 1}</span>
              <strong>
                {p
                  ? p.pnl === 0
                    ? "—"
                    : (p.pnl > 0 ? "+" : "") + compact(p.pnl)
                  : ""}
              </strong>
              <small>
                {p ? (p.trades ? `${p.trades} closed` : "") : "Outside"}
              </small>
            </button>
          );
        })}
      </div>
      <div className="wb-legend">
        <span>
          <i style={{ background: "rgba(30,122,98,.35)" }} />
          Gain
        </span>
        <span>
          <i style={{ background: "rgba(179,65,46,.35)" }} />
          Loss
        </span>
        <span>
          <i style={{ background: "#fff" }} />
          No recorded change
        </span>
        <span>
          <i className="hatch" />
          Outside test window
        </span>
        <span style={{ marginLeft: "auto" }}>UTC days</span>
      </div>
    </section>
  );
}

export function CollectiveDashboard({
  refreshKey,
  view,
  alerts,
}: {
  refreshKey: number;
  view: string;
  alerts?: ReactNode;
}) {
  const current: ViewName = (VIEWS as readonly string[]).includes(view)
    ? (view as ViewName)
    : "overview";
  const isMobile = useMediaQuery("(max-width: 900px)");
  const [initial] = useState(saved);
  const initialized = useRef(Boolean(initial));
  const [catalog, setCatalog] = useState<CollectiveCatalog | null>(null),
    [error, setError] = useState("");
  const [settings, setSettings] = useState<Settings>(
    initial || {
      copies: {},
      start: "2024-01-01",
      end: "2026-08-31",
      basis: "marked",
      policy: { ...defaultPolicy },
    },
  );
  const [histories, setHistories] = useState<CollectiveSeries[]>([]),
    [loading, setLoading] = useState(false),
    [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState("working"),
    [markets, setMarkets] = useState<string[]>([]),
    [timeframe, setTimeframe] = useState("all"),
    [search, setSearch] = useState("");
  const [month, setMonth] = useState(settings.end.slice(0, 7)),
    [day, setDay] = useState(""),
    [chartMode, setChartMode] = useState("cumulative");
  const [reload, setReload] = useState(0);
  const [pickerOpen, setPickerOpen] = useState(view === "strategies");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState<boolean | null>(null);
  const collapsed =
    railCollapsed ?? (current === "calendar" || current === "pause");
  useEffect(() => {
    // The legacy #collective-strategies link opens the picker.
    if (view === "strategies") {
      setPickerOpen(true);
      history.replaceState(null, "", href("portfolio"));
    }
  }, [view]);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/workbench/collective", { signal: controller.signal })
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d.error);
        return d as CollectiveCatalog;
      })
      .then((d) => {
        setCatalog(d);
        setError("");
        setHistories([]);
        const seedDefaults = !initialized.current;
        initialized.current = true;
        setSettings((s) => ({
          ...s,
          copies: Object.keys(s.copies).length
            ? Object.fromEntries(
                Object.entries(s.copies).filter(([id]) =>
                  d.items.some((i) => i.id === id),
                ),
              )
            : seedDefaults
              ? Object.fromEntries(
                  d.items.filter((i) => i.working).map((i) => [i.id, 1]),
                )
              : s.copies,
        }));
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(String(e));
      });
    return () => controller.abort();
  }, [refreshKey, reload, initial]);
  useEffect(() => {
    // Persist only after the catalog has seeded or reconciled the selection.
    if (!initialized.current) return;
    try {
      localStorage.setItem("quant-collective-v1", JSON.stringify(settings));
    } catch {
      /* Storage may be unavailable; the current combination still works. */
    }
  }, [settings]);
  const ids = Object.entries(settings.copies)
    .filter(([, n]) => n > 0)
    .map(([id]) => id)
    .sort()
    .join(",");
  useEffect(() => {
    const controller = new AbortController();
    if (!catalog || !ids) return () => controller.abort();
    fetch("/api/workbench/collective/series", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: ids.split(",") }),
      signal: controller.signal,
    })
      .then(async (r) => {
        const data = await r.json();
        if (!r.ok) throw new Error(data.error);
        return data;
      })
      .then((data) => {
        setHistories(data);
        setError("");
        setLoading(false);
      })
      .catch((e) => {
        if (e.name !== "AbortError") {
          setError(String(e));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [ids, catalog]);
  async function refreshEvidence() {
    setRefreshing(true);
    setError("");
    try {
      const response = await fetch("/api/workbench/collective/refresh", {
        method: "POST",
      });
      if (!response.ok) throw new Error("Could not start evidence refresh");
      let done = false;
      while (!done) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const status = await (
          await fetch("/api/workbench/collective/status")
        ).json();
        if (!status.running) {
          done = true;
          if (status.error) throw new Error(status.error);
        }
      }
      setReload((n) => n + 1);
    } catch (e) {
      setError(String(e));
    } finally {
      setRefreshing(false);
    }
  }
  function choose(copies: Record<string, number>) {
    setLoading(true);
    setSettings((s) => ({ ...s, copies }));
  }
  function policy(next: Partial<GatePolicy>) {
    setSettings((s) => ({
      ...s,
      basis: next.enabled ? "closed" : s.basis,
      policy: { ...s.policy, ...next },
    }));
  }
  const selected = useMemo(
    () => (catalog?.items || []).filter((i) => settings.copies[i.id] > 0),
    [catalog, settings.copies],
  );
  const visible = useMemo(
    () =>
      (catalog?.items || []).filter(
        (i) =>
          (filter === "all" ||
            (filter === "working"
              ? i.working
              : filter === "feasible"
                ? i.feasible
                : !i.tested)) &&
          (!markets.length || markets.includes(i.symbol)) &&
          (timeframe === "all" || i.timeframe === timeframe) &&
          `${i.name} ${i.symbol} ${i.timeframe} ${i.session} ${i.source}`
            .toLowerCase()
            .includes(search.toLowerCase()),
      ),
    [catalog, filter, markets, timeframe, search],
  );
  const computed = useMemo(() => {
    try {
      return {
        value: calculatePortfolio(
          selected,
          histories,
          settings.copies,
          settings.start,
          settings.end,
          settings.basis,
          settings.policy,
        ),
        error: "",
      };
    } catch (e) {
      return { value: null, error: String(e instanceof Error ? e.message : e) };
    }
  }, [selected, histories, settings]);
  const result = computed.value,
    hidden = selected.filter((i) => !visible.some((v) => v.id === i.id));
  const selectedDay = result?.points.find((p) => p.date === day);
  const capital = selected.reduce(
    (n, i) => n + i.capital * (settings.copies[i.id] || 0),
    0,
  );
  const totals =
    result?.points.reduce(
      (a, p) => {
        for (const [s, n] of Object.entries(p.bySymbol)) a[s] = (a[s] || 0) + n;
        return a;
      },
      {} as Record<string, number>,
    ) || {};
  const annual =
    result?.points.reduce(
      (a, p) => {
        const y = p.date.slice(0, 4);
        a[y] = (a[y] || 0) + p.pnl;
        return a;
      },
      {} as Record<string, number>,
    ) || {};
  const marketCount = new Set(selected.map((i) => i.symbol)).size;
  function useCommon() {
    const w = commonWindow(selected);
    if (w.start && w.end && w.start <= w.end) {
      setSettings((s) => ({ ...s, ...w }));
      setMonth(w.end.slice(0, 7));
    }
  }
  function exportDaily() {
    if (result)
      download(
        "combined-daily-pnl.csv",
        [
          "date,pnl,always_on_pnl,cumulative_pnl,always_on_cumulative_pnl,equity,drawdown,closed_trades",
          ...result.points.map((p) =>
            [
              p.date,
              p.pnl,
              p.baseline,
              p.cumulative,
              p.baselineCumulative,
              p.equity,
              p.drawdown,
              p.trades,
            ].join(","),
          ),
        ].join("\n"),
      );
  }
  function exportCombination() {
    download(
      "strategy-combination.json",
      JSON.stringify(
        {
          version: 1,
          catalog_at: catalog?.generated_at,
          ...settings,
          selected: selected.map((i) => ({
            id: i.id,
            name: i.name,
            key: i.key,
            source: i.source,
            checksum: i.checksum,
          })),
          results: result
            ? {
                pnl: result.net,
                max_drawdown: result.maxDrawdown,
                capital: result.capital,
              }
            : null,
        },
        null,
        2,
      ),
      "application/json",
    );
  }
  const accountingLabel =
    settings.basis === "marked" ? "daily marked P&L" : "closed-trade P&L";
  const volatility = settings.policy.mode === "volatility";

  // ---------- combination rail ----------
  const railBody = (
    <>
      <div className="wb-rail-head">
        <div>
          <h2>Combination</h2>
          <p>
            <span data-testid="selected-count">
              {selected.length} {selected.length === 1 ? "book" : "books"}
            </span>{" "}
            · {money(capital)}
          </p>
        </div>
        <Group gap={4} wrap="nowrap">
          <Button
            size="compact-sm"
            variant="light"
            leftSection={<IconPlus size={13} />}
            onClick={() => {
              setSheetOpen(false);
              setPickerOpen(true);
            }}
          >
            Add
          </Button>
          {!isMobile && (
            <ActionIcon
              variant="subtle"
              color="gray"
              aria-label="Collapse combination"
              onClick={() => setRailCollapsed(true)}
            >
              <IconChevronRight size={15} />
            </ActionIcon>
          )}
        </Group>
      </div>
      {selected.length ? (
        <ul className="wb-books" data-testid="selected-strategies">
          {selected.map((i) => (
            <li key={i.id}>
              <div className="wb-book-text">
                <div className="wb-book-name" title={i.name}>
                  {i.name}
                </div>
                <div className="wb-book-meta">
                  {i.symbol} · {i.timeframe} · {i.session}
                </div>
              </div>
              <NumberInput
                aria-label={`Copies of ${i.name} ${i.symbol} ${i.timeframe}`}
                size="xs"
                w={62}
                min={1}
                max={100}
                allowDecimal={false}
                value={settings.copies[i.id]}
                onChange={(n) =>
                  setSettings((s) => ({
                    ...s,
                    copies: {
                      ...s.copies,
                      [i.id]: Math.max(1, Math.min(100, Number(n) || 1)),
                    },
                  }))
                }
              />
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                aria-label={`Remove ${i.name} ${i.symbol} ${i.timeframe}`}
                onClick={() => {
                  const next = { ...settings.copies };
                  delete next[i.id];
                  choose(next);
                }}
              >
                <IconX size={13} />
              </ActionIcon>
            </li>
          ))}
        </ul>
      ) : (
        <Text size="sm" c="dimmed">
          {catalog
            ? "No books yet. Add strategies to build a combination."
            : "Loading the combination…"}
        </Text>
      )}
      <div className="wb-rail-section">
        <SimpleGrid cols={2} spacing={6}>
          <TextInput
            type="date"
            size="xs"
            label="P&L start"
            value={settings.start}
            onChange={(e) => {
              const start = e.currentTarget.value;
              setSettings((s) => ({ ...s, start }));
            }}
          />
          <TextInput
            type="date"
            size="xs"
            label="P&L end"
            value={settings.end}
            onChange={(e) => {
              const end = e.currentTarget.value;
              setSettings((s) => ({ ...s, end }));
              if (end) setMonth(end.slice(0, 7));
            }}
          />
        </SimpleGrid>
        <button
          type="button"
          className="wb-link-button"
          onClick={useCommon}
          disabled={!selected.length}
        >
          Use common tested window
        </button>
      </div>
      <div className="wb-rail-section">
        <span className="wb-rail-label">Accounting</span>
        <SegmentedControl
          aria-label="P&L accounting"
          size="xs"
          fullWidth
          value={settings.basis}
          disabled={settings.policy.enabled}
          onChange={(v) =>
            setSettings((s) => ({
              ...s,
              basis: v === "closed" ? "closed" : "marked",
            }))
          }
          data={[
            { value: "marked", label: "Marked daily" },
            { value: "closed", label: "Closed trades" },
          ]}
        />
        <Text size="xs" c="dimmed">
          {settings.policy.enabled
            ? "The pause & sizing replay uses closed-trade accounting."
            : settings.basis === "marked"
              ? "Includes open P&L at daily observations."
              : "Books each complete net trade on its exit date."}
        </Text>
      </div>
      <Text size="xs" c="dimmed">
        Copies repeat each recorded book and its capital; they do not rerun
        sizing.
      </Text>
      <div className="wb-rail-foot">
        <Button
          size="compact-sm"
          variant="default"
          leftSection={<IconDownload size={13} />}
          onClick={exportDaily}
          disabled={!result}
        >
          Daily P&L CSV
        </Button>
        <Button
          size="compact-sm"
          variant="default"
          onClick={exportCombination}
          disabled={!selected.length}
        >
          Combination JSON
        </Button>
      </div>
    </>
  );

  // ---------- views ----------
  const loadingState = (
    <Group>
      <Loader size="sm" />
      <Text>Loading strategy catalog…</Text>
    </Group>
  );
  const emptyState = (
    <section className="wb-card">
      <h2>{selected.length ? "Combined book unavailable" : "No books selected"}</h2>
      <p className="wb-card-sub">
        {selected.length
          ? "Adjust the window in the combination panel to a period every selected book covers."
          : "Add tested strategies to see their combined P&L, calendar and contributions."}
      </p>
      {!selected.length && (
        <Button
          mt="md"
          variant="light"
          leftSection={<IconPlus size={14} />}
          onClick={() => setPickerOpen(true)}
        >
          Add strategies
        </Button>
      )}
    </section>
  );

  const overview = result ? (
    <>
      <div className="wb-kpis" data-testid="portfolio-metrics">
        <div className="wb-kpi lead">
          <span className="wb-kpi-label">Combined net P&L</span>
          <span className={`wb-kpi-value ${signed(result.net)}`}>
            {money(result.net)}
          </span>
          <span className="wb-kpi-note">
            {pct(result.returnOnCapital)} on represented capital
          </span>
        </div>
        <div className="wb-kpi">
          <span className="wb-kpi-label">Maximum drawdown</span>
          <span className="wb-kpi-value">
            {money(result.maxDrawdownDollars)}
          </span>
          <span className="wb-kpi-note">
            {pct(Math.abs(result.maxDrawdown))} ·{" "}
            {settings.basis === "marked" ? "daily closes" : "closed trades only"}
          </span>
        </div>
        <div className="wb-kpi">
          <span className="wb-kpi-label">Combination score</span>
          <span className="wb-kpi-value">
            {result.recoveryFactor?.toFixed(2) || "Undefined"}
          </span>
          <span className="wb-kpi-note">Net P&L ÷ max drawdown dollars</span>
        </div>
        <div className="wb-kpi">
          <span className="wb-kpi-label">Profit factor</span>
          <span className="wb-kpi-value">
            {result.profitFactor?.toFixed(2) ?? "No finite ratio"}
          </span>
          <span className="wb-kpi-note">Closed-trade gains ÷ losses</span>
        </div>
      </div>
      <div className="wb-kpi-sub">
        <span>
          Winning trades{" "}
          <b>{result.winRate == null ? "none" : pct(result.winRate)}</b> of{" "}
          {result.trades.toLocaleString()}
        </span>
        <span>
          Positive days{" "}
          <b>
            {result.positiveDays} / {result.activeDays}
          </b>
        </span>
        <span>
          Capital represented <b>{money(result.capital)}</b>, no netting
        </span>
        {settings.policy.enabled && (
          <span>
            {volatility ? "Effect of volatility scaling" : "Effect of pause rule"}{" "}
            <b className={signed(result.net - result.baseline)}>
              {money(result.net - result.baseline)}
            </b>{" "}
            vs always-on {money(result.baseline)}
            {volatility && ` · average size ×${result.exposure.toFixed(2)}`}
          </span>
        )}
      </div>
      <section className="wb-card">
        <div className="wb-card-head">
          <div>
            <h2>Combined P&L across charts</h2>
            <p className="wb-card-sub">
              {settings.basis === "marked"
                ? "Daily marked P&L, including open positions"
                : "Closed-trade P&L assigned to UTC exit dates"}{" "}
              · net of recorded costs
            </p>
          </div>
          <Select
            aria-label="P&L chart mode"
            size="xs"
            w={220}
            maw="100%"
            value={chartMode}
            onChange={(v) => setChartMode(v || "cumulative")}
            data={[
              { value: "cumulative", label: "Cumulative + every market" },
              { value: "daily", label: "Daily P&L bars" },
            ]}
          />
        </div>
        <PnlChart
          points={result.points}
          mode={chartMode}
          comparison={settings.policy.enabled}
        />
      </section>
      <div className="wb-two">
        <section className="wb-card">
          <h2>P&L by market</h2>
          <Table data-testid="market-contributions" mt={6}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Market</Table.Th>
                <Table.Th ta="right">Books</Table.Th>
                <Table.Th ta="right">Net P&L</Table.Th>
                <Table.Th w="28%" />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {Object.entries(totals)
                .sort()
                .map(([s, n]) => {
                  const scale = Math.max(
                    1,
                    ...Object.values(totals).map(Math.abs),
                  );
                  return (
                    <Table.Tr key={s}>
                      <Table.Td>{s}</Table.Td>
                      <Table.Td ta="right">
                        {selected.filter((i) => i.symbol === s).length}
                      </Table.Td>
                      <Table.Td ta="right" c={tone(n)} className="mono">
                        {money(n)}
                      </Table.Td>
                      <Table.Td>
                        <div
                          className="collective-bar"
                          style={{
                            width: `${(Math.abs(n) / scale) * 100}%`,
                            background: tone(n),
                          }}
                        />
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
            </Table.Tbody>
          </Table>
        </section>
        <section className="wb-card">
          <h2>P&L by year</h2>
          <Table mt={6}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Year</Table.Th>
                <Table.Th ta="right">Net P&L</Table.Th>
                <Table.Th w="35%" />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {Object.entries(annual)
                .sort()
                .map(([s, n]) => {
                  const scale = Math.max(
                    1,
                    ...Object.values(annual).map(Math.abs),
                  );
                  return (
                    <Table.Tr key={s}>
                      <Table.Td>
                        {s}
                        {s === settings.end.slice(0, 4) &&
                        !settings.end.endsWith("12-31") ? (
                          <Text span size="xs" c="dimmed">
                            {" "}
                            partial
                          </Text>
                        ) : null}
                      </Table.Td>
                      <Table.Td ta="right" c={tone(n)} className="mono">
                        {money(n)}
                      </Table.Td>
                      <Table.Td>
                        <div
                          className="collective-bar"
                          style={{
                            width: `${(Math.abs(n) / scale) * 100}%`,
                            background: tone(n),
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
  ) : (
    emptyState
  );

  const dayIndex = result && day ? result.points.findIndex((p) => p.date === day) : -1;
  const calendarView = result ? (
    <div className="wb-calendar-layout">
      <Calendar
        points={result.points}
        month={month}
        onMonth={setMonth}
        onDay={setDay}
        selected={day}
      />
      <section className="wb-card" aria-live="polite">
        {selectedDay ? (
          <>
            <h2 className="wb-day-label">
              {weekday(day)} {day}
            </h2>
            <div className="wb-day-total" style={{ color: tone(selectedDay.pnl) }}>
              {money(selectedDay.pnl)}
            </div>
            <Text size="sm" c="dimmed">
              {selectedDay.trades} closed trades ·{" "}
              {settings.basis === "marked"
                ? "marked changes can occur without an exit."
                : "only trades closing this day contribute."}
            </Text>
            <Table mt="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Strategy / chart</Table.Th>
                  <Table.Th ta="right">Contribution</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {[...selected]
                  .sort(
                    (a, b) =>
                      Math.abs(selectedDay.byStrategy[b.id] || 0) -
                      Math.abs(selectedDay.byStrategy[a.id] || 0),
                  )
                  .map((i) => {
                    const v = selectedDay.byStrategy[i.id] || 0;
                    return (
                      <Table.Tr key={i.id}>
                        <Table.Td>
                          <Text size="sm" fw={600}>
                            {i.name}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {i.symbol} · {i.timeframe}
                          </Text>
                        </Table.Td>
                        <Table.Td ta="right" c={v ? tone(v) : "dimmed"} className="mono">
                          {money(v)}
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
              </Table.Tbody>
            </Table>
            <Group justify="space-between" mt="md">
              <Button
                size="compact-sm"
                variant="default"
                leftSection={<IconChevronLeft size={13} />}
                disabled={dayIndex <= 0}
                onClick={() => {
                  const d = result.points[dayIndex - 1].date;
                  setDay(d);
                  setMonth(d.slice(0, 7));
                }}
              >
                Previous day
              </Button>
              <Button
                size="compact-sm"
                variant="default"
                rightSection={<IconChevronRight size={13} />}
                disabled={dayIndex < 0 || dayIndex >= result.points.length - 1}
                onClick={() => {
                  const d = result.points[dayIndex + 1].date;
                  setDay(d);
                  setMonth(d.slice(0, 7));
                }}
              >
                Next day
              </Button>
            </Group>
          </>
        ) : (
          <>
            <h2>Pick a day</h2>
            <p className="wb-card-sub">
              Click any covered date to see each strategy’s contribution to that
              day.
            </p>
          </>
        )}
      </section>
    </div>
  ) : (
    emptyState
  );

  const contributionsView = result ? (
    <section className="wb-card">
      <div className="wb-card-head">
        <h2>Every strategy’s contribution</h2>
        <Text size="xs" c="dimmed">
          {settings.start} to {settings.end} · {accountingLabel}
        </Text>
      </div>
      <ScrollArea>
        <Table miw={820} data-testid="strategy-contributions" highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Strategy / chart</Table.Th>
              <Table.Th ta="right">Net P&L</Table.Th>
              <Table.Th ta="right">Always on</Table.Th>
              <Table.Th ta="right">Closed trades</Table.Th>
              <Table.Th ta="right">Skipped</Table.Th>
              <Table.Th>At cutoff</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {result.components.map((c) => (
              <Table.Tr key={c.id}>
                <Table.Td>
                  <Text size="sm" fw={600}>
                    {c.name} / {c.symbol}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {selected.find((i) => i.id === c.id)?.timeframe} ·{" "}
                    {selected.find((i) => i.id === c.id)?.session}
                  </Text>
                </Table.Td>
                <Table.Td ta="right" c={tone(c.pnl)} className="mono">
                  {money(c.pnl)}
                </Table.Td>
                <Table.Td ta="right" className="mono">
                  {money(c.baseline)}
                </Table.Td>
                <Table.Td ta="right">{c.trades}</Table.Td>
                <Table.Td ta="right">{c.skipped}</Table.Td>
                <Table.Td>
                  <Badge color={stateColor[c.state]} radius="xs" variant="light">
                    {settings.policy.enabled ? c.state : "Always on"}
                  </Badge>
                  {volatility && settings.policy.enabled && (
                    <Text size="xs" c="dimmed">
                      average size ×{c.exposure.toFixed(2)}
                    </Text>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
    </section>
  ) : (
    emptyState
  );

  const numberField = (
    label: string,
    value: number,
    set: (n: number) => void,
    props: { min?: number; max?: number; step?: number; decimal?: boolean } = {},
  ) => (
    <NumberInput
      label={label}
      size="xs"
      min={props.min}
      max={props.max}
      step={props.step}
      allowDecimal={!!props.decimal}
      decimalScale={props.decimal ? 2 : undefined}
      value={value}
      onChange={(n) => set(Number(n))}
    />
  );
  const p = settings.policy;
  const settingsCard = (
    <section className="wb-card collective-policy-settings">
      <Switch
        label="Enable pause/resume replay"
        checked={p.enabled}
        onChange={(e) => policy({ enabled: e.currentTarget.checked })}
      />
      {p.enabled ? (
        <>
          <Select
            label="Losing pattern"
            size="xs"
            value={p.mode}
            onChange={(v) =>
              policy({ mode: (v || "rolling") as GatePolicy["mode"] })
            }
            data={[
              { value: "rolling", label: "Rolling closed-trade losses" },
              { value: "streak", label: "Consecutive losing trades" },
              { value: "drawdown", label: "Shadow equity drawdown" },
              {
                value: "volatility",
                label: "Scale size by realized volatility (no pause)",
              },
            ]}
          />
          <div className="wb-policy-group">
            <h3>{volatility ? "Size by" : "Pause when"}</h3>
            <SimpleGrid cols={2} spacing={8}>
              {p.mode === "rolling" ? (
                <>
                  {numberField("Lookback trades", p.lookback, (n) =>
                    policy({ lookback: Math.max(2, n || 2) }),
                    { min: 2, max: 100 },
                  )}
                  {numberField(
                    "Rolling loss threshold ($ / copy)",
                    p.lossLimit,
                    (n) => policy({ lossLimit: Math.max(0, n || 0) }),
                    { min: 0 },
                  )}
                </>
              ) : p.mode === "streak" ? (
                numberField("Consecutive losses to pause", p.streak, (n) =>
                  policy({ streak: Math.max(1, n || 1) }),
                  { min: 1, max: 50 },
                )
              ) : p.mode === "drawdown" ? (
                numberField(
                  "Drawdown threshold ($ / copy)",
                  p.drawdown,
                  (n) => policy({ drawdown: Math.max(1, n || 1) }),
                  { min: 1 },
                )
              ) : (
                <>
                  {numberField(
                    "Volatility lookback (positioned days)",
                    p.volLookback,
                    (n) =>
                      policy({ volLookback: Math.min(250, Math.max(10, n || 10)) }),
                    { min: 10, max: 250 },
                  )}
                  {numberField(
                    "Maximum size multiple",
                    p.volCap,
                    (n) => policy({ volCap: Math.min(4, Math.max(0.25, n || 1)) }),
                    { min: 0.25, max: 4, step: 0.25, decimal: true },
                  )}
                </>
              )}
            </SimpleGrid>
          </div>
          {!volatility && (
            <div className="wb-policy-group">
              <h3>Resume after</h3>
              <SimpleGrid cols={2} spacing={8}>
                {numberField("Cooldown (calendar days)", p.cooldown, (n) =>
                  policy({ cooldown: Math.max(1, n || 1) }),
                  { min: 1, max: 365 },
                )}
                {numberField("Shadow recovery trades", p.recovery, (n) =>
                  policy({ recovery: Math.max(1, n || 1) }),
                  { min: 1, max: 100 },
                )}
              </SimpleGrid>
            </div>
          )}
          <Text size="xs" c="dimmed">
            Each decision uses only outcomes closed before it. Fields change
            with the pattern you pick.
          </Text>
        </>
      ) : (
        <Text size="sm" c="dimmed">
          Test a fixed loss rule, or volatility-scaled sizing, against the same
          strategies always on. Turning it on switches accounting to closed
          trades.
        </Text>
      )}
    </section>
  );
  const deps = result?.dependence || [];
  const clusters = deps.filter((d) => d.verdict === "cluster").length;
  const single = deps.length === 1 ? deps[0] : null;
  const verdictClass = single
    ? single.verdict
    : clusters
      ? "cluster"
      : deps.some((d) => d.verdict === "alternate")
        ? "alternate"
        : "none";
  const skipped = result?.components.reduce((n, c) => n + c.skipped, 0) || 0;
  const cutoffStates = result
    ? Object.entries(
        result.components.reduce(
          (a, c) => ({ ...a, [c.state]: (a[c.state] || 0) + 1 }),
          {} as Record<string, number>,
        ),
      )
    : [];
  const pauseView = (
    <div className="wb-policy">
      {settingsCard}
      <div className="collective-policy-results">
        {!p.enabled ? (
          <section className="wb-card">
            <h2>Replay is off</h2>
            <p className="wb-card-sub">
              Turn on the replay to see whether losses cluster, how a pause or
              sizing rule compares with always-on trading, and every decision it
              would have made.
            </p>
          </section>
        ) : !result ? (
          emptyState
        ) : (
          <>
            <div className={`wb-verdict ${verdictClass}`}>
              <span className="wb-verdict-icon" aria-hidden="true">
                {verdictClass === "cluster" ? (
                  <IconCheck size={17} />
                ) : (
                  <IconX size={17} />
                )}
              </span>
              <h2>
                {single
                  ? verdictCopy[single.verdict][0]
                  : `${clusters} of ${deps.length} selected books show loss clustering`}
              </h2>
              <p>
                {single
                  ? verdictCopy[single.verdict][1]
                  : clusters
                    ? "A pause rule has a statistical basis only for those books."
                    : "Without persistence, a loss-triggered pause is expected to give up return; a worse result below is the expected outcome, not bad luck."}
                {volatility &&
                  " Volatility scaling changes size without conditioning on P&L."}
              </p>
              {single && (
                <div className="collective-stats">
                  <div>
                    <span>
                      Trades {single.prior ? "before window" : "in window"}
                    </span>
                    <b>{single.trades.toLocaleString()}</b>
                  </div>
                  <div>
                    <span>Lag-1 autocorrelation</span>
                    <b>
                      {Number.isFinite(single.autocorrelation)
                        ? single.autocorrelation.toFixed(3)
                        : "—"}
                    </b>
                  </div>
                  <div>
                    <span>Runs z</span>
                    <b>
                      {Number.isFinite(single.runsZ)
                        ? single.runsZ.toFixed(2)
                        : "—"}
                    </b>
                  </div>
                  <div>
                    <span>Mean after loss</span>
                    <b>
                      {Number.isFinite(single.afterLoss)
                        ? money(single.afterLoss)
                        : "—"}
                    </b>
                  </div>
                  <div>
                    <span>Mean after win</span>
                    <b>
                      {Number.isFinite(single.afterWin)
                        ? money(single.afterWin)
                        : "—"}
                    </b>
                  </div>
                </div>
              )}
            </div>
            <div className="wb-compare" data-testid="policy-comparison">
              <div>
                <span>
                  {volatility ? "With volatility scaling" : "With pause rule"}
                </span>
                <strong className={signed(result.net)}>{money(result.net)}</strong>
              </div>
              <div>
                <span>Always on</span>
                <strong>{money(result.baseline)}</strong>
              </div>
              <div>
                <span>Difference</span>
                <strong className={signed(result.net - result.baseline)}>
                  {money(result.net - result.baseline)}
                </strong>
              </div>
              <div className="wb-compare-foot">
                <span>{result.trades.toLocaleString()} closed trades</span>
                <span>{skipped.toLocaleString()} skipped</span>
                {volatility ? (
                  <span>average size ×{result.exposure.toFixed(2)}</span>
                ) : (
                  <span>
                    At cutoff{" "}
                    {cutoffStates.map(([s, n]) => (
                      <Badge
                        key={s}
                        color={stateColor[s as GateState]}
                        variant="light"
                        radius="xs"
                        size="sm"
                        ml={4}
                      >
                        {n > 1 ? `${n} ${s}` : s}
                      </Badge>
                    ))}
                  </span>
                )}
              </div>
            </div>
            <section className="wb-card" data-testid="dependence-check">
              <h2>Do losses cluster?</h2>
              <p className="wb-card-sub">
                A loss-triggered pause can only add expected return when
                outcomes persist (Kaminski &amp; Lo, 2014). Runs test on
                win/loss signs, using trades closed before the window when at
                least 30 exist, otherwise the window itself. z below −1.96 means
                streaks; above +1.96 means alternation.
              </p>
              <ScrollArea mt="sm">
                <Table miw={760}>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Strategy / chart</Table.Th>
                      <Table.Th ta="right">Trades</Table.Th>
                      <Table.Th ta="right">Lag-1</Table.Th>
                      <Table.Th ta="right">Runs z</Table.Th>
                      <Table.Th ta="right">After loss</Table.Th>
                      <Table.Th ta="right">After win</Table.Th>
                      <Table.Th>Verdict</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {deps.map((d) => (
                      <Table.Tr key={d.id}>
                        <Table.Td>
                          {d.name} / {d.symbol}
                        </Table.Td>
                        <Table.Td ta="right">
                          {d.trades}{" "}
                          <Text span size="xs" c="dimmed">
                            {d.prior ? "before window" : "in window"}
                          </Text>
                        </Table.Td>
                        <Table.Td ta="right">
                          {Number.isFinite(d.autocorrelation)
                            ? d.autocorrelation.toFixed(3)
                            : "—"}
                        </Table.Td>
                        <Table.Td ta="right">
                          {Number.isFinite(d.runsZ) ? d.runsZ.toFixed(2) : "—"}
                        </Table.Td>
                        <Table.Td ta="right">
                          {Number.isFinite(d.afterLoss) ? money(d.afterLoss) : "—"}
                        </Table.Td>
                        <Table.Td ta="right">
                          {Number.isFinite(d.afterWin) ? money(d.afterWin) : "—"}
                        </Table.Td>
                        <Table.Td>
                          <Badge color={verdicts[d.verdict][1]} radius="xs" variant="light">
                            {verdicts[d.verdict][0]}
                          </Badge>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
            </section>
            <Alert color="yellow">
              {volatility
                ? "Exploratory sizing replay. Each entry is scaled by target ÷ recent volatility, where volatility is the standard deviation of the book's last positioned marked-P&L days before entry and the target is the median of that estimate before the window. Sizes are fixed at entry and capped. Fractional multiples assume divisible contracts; margin and strategy state are not rerun. "
                : "Exploratory entry-filter replay. Decisions use only trades closed before entry; recovery observes hypothetical trades while paused. Existing positions keep their original exits. Strategy state, sizing and margin are not rerun; skipped entries can change them in a full simulation. "}
              P&amp;L is realized on exit dates, so open risk is not shown.
              Parameters are not optimized and no live orders are controlled.
            </Alert>
            <section className="wb-card">
              <div className="wb-card-head">
                <h2>
                  {volatility ? "Size band changes" : "Pause / resume decisions"}{" "}
                  ({result.events.length})
                </h2>
                <Button
                  size="compact-sm"
                  variant="default"
                  leftSection={<IconDownload size={13} />}
                  onClick={() =>
                    download(
                      "pause-resume-decisions.csv",
                      [
                        "timestamp,strategy,state,reason",
                        ...result.events.map((e) =>
                          [e.timestamp, e.name, e.state, e.reason]
                            .map(csvCell)
                            .join(","),
                        ),
                      ].join("\n"),
                    )
                  }
                >
                  Export decisions
                </Button>
              </div>
              <ScrollArea h={320}>
                <Table miw={680}>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Known at</Table.Th>
                      <Table.Th>Strategy</Table.Th>
                      <Table.Th>Decision</Table.Th>
                      <Table.Th>Reason</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {result.events.map((e, i) => (
                      <Table.Tr key={i}>
                        <Table.Td className="mono" style={{ whiteSpace: "nowrap" }}>
                          {e.timestamp.replace("T", " ").slice(0, 16)}
                        </Table.Td>
                        <Table.Td>{e.name}</Table.Td>
                        <Table.Td>
                          <Badge color={stateColor[e.state]} radius="xs" variant="light">
                            {e.state}
                          </Badge>
                        </Table.Td>
                        <Table.Td>{e.reason}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
                {!result.events.length && (
                  <Text c="dimmed" size="sm" py="sm">
                    No state changes in this reporting window.
                  </Text>
                )}
              </ScrollArea>
            </section>
          </>
        )}
      </div>
    </div>
  );

  // ---------- strategy picker ----------
  const counts = catalog
    ? {
        working: catalog.items.filter((i) => i.working).length,
        feasible: catalog.items.filter((i) => i.feasible).length,
        all: catalog.items.length,
        screen: catalog.items.filter((i) => !i.tested).length,
      }
    : { working: 0, feasible: 0, all: 0, screen: 0 };
  const picker = catalog && (
    <div className="collective-picker">
      <Text size="sm" c="dimmed">
        Pick tested configurations for this combination. Filters only change
        what you see here; books you already chose stay in the combination.
      </Text>
      <SegmentedControl
        aria-label="Eligibility filter"
        fullWidth
        orientation={isMobile ? "vertical" : "horizontal"}
        value={filter}
        onChange={setFilter}
        data={[
          { value: "working", label: `Working · ${counts.working}` },
          {
            value: "feasible",
            label: `Fully tested & feasible · ${counts.feasible}`,
          },
          { value: "all", label: `All tested configurations · ${counts.all}` },
          { value: "screen", label: `Screened only · ${counts.screen}` },
        ]}
      />
      <Text size="xs" c="dimmed">
        {filter === "feasible"
          ? catalog.definitions.feasible
          : catalog.definitions.working}{" "}
        Screening profits alone do not qualify as working.
      </Text>
      <div className="collective-filters">
        <Group gap={6} align="center">
          <Text size="sm" fw={600} mr={4}>
            Markets
          </Text>
          <Chip
            size="sm"
            checked={!markets.length}
            onChange={() => setMarkets([])}
          >
            All
          </Chip>
          <Chip.Group multiple value={markets} onChange={setMarkets}>
            {[...new Set(catalog.items.map((i) => i.symbol))].sort().map((s) => (
              <Chip key={s} value={s} size="sm">
                {s}
              </Chip>
            ))}
          </Chip.Group>
        </Group>
        <Group gap={8} align="end" wrap="nowrap" className="collective-filter-fields">
          <Select
            label="Chart timeframe"
            size="xs"
            w={150}
            value={timeframe}
            onChange={(v) => setTimeframe(v || "all")}
            data={[
              { value: "all", label: "All timeframes" },
              ...[...new Set(catalog.items.map((i) => i.timeframe))]
                .sort()
                .map((value) => ({ value, label: value })),
            ]}
          />
          <TextInput
            label="Find a strategy"
            size="xs"
            placeholder="Name, session or source"
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
          />
        </Group>
      </div>
      <ScrollArea className="collective-picker-table">
        <Table miw={880} highlightOnHover data-testid="strategy-picker">
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={40}>
                <span className="visually-hidden">Include</span>
              </Table.Th>
              <Table.Th>Strategy / chart</Table.Th>
              <Table.Th>Evidence</Table.Th>
              <Table.Th>Test coverage</Table.Th>
              <Table.Th ta="right">2024 onward</Table.Th>
              <Table.Th>Review notes</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visible.map((i) => (
              <Table.Tr key={i.id}>
                <Table.Td>
                  <Checkbox
                    aria-label={`Include ${i.name} ${i.symbol} ${i.timeframe} ${i.source}`}
                    checked={settings.copies[i.id] > 0}
                    disabled={!settings.copies[i.id] && selected.length >= 100}
                    onChange={(e) => {
                      const next = { ...settings.copies };
                      if (e.currentTarget.checked) next[i.id] = 1;
                      else delete next[i.id];
                      choose(next);
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <Text fw={600} size="sm">
                    {i.name}
                  </Text>
                  <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
                    {i.symbol} · {i.timeframe} · {i.session}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Badge
                    radius="xs"
                    variant="light"
                    color={i.feasible ? "teal" : i.working ? "blue" : "gray"}
                  >
                    {i.feasible
                      ? "Checklist passed"
                      : i.working
                        ? "Working"
                        : i.tested
                          ? "Needs review"
                          : "Screened"}
                  </Badge>
                  <Text size="xs" c="dimmed">
                    {i.source}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="xs" className="mono" style={{ whiteSpace: "nowrap" }}>
                    {i.start} → {i.end}
                  </Text>
                </Table.Td>
                <Table.Td ta="right" c={tone(i.recent_pnl)} className="mono">
                  {i.end < "2024" ? "Not tested" : money(i.recent_pnl)}
                </Table.Td>
                <Table.Td maw={280}>
                  <details>
                    <summary>
                      {i.reasons[0]
                        ? i.reasons[0].length > 60
                          ? i.reasons[0].slice(0, 58) + "…"
                          : i.reasons[0]
                        : `${i.reasons.length} notes`}
                    </summary>
                    {i.reasons.map((r, j) => (
                      <Text key={j} size="xs" mb={5}>
                        {r}
                      </Text>
                    ))}
                    <Text size="xs">
                      Parameters: {JSON.stringify(i.parameters)}
                    </Text>
                  </details>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
      {!visible.length && (
        <Text c="dimmed" py="md">
          No strategies meet these filters. Missing tests are not treated as
          passes.
        </Text>
      )}
      {catalog.errors.length > 0 && (
        <Alert color="yellow">
          {catalog.errors.length} configurations could not be verified and are
          excluded:{" "}
          {catalog.errors.map((e) => e.key + ": " + e.error).join("; ")}
        </Alert>
      )}
      <div className="collective-picker-foot">
        <Text size="sm">
          <b>{selected.length} selected</b>
          {hidden.length > 0 && (
            <Text span c="dimmed">
              {" "}
              · {hidden.length} hidden by these filters stay in the combination
            </Text>
          )}
        </Text>
        <Group gap={8} ml="auto">
          <Button size="xs" variant="subtle" color="gray" onClick={() => choose({})}>
            Clear combination
          </Button>
          <Button
            size="xs"
            variant="default"
            onClick={() =>
              choose(Object.fromEntries(visible.slice(0, 100).map((i) => [i.id, 1])))
            }
            disabled={!visible.length || visible.length > 100}
          >
            Apply visible strategies ({visible.length})
          </Button>
          <Button size="xs" onClick={() => setPickerOpen(false)}>
            Done
          </Button>
        </Group>
      </div>
    </div>
  );

  const titleByView: Record<ViewName, string> = {
    overview: "Overview",
    calendar: "Calendar",
    contributions: "Contributions",
    pause: "Pause & sizing",
  };
  return (
    <>
      <PageHeader
        crumb="Portfolio"
        title="Combined portfolio"
        actions={
          <>
            {catalog && (
              <span className="wb-stamp">
                Evidence refreshed{" "}
                {new Date(catalog.generated_at).toLocaleString(undefined, {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
            <Button
              variant="default"
              size="xs"
              leftSection={<IconRefresh size={14} />}
              loading={refreshing}
              onClick={() => void refreshEvidence()}
            >
              Refresh evidence
            </Button>
          </>
        }
        tabsLabel="Portfolio views"
        tabs={VIEWS.map((v) => ({
          label: titleByView[v],
          href: href("portfolio", v),
          active: current === v,
        }))}
      />
      {alerts}
      <div className={`wb-with-rail${collapsed ? " collapsed" : ""}`}>
        <div className="wb-content collective-dashboard">
          {error && (
            <Alert color="red" title="Collective evidence">
              {error}
            </Alert>
          )}
          {!catalog ? (
            loadingState
          ) : (
            <>
              <p className="wb-context">
                {selected.length} {selected.length === 1 ? "book" : "books"} ·{" "}
                {marketCount} {marketCount === 1 ? "market" : "markets"} ·{" "}
                {settings.start} to {settings.end} · {accountingLabel}, net of
                recorded costs
              </p>
              {computed.error && (
                <Alert color={loading ? "blue" : "yellow"} title="Combined book">
                  {computed.error}
                </Alert>
              )}
              {current === "overview" && overview}
              {current === "calendar" && calendarView}
              {current === "contributions" && contributionsView}
              {current === "pause" && pauseView}
              <Text size="xs" c="dimmed" mt="md">
                {catalog.definitions.pnl} Known gaps between test windows block
                aggregation. Zero on a covered day means no recorded change.
                Selections were made after inspecting these histories; this is
                not untouched portfolio validation. Histories are imported from
                verified full ledgers, with one baseline per strategy
                configuration; cost and execution variants are not added twice.
                Daily drawdown does not capture intraday extremes. Feasibility
                refers to the displayed historical checklist, not live approval.
                Configuration and selection are saved in this browser.
              </Text>
            </>
          )}
        </div>
        {!isMobile &&
          (collapsed ? (
            <aside className="wb-rail-strip" aria-label="Combination, collapsed">
              <ActionIcon
                variant="light"
                aria-label="Expand combination"
                onClick={() => setRailCollapsed(false)}
              >
                <IconChevronLeft size={15} />
              </ActionIcon>
              <span className="vertical">
                Combination · {selected.length}{" "}
                {selected.length === 1 ? "book" : "books"}
              </span>
            </aside>
          ) : (
            <aside className="wb-rail" aria-label="Combination">
              {railBody}
            </aside>
          ))}
      </div>
      {isMobile && (
        <div className="wb-rail-summary">
          <div>
            <b>
              Combination · {selected.length}{" "}
              {selected.length === 1 ? "book" : "books"}
            </b>
            <small>
              {money(capital)} ·{" "}
              {settings.basis === "marked" ? "marked daily" : "closed trades"}
            </small>
          </div>
          <Button variant="light" onClick={() => setSheetOpen(true)}>
            Edit
          </Button>
        </div>
      )}
      <Drawer
        opened={pickerOpen}
        onClose={() => setPickerOpen(false)}
        position="right"
        size={isMobile ? "100%" : 900}
        title={<span className="collective-drawer-title">Add strategies</span>}
      >
        {picker || loadingState}
      </Drawer>
      <Drawer
        opened={!!isMobile && sheetOpen}
        onClose={() => setSheetOpen(false)}
        position="bottom"
        size="auto"
        aria-label="Combination"
        styles={{ content: { height: "auto", maxHeight: "92vh", borderRadius: "16px 16px 0 0" } }}
        classNames={{ body: "collective-sheet" }}
      >
        {railBody}
        <Button fullWidth mt="md" onClick={() => setSheetOpen(false)}>
          Done
        </Button>
      </Drawer>
    </>
  );
}
