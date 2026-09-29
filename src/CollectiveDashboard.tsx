import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
  DEFAULT_PORTFOLIO_CAPITAL,
  commonWindow,
  PortfolioCoverageError,
  defaultPolicy,
  type CollectiveCatalog,
  type CollectiveSeries,
  type DailyPoint,
  type Dependence,
  type GatePolicy,
  type GateState,
} from "./collectiveModel";
import { PageHeader } from "./Shell";
import { StrategyConditionPanel } from "./StrategyConditionPanel";
import { href } from "./navigation";
import { strategyTitle } from "./strategyTitle";
import { collectiveProgress, stageColor } from "./researchProgress";
import "./collective.css";
import {
  defaultSizing,
  sizingSettings,
  type SizingSettings,
} from "./riskSizing";

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
  cluster: ["Clustering detected in sample", "teal"],
  alternate: ["Alternation detected in sample", "red"],
  none: ["No clustering detected", "gray"],
  insufficient: ["Under 30 trades", "gray"],
};
const verdictCopy: Record<Dependence["verdict"], [string, string]> = {
  cluster: [
    "Losses cluster in this book",
    "This sample shows outcome persistence. It is a reason to investigate a pause rule, not proof that the rule improves future results. Compare the replay below.",
  ],
  alternate: [
    "Outcomes alternate in this sample",
    "The sample shows alternation, which can make loss-triggered pauses skip recoveries. Check the actual replay and its skipped trades below.",
  ],
  none: [
    "No loss clustering detected in this sample",
    "This test did not detect clustering. That does not prove independence or tell us whether a pause rule will work on future data.",
  ],
  insufficient: [
    "Too few trades to judge this book",
    "Fewer than 30 trades are available, so the runs test is not informative.",
  ],
};
const VIEWS = ["overview", "calendar", "contributions", "pause"] as const;
type ViewName = (typeof VIEWS)[number];
type Settings = {
  capital: number;
  copies: Record<string, number>;
  start: string;
  end: string;
  basis: "marked" | "closed";
  policy: GatePolicy;
};
const SETTINGS_KEY = "quant-collective-v1";
const PREVIOUS_SETTINGS_KEY = "quant-collective-previous-v1";
function saved(key = SETTINGS_KEY): Settings | null {
  try {
    const value = JSON.parse(
      localStorage.getItem(key) || "null",
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
      capital: typeof value.capital === "number" && Number.isFinite(value.capital) && value.capital > 0
        ? value.capital : DEFAULT_PORTFOLIO_CAPITAL,
      basis: value.basis === "closed" ? "closed" : "marked",
      policy: {
        ...defaultPolicy,
        ...value.policy,
        ...(value.policy?.mode === "volatility" && !value.policy?.sizing
          ? { sizing: { ...defaultSizing, estimator: "legacy" } }
          : {}),
      },
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
          const strength = p
            ? 0.07 + 0.5 * Math.min(1, Math.abs(p.pnl) / scale)
            : 0;
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
  const [previousSettings, setPreviousSettings] = useState(() => saved(PREVIOUS_SETTINGS_KEY));
  const latestLinkApplied = useRef(false);
  const initialized = useRef(Boolean(initial));
  const [catalog, setCatalog] = useState<CollectiveCatalog | null>(null),
    [error, setError] = useState("");
  const [settings, setSettings] = useState<Settings>(
    initial || {
      capital: DEFAULT_PORTFOLIO_CAPITAL,
      copies: {},
      start: "2024-01-01",
      end: "2026-08-31",
      basis: "marked",
      policy: {
        ...defaultPolicy,
        mode: "fixed",
        volCap: 1,
        sizing: { ...defaultSizing },
      },
    },
  );
  const [histories, setHistories] = useState<CollectiveSeries[]>([]),
    [loading, setLoading] = useState(false),
    [refreshing, setRefreshing] = useState(false);
  const [manualBook, setManualBook] = useState<string | null>(null);
  const [manualTime, setManualTime] = useState("");
  const [manualAction, setManualAction] = useState("pause");
  const [manualReason, setManualReason] = useState("");
  const [manualError, setManualError] = useState("");
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
        setCatalog({
          ...d,
          items: d.items.map((item) => ({ ...item, name: strategyTitle(item.name) })),
        });
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
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
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
    setHistories([]);
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
  const latestEsNq = useMemo(
    () => (catalog?.items || []).filter((item) =>
      item.working && item.latest_replay && (item.symbol === "ES" || item.symbol === "NQ"),
    ),
    [catalog],
  );
  const latestEsNqWindow = useMemo(() => commonWindow(latestEsNq), [latestEsNq]);
  const latestEsNqAvailable = latestEsNq.length >= 2 &&
    latestEsNq.some((item) => item.symbol === "ES") &&
    latestEsNq.some((item) => item.symbol === "NQ") &&
    Boolean(latestEsNqWindow.end);
  const showingLatestEsNq = latestEsNqAvailable &&
    selected.length === latestEsNq.length &&
    latestEsNq.every((item) => settings.copies[item.id] > 0) &&
    settings.end === latestEsNqWindow.end;
  const viewLatestEsNq = useCallback(() => {
    if (!latestEsNqAvailable) return;
    if (!previousSettings) {
      setPreviousSettings(settings);
      try {
        localStorage.setItem(PREVIOUS_SETTINGS_KEY, JSON.stringify(settings));
      } catch {
        /* The restore action still works in this session. */
      }
    }
    const start = settings.start >= latestEsNqWindow.start &&
      settings.start <= latestEsNqWindow.end
      ? settings.start : latestEsNqWindow.start;
    setLoading(true);
    setSettings((current) => ({
      ...current,
      copies: Object.fromEntries(latestEsNq.map((item) => [item.id, 1])),
      start,
      end: latestEsNqWindow.end,
    }));
    setMonth(latestEsNqWindow.end.slice(0, 7));
    setDay("");
  }, [latestEsNqAvailable, previousSettings, settings, latestEsNqWindow.start, latestEsNqWindow.end, latestEsNq]);
  function restorePreviousCombination() {
    if (!previousSettings) return;
    setLoading(true);
    setSettings(previousSettings);
    setMonth(previousSettings.end.slice(0, 7));
    setDay("");
    setPreviousSettings(null);
    try {
      localStorage.removeItem(PREVIOUS_SETTINGS_KEY);
    } catch {
      /* The restored settings still work in this session. */
    }
  }
  useEffect(() => {
    if (!catalog || latestLinkApplied.current) return;
    if (new URLSearchParams(window.location.search).get("portfolio") !== "latest-es-nq") return;
    if (!latestEsNqAvailable) return;
    latestLinkApplied.current = true;
    viewLatestEsNq();
    const url = new URL(window.location.href);
    url.searchParams.delete("portfolio");
    history.replaceState(history.state, "", url.pathname + url.search + url.hash);
  }, [catalog, latestEsNqAvailable, viewLatestEsNq]);
  const visible = useMemo(
    () =>
      (catalog?.items || []).filter(
        (i) =>
          (filter === "all" || (filter === "working" ? i.working
            : filter === "feasible" ? i.feasible
            : !i.working && !i.benchmark)) &&
          (!markets.length || markets.includes(i.symbol)) &&
          (timeframe === "all" || i.timeframe === timeframe) &&
          `${i.name} ${i.symbol} ${i.timeframe} ${i.session} ${i.source}`
            .toLowerCase()
            .includes(search.toLowerCase()),
      ).sort((a, b) => Number(a.benchmark) - Number(b.benchmark) || collectiveProgress(b).stage - collectiveProgress(a).stage || a.name.localeCompare(b.name) || a.symbol.localeCompare(b.symbol)),
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
          settings.capital,
        ),
        error: "",
        coverageGap: false,
      };
    } catch (e) {
      return { value: null, error: String(e instanceof Error ? e.message : e), coverageGap: e instanceof PortfolioCoverageError };
    }
  }, [selected, histories, settings]);
  const result = computed.value,
    hidden = selected.filter((i) => !visible.some((v) => v.id === i.id));
  const testedWindow = useMemo(() => commonWindow(selected.map((item) =>
    histories.find((history) => history.id === item.id) || item,
  )), [selected, histories]);
  const selectedDay = result?.points.find((p) => p.date === day);
  const capital = settings.capital;
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
    const w = testedWindow;
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
          "date,pnl,always_on_pnl,cumulative_pnl,always_on_cumulative_pnl,equity,drawdown,closed_trades,starting_capital",
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
              result.capital,
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
          version: 2,
          capital_model: "shared",
          catalog_at: catalog?.generated_at,
          replay_version: 4,
          ...settings,
          capital,
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
                benchmarks: result.benchmarks,
                execution: result.execution,
                correlations: result.correlations,
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
  const volatility = ["volatility", "portfolio", "fixed"].includes(
    settings.policy.mode,
  );

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
                <div className="wb-book-meta">
                  Tested: {i.coverage.map((span) => `${span.start} to ${span.end}`).join("; ") || "No covered dates"}
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
        <NumberInput
          label="Starting capital (USD)"
          description="One balance shared across all selected strategies."
          size="xs"
          min={1}
          decimalScale={2}
          allowNegative={false}
          value={capital}
          onChange={(value) => setSettings((s) => ({ ...s, capital: Number(value) }))}
        />
      </div>
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
          disabled={!testedWindow.start}
        >
          Use common tested window
        </button>
        {selected.length > 0 && (
          <Text size="xs" c="dimmed">
            {testedWindow.start
              ? `Common continuous window: ${testedWindow.start} to ${testedWindow.end}.`
              : "These configurations have no common tested window. Remove a configuration or choose different histories."}
          </Text>
        )}
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
        Copies multiply recorded P&L and exposure. Starting capital stays fixed
        when adding strategies or copies; shared margin and liquidation are not simulated.
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
      <h2>
        {selected.length ? "Combined book unavailable" : "No books selected"}
      </h2>
      <p className="wb-card-sub">
        {selected.length
          ? computed.coverageGap
            ? testedWindow.start
              ? `All selected books cover ${testedWindow.start} to ${testedWindow.end}. Apply this continuous tested window to calculate the combined book.`
              : "These configurations have no common tested window. Remove a configuration or choose different histories."
            : "Review the message above, then adjust the dates, calibration, or replay settings."
          : "Add tested strategies to see their combined P&L, calendar and contributions."}
      </p>
      {computed.coverageGap && (
        <Button mt="md" variant="light" onClick={testedWindow.start ? useCommon : () => setPickerOpen(true)}>
          {testedWindow.start ? "Apply common tested window" : "Review configurations"}
        </Button>
      )}
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
            {pct(result.returnOnCapital)} on total portfolio capital
          </span>
        </div>
        <div className="wb-kpi">
          <span className="wb-kpi-label">Maximum drawdown</span>
          <span className="wb-kpi-value">
            {money(result.maxDrawdownDollars)}
          </span>
          <span className="wb-kpi-note">
            {pct(Math.abs(result.maxDrawdown))} ·{" "}
            {settings.basis === "marked"
              ? "daily closes"
              : "closed trades only"}
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
          Total portfolio capital <b>{money(result.capital)}</b>
        </span>
        {settings.policy.enabled && (
          <span>
            {volatility
              ? "Effect of volatility scaling"
              : "Effect of pause rule"}{" "}
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

  const dayIndex =
    result && day ? result.points.findIndex((p) => p.date === day) : -1;
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
            <div
              className="wb-day-total"
              style={{ color: tone(selectedDay.pnl) }}
            >
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
                        <Table.Td
                          ta="right"
                          c={v ? tone(v) : "dimmed"}
                          className="mono"
                        >
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
        <Table miw={1040} data-testid="strategy-contributions" highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Strategy</Table.Th>
              <Table.Th>Chart</Table.Th>
              <Table.Th ta="right">Net P&L</Table.Th>
              <Table.Th ta="right">Maximum drawdown</Table.Th>
              <Table.Th ta="right">Return contribution</Table.Th>
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
                    {c.name}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{c.symbol} · {c.timeframe}</Text>
                  <Text size="xs" c="dimmed">
                    {c.session}
                  </Text>
                </Table.Td>
                <Table.Td ta="right" c={tone(c.pnl)} className="mono">
                  {money(c.pnl)}
                </Table.Td>
                <Table.Td ta="right" c={c.maxDrawdownDollars > 0 ? "red" : undefined} className="mono">
                  {money(c.maxDrawdownDollars)}
                </Table.Td>
                <Table.Td ta="right" c={tone(c.pnl)} className="mono">
                  {pct(c.pnl / result.capital)}
                </Table.Td>
                <Table.Td ta="right" className="mono">
                  {money(c.baseline)}
                </Table.Td>
                <Table.Td ta="right">{c.trades}</Table.Td>
                <Table.Td ta="right">{c.skipped}</Table.Td>
                <Table.Td>
                  <Badge
                    color={stateColor[c.state]}
                    radius="xs"
                    variant="light"
                  >
                    {settings.policy.enabled
                      ? c.state === "Active"
                        ? "Enabled"
                        : c.state
                      : "Always on"}
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
      <Text size="xs" c="dimmed" mt="sm">
        Maximum drawdown is each strategy's largest peak-to-trough dollar loss
        over the selected dates, using {accountingLabel}, selected copies and
        active replay settings. Individual drawdowns do not add up to portfolio drawdown.
      </Text>
    </section>
  ) : (
    emptyState
  );

  const numberField = (
    label: string,
    value: number,
    set: (n: number) => void,
    props: {
      min?: number;
      max?: number;
      step?: number;
      decimal?: boolean;
    } = {},
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
  const sizing = sizingSettings(p);
  function changeSizing(next: Partial<SizingSettings>) {
    policy({ sizing: { ...sizing, ...next } });
  }
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
            label="Replay mode"
            size="xs"
            value={p.mode}
            onChange={(v) =>
              policy({
                mode: (v || "fixed") as GatePolicy["mode"],
                sizing: {
                  ...sizing,
                  estimator:
                    v === "volatility" && sizing.estimator === "legacy"
                      ? "legacy"
                      : sizing.estimator === "legacy"
                        ? "ewma"
                        : sizing.estimator,
                },
              })
            }
            data={[
              { value: "fixed", label: "Constant size (no pause)" },
              {
                value: "portfolio",
                label: "Portfolio-aware volatility sizing",
              },
              {
                value: "deterioration",
                label: "Sustained deterioration / manual review",
              },
              { value: "rolling", label: "Rolling closed-trade losses" },
              { value: "manual", label: "Manual pause / resume schedule" },
              { value: "streak", label: "Consecutive losing trades" },
              { value: "drawdown", label: "Shadow equity drawdown" },
              {
                value: "volatility",
                label: "Scale size by realized volatility (no pause)",
              },
            ]}
          />
          {p.mode !== "manual" && p.mode !== "deterioration" && (
            <div className="wb-policy-group">
              <h3>{volatility ? "Size by" : "Pause when"}</h3>
              <SimpleGrid cols={2} spacing={8}>
                {p.mode === "fixed" ? (
                  numberField(
                    "Constant size multiple",
                    sizing.fixedSize,
                    (n) =>
                      changeSizing({ fixedSize: Math.max(0, Math.min(4, n)) }),
                    { min: 0, max: 4, step: 0.25, decimal: true },
                  )
                ) : p.mode === "rolling" ? (
                  <>
                    {numberField(
                      "Lookback trades",
                      p.lookback,
                      (n) => policy({ lookback: Math.max(2, n || 2) }),
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
                  numberField(
                    "Consecutive losses to pause",
                    p.streak,
                    (n) => policy({ streak: Math.max(1, n || 1) }),
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
                      "Volatility lookback (observations)",
                      p.volLookback,
                      (n) =>
                        policy({
                          volLookback: Math.min(250, Math.max(10, n || 10)),
                        }),
                      { min: 10, max: 250 },
                    )}
                    {numberField(
                      "Maximum size multiple",
                      p.volCap,
                      (n) =>
                        policy({ volCap: Math.min(4, Math.max(0.25, n || 1)) }),
                      { min: 0.25, max: 4, step: 0.25, decimal: true },
                    )}
                  </>
                )}
              </SimpleGrid>
            </div>
          )}
          {!volatility && p.mode !== "manual" && p.mode !== "deterioration" && (
            <div className="wb-policy-group">
              <h3>Resume after</h3>
              <SimpleGrid cols={2} spacing={8}>
                {numberField(
                  "Cooldown (calendar days)",
                  p.cooldown,
                  (n) => policy({ cooldown: Math.max(1, n || 1) }),
                  { min: 1, max: 365 },
                )}
                {numberField(
                  "Shadow recovery trades",
                  p.recovery,
                  (n) => policy({ recovery: Math.max(1, n || 1) }),
                  { min: 1, max: 100 },
                )}
              </SimpleGrid>
            </div>
          )}
          {(p.mode === "volatility" ||
            p.mode === "portfolio" ||
            p.mode === "deterioration" ||
            sizing.portfolioVolLimit > 0 ||
            sizing.equityVolLimit > 0 ||
            sizing.lossLimit > 0) && (
            <div className="wb-policy-group">
              <h3>Frozen risk calibration</h3>
              <TextInput
                size="xs"
                type="date"
                label="Calibration end (UTC)"
                value={sizing.calibrationEnd}
                onChange={(e) =>
                  changeSizing({ calibrationEnd: e.currentTarget.value })
                }
              />
              <Select
                size="xs"
                label="Volatility estimator"
                value={p.sizing ? sizing.estimator : "legacy"}
                onChange={(value) =>
                  changeSizing({
                    estimator: value as SizingSettings["estimator"],
                  })
                }
                data={[
                  {
                    value: "ewma",
                    label: "Exponentially weighted observed sessions",
                  },
                  {
                    value: "session",
                    label: "Observed sessions, including zero P&L",
                  },
                  ...(p.mode === "volatility"
                    ? [
                        {
                          value: "legacy",
                          label: "Legacy nonzero days / chart-window target",
                        },
                      ]
                    : []),
                ]}
              />
              <SimpleGrid cols={2} spacing={8} mt="xs">
                {numberField(
                  "Volatility floor / target",
                  sizing.floorFraction,
                  (n) => changeSizing({ floorFraction: n }),
                  { min: 0.01, max: 1, step: 0.1, decimal: true },
                )}
                {numberField(
                  "Max size change per entry",
                  sizing.maxChange,
                  (n) => changeSizing({ maxChange: n }),
                  { min: 0.01, max: 4, step: 0.05, decimal: true },
                )}
              </SimpleGrid>
              <Text size="xs" c="dimmed">
                {p.mode === "volatility" &&
                (!p.sizing || sizing.estimator === "legacy")
                  ? "Legacy sizing uses nonzero days and recalibrates from the chart start. The frozen date, floor and step controls do not change legacy book sizing; portfolio limits still use the frozen calibration. Choose a session estimator for the revised sizing method."
                  : "The calibration date stays fixed when chart dates change. Observed zero-P&L sessions count; missing dates do not. These dates have already been researched."}
              </Text>
            </div>
          )}
          {p.mode === "deterioration" && (
            <div className="wb-policy-group">
              <h3>Review trigger</h3>
              {numberField(
                "Monitoring trades",
                sizing.monitorWindow,
                (n) => changeSizing({ monitorWindow: n }),
                { min: 20, max: 250 },
              )}
              {numberField(
                "Consecutive confirmations",
                sizing.monitorConfirm,
                (n) => changeSizing({ monitorConfirm: n }),
                { min: 2, max: 50 },
              )}
              {numberField(
                "Normalized shortfall threshold",
                sizing.monitorThreshold,
                (n) => changeSizing({ monitorThreshold: n }),
                { min: 1, max: 10, step: 0.5, decimal: true },
              )}
              <Text size="xs" c="dimmed">
                Requires 50 calibration trades. A sustained shortfall against
                the frozen normalized mean pauses entries until a dated manual
                resume below. The threshold is a research setting, not a
                statistical confidence level.
              </Text>
            </div>
          )}
          <div className="wb-policy-group">
            <h3>Portfolio limits</h3>
            {numberField(
              "Portfolio daily risk cap ($; 0 = auto/off)",
              sizing.portfolioVolLimit,
              (n) => changeSizing({ portfolioVolLimit: n }),
              { min: 0 },
            )}
            {numberField(
              "Equity-index daily risk cap ($; 0 = off)",
              sizing.equityVolLimit,
              (n) => changeSizing({ equityVolLimit: n }),
              { min: 0 },
            )}
            {numberField(
              "Portfolio closed-loss limit ($; 0 = off)",
              sizing.lossLimit,
              (n) => changeSizing({ lossLimit: n }),
              { min: 0 },
            )}
            <Text size="xs" c="dimmed">
              Portfolio mode derives its risk cap from frozen calibration when
              zero. Other modes leave it off. The equity cap groups ES, NQ, YM,
              RTY and their micros. A closed-loss breach blocks new entries for
              the rest of the replay; existing positions retain their exits.
            </Text>
          </div>
          <div className="wb-policy-group">
            <h3>Contract feasibility</h3>
            <Switch
              size="xs"
              label="Round down to recorded whole contracts"
              checked={sizing.wholeContracts}
              onChange={(e) =>
                changeSizing({ wholeContracts: e.currentTarget.checked })
              }
            />
            {sizing.wholeContracts && (
              <>
                {numberField(
                  "Assumed margin per contract ($)",
                  sizing.marginPerContract,
                  (n) => changeSizing({ marginPerContract: n }),
                  { min: 0 },
                )}
                {numberField(
                  "Shared margin budget ($; 0 = off)",
                  sizing.marginBudget,
                  (n) => changeSizing({ marginBudget: n }),
                  { min: 0 },
                )}
                <Text size="xs" c="dimmed">
                  Uses a user-supplied uniform margin assumption. One recorded
                  contract at 75% rounds to zero. Micro contracts require their
                  own data, fees and rerun.
                </Text>
              </>
            )}
          </div>
          <Text size="xs" c="dimmed">
            {volatility
              ? "Sizing is fixed at entry; pause recovery rules do not apply."
              : p.mode === "manual" || p.mode === "deterioration"
                ? "Schedule entry pauses and resumes below. A pause stays in effect until a manual resume."
                : "Recovery counts only completed shadow trades entered after the pause. The cooldown and positive recovery must both pass. Existing positions keep their exits."}
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
        <StrategyConditionPanel
          catalog={catalog}
          items={selected}
          histories={histories}
          end={settings.end}
          enabled={p.enabled}
          permissions={result?.components || []}
        />
        {result && (
          <section className="wb-card" data-testid="sizing-benchmarks">
            <div className="wb-card-head">
              <h2>Fixed-size benchmarks</h2>
              <Button
                size="compact-sm"
                variant="default"
                onClick={() =>
                  download(
                    "sizing-comparison.csv",
                    [
                      "variant,net_pnl,max_drawdown,worst_day,recovery_factor",
                      ...[
                        { label: "Selected policy", ...result.comparison },
                        ...result.benchmarks.map((b) => ({
                          label: `Constant ${b.size * 100}%`,
                          ...b,
                        })),
                      ].map((r) =>
                        [
                          r.label,
                          r.net,
                          r.drawdown,
                          r.worstDay,
                          r.recovery ?? "",
                        ]
                          .map(csvCell)
                          .join(","),
                      ),
                    ].join("\n"),
                  )
                }
              >
                Export comparison
              </Button>
            </div>
            <Text size="sm" c="dimmed">
              Same dates, books and {accountingLabel}. Constant benchmarks scale
              recorded net P&amp;L and costs proportionally, with fractional
              exposure and no pause or portfolio cap. Capital is held fixed.
            </Text>
            <ScrollArea>
              <Table miw={610}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Variant</Table.Th>
                    <Table.Th>Net P&amp;L</Table.Th>
                    <Table.Th>Max drawdown</Table.Th>
                    <Table.Th>Worst day</Table.Th>
                    <Table.Th>Recovery</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {[
                    { label: "Selected policy", ...result.comparison },
                    ...result.benchmarks.map((b) => ({
                      label: `Constant ${b.size * 100}%`,
                      ...b,
                    })),
                  ].map((row) => (
                    <Table.Tr key={row.label}>
                      <Table.Td>{row.label}</Table.Td>
                      <Table.Td>{money(row.net)}</Table.Td>
                      <Table.Td>{money(row.drawdown)}</Table.Td>
                      <Table.Td>{money(row.worstDay)}</Table.Td>
                      <Table.Td>{row.recovery?.toFixed(2) ?? "—"}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          </section>
        )}
        {p.enabled && result && (
          <section className="wb-card" data-testid="sizing-validation">
            <h2>Exposure and execution checks</h2>
            <Button
              size="compact-sm"
              variant="default"
              mb="sm"
              onClick={() =>
                download(
                  "entry-sizing.csv",
                  [
                    "configuration_id,entry,accepted,size_multiple,represented_contracts",
                    ...result.sizingDecisions.map((d) =>
                      [d.id, d.entry, d.accepted, d.multiple, d.contracts ?? ""]
                        .map(csvCell)
                        .join(","),
                    ),
                  ].join("\n"),
                )
              }
            >
              Export entry sizes
            </Button>
            <Text size="sm">
              Recorded contract quantities:{" "}
              {result.execution.quantitiesAvailable
                ? "available"
                : "missing — refresh evidence; unsupported ledgers remain unavailable"}
              . Whole-contract rounding:{" "}
              {result.execution.wholeContracts ? "on" : "off"}. Shared margin
              assumption:{" "}
              {result.execution.marginConfigured
                ? "configured"
                : "not configured"}
              .
            </Text>
            <Text size="sm" c="dimmed" mt="xs">
              Risk caps use lagged daily book P&amp;L and concurrent recorded
              entries. They are an exposure estimate, not a stop-loss budget or
              an intraday open-loss limit. Stateful execution, per-trade stop
              risk, changing margin and micro-contract fills still require a
              full strategy rerun.
            </Text>
            <h3>Book correlations through {sizing.calibrationEnd}</h3>
            <ScrollArea h={210}>
              <Table miw={580}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Books</Table.Th>
                    <Table.Th>Shared observations</Table.Th>
                    <Table.Th>Correlation</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {result.correlations.map((row) => (
                    <Table.Tr key={row.a + row.b}>
                      <Table.Td>
                        {[row.a, row.b]
                          .map((id) => {
                            const item = selected.find((i) => i.id === id);
                            return `${item?.name} / ${item?.symbol}`;
                          })
                          .join(" ↔ ")}
                      </Table.Td>
                      <Table.Td>{row.observations}</Table.Td>
                      <Table.Td>
                        {row.correlation?.toFixed(3) ??
                          "Insufficient variation / history"}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
            <Text size="xs" c="dimmed">
              Portfolio caps use trailing correlations available before entry,
              shrink them toward +1 and give no negative-correlation hedge
              credit. Existing positions are not resized if risk later rises.
            </Text>
          </section>
        )}
        {p.enabled && (p.mode === "manual" || p.mode === "deterioration") && (
          <section className="wb-card" data-testid="manual-schedule">
            <h2>Manual pause / resume</h2>
            <p className="wb-card-sub">
              Apply a dated decision to one selected book. The timestamp is UTC;
              entries at or after it follow the decision. Existing positions
              keep their recorded exits. This schedule replays history and does
              not control live orders.
            </p>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <Select
                label="Strategy to control"
                value={manualBook}
                onChange={setManualBook}
                data={selected.map((i) => ({
                  value: i.id,
                  label: `${i.name} / ${i.symbol} / ${i.timeframe}`,
                }))}
                searchable
              />
              <TextInput
                label="Effective time (UTC)"
                type="datetime-local"
                value={manualTime}
                onChange={(e) => setManualTime(e.currentTarget.value)}
              />
              <Select
                label="Manual action"
                value={manualAction}
                onChange={(v) => setManualAction(v || "pause")}
                data={[
                  { value: "pause", label: "Pause new entries" },
                  { value: "resume", label: "Resume new entries" },
                ]}
              />
              <TextInput
                label="Decision reason"
                value={manualReason}
                onChange={(e) => setManualReason(e.currentTarget.value)}
              />
            </SimpleGrid>
            {manualError && (
              <Alert color="red" mt="sm">
                {manualError}
              </Alert>
            )}
            <Button
              mt="sm"
              onClick={() => {
                const time = Date.parse(manualTime + "Z");
                if (
                  !manualBook ||
                  !selected.some((i) => i.id === manualBook) ||
                  !Number.isFinite(time) ||
                  !manualReason.trim()
                ) {
                  setManualError(
                    "Choose a selected strategy, UTC time and decision reason.",
                  );
                  return;
                }
                const timestamp = new Date(time).toISOString();
                const book = selected.find((i) => i.id === manualBook)!;
                if (
                  timestamp.slice(0, 10) < book.start ||
                  timestamp.slice(0, 10) > book.end
                ) {
                  setManualError(
                    "Choose a time within this strategy's tested history.",
                  );
                  return;
                }
                const current = p.manual?.[manualBook] || [];
                if (current.some((d) => Date.parse(d.timestamp) === time)) {
                  setManualError(
                    "A decision already exists at that time. Remove it before replacing it.",
                  );
                  return;
                }
                policy({
                  manual: {
                    ...p.manual,
                    [manualBook]: [
                      ...current,
                      {
                        timestamp,
                        action: manualAction as "pause" | "resume",
                        reason: manualReason.trim(),
                      },
                    ].sort((a, b) => a.timestamp.localeCompare(b.timestamp)),
                  },
                });
                setManualError("");
                setManualReason("");
              }}
            >
              Add decision
            </Button>
            <ScrollArea mt="sm">
              <Table miw={640}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Effective UTC</Table.Th>
                    <Table.Th>Strategy</Table.Th>
                    <Table.Th>Action / reason</Table.Th>
                    <Table.Th>Change</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {selected.flatMap((i) =>
                    (p.manual?.[i.id] || []).map((d) => (
                      <Table.Tr key={i.id + d.timestamp}>
                        <Table.Td>
                          {d.timestamp.replace("T", " ").slice(0, 16)}
                        </Table.Td>
                        <Table.Td>
                          {i.name} / {i.symbol} / {i.timeframe}
                        </Table.Td>
                        <Table.Td>
                          {d.action}: {d.reason}
                        </Table.Td>
                        <Table.Td>
                          <Button
                            size="compact-xs"
                            variant="subtle"
                            aria-label={`Remove ${d.action} ${i.id} ${d.timestamp}`}
                            onClick={() =>
                              policy({
                                manual: {
                                  ...p.manual,
                                  [i.id]: (p.manual?.[i.id] || []).filter(
                                    (x) => x.timestamp !== d.timestamp,
                                  ),
                                },
                              })
                            }
                          >
                            Remove
                          </Button>
                        </Table.Td>
                      </Table.Tr>
                    )),
                  )}
                </Table.Tbody>
              </Table>
            </ScrollArea>
            <Text size="xs" c="dimmed" mt="xs">
              Decisions persist with this browser's combination and are included
              in its JSON export. Turning replay off restores the always-on
              history; it keeps your schedule.
            </Text>
          </section>
        )}
        {p.enabled && result && !volatility && (
          <section className="wb-card" data-testid="gate-status">
            <h2>Entry permission at {settings.end} (UTC)</h2>
            <ScrollArea>
              <Table miw={700}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Strategy</Table.Th>
                    <Table.Th>Status / reason</Table.Th>
                    <Table.Th>Cooldown ends (UTC)</Table.Th>
                    <Table.Th>Recovery</Table.Th>
                    <Table.Th>Skipped P&amp;L</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {result.components.map((c) => (
                    <Table.Tr key={c.id}>
                      <Table.Td>
                        {c.name} / {c.symbol} /{" "}
                        {selected.find((i) => i.id === c.id)?.timeframe}
                      </Table.Td>
                      <Table.Td>
                        <Badge color={stateColor[c.state]}>
                          {c.state === "Active" ? "Enabled" : c.state}
                        </Badge>
                        <Text size="xs">{c.status?.reason}</Text>
                      </Table.Td>
                      <Table.Td>
                        {c.status?.cooldownUntil
                          ?.replace("T", " ")
                          .slice(0, 16) || "—"}
                      </Table.Td>
                      <Table.Td>
                        {c.state === "Paused" && (c.status?.required || 0) > 0
                          ? `${c.status?.recoveryTrades}/${c.status?.required} trades; ${money(c.status?.recoveryPnl || 0)}`
                          : "—"}
                      </Table.Td>
                      <Table.Td>
                        {money(c.baseline - c.pnl)}
                        <Text size="xs">
                          {c.skipped} trades; positive = missed profit
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          </section>
        )}
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
            {p.mode !== "manual" && (
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
                      ? "Clustering is a reason to investigate those books, not proof that a pause improves future results."
                      : "No clustering was detected in these samples. This does not prove independence; judge the replay and its skipped trades below."}
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
            )}
            <div className="wb-compare" data-testid="policy-comparison">
              <div>
                <span>
                  {volatility
                    ? p.mode === "fixed"
                      ? "With constant sizing"
                      : "With volatility scaling"
                    : p.mode === "manual"
                      ? "With manual schedule"
                      : "With pause rule"}
                </span>
                <strong className={signed(result.net)}>
                  {money(result.net)}
                </strong>
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
                        {n > 1
                          ? `${n} ${s === "Active" ? "Enabled" : s}`
                          : s === "Active"
                            ? "Enabled"
                            : s}
                      </Badge>
                    ))}
                  </span>
                )}
              </div>
            </div>
            {p.mode !== "manual" && (
              <section className="wb-card" data-testid="dependence-check">
                <h2>Do losses cluster?</h2>
                <p className="wb-card-sub">
                  Runs test on win/loss signs, using trades closed before the
                  window when at least 30 exist, otherwise the window itself. z
                  below −1.96 indicates clustering in the sample; above +1.96
                  indicates alternation. These diagnostics do not establish a
                  profitable pause rule or predict future outcomes.
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
                            {Number.isFinite(d.runsZ)
                              ? d.runsZ.toFixed(2)
                              : "—"}
                          </Table.Td>
                          <Table.Td ta="right">
                            {Number.isFinite(d.afterLoss)
                              ? money(d.afterLoss)
                              : "—"}
                          </Table.Td>
                          <Table.Td ta="right">
                            {Number.isFinite(d.afterWin)
                              ? money(d.afterWin)
                              : "—"}
                          </Table.Td>
                          <Table.Td>
                            <Badge
                              color={verdicts[d.verdict][1]}
                              radius="xs"
                              variant="light"
                            >
                              {verdicts[d.verdict][0]}
                            </Badge>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </ScrollArea>
              </section>
            )}
            <Alert color="yellow">
              {volatility
                ? "Exploratory sizing replay. Sizes are fixed at entry using the selected estimator and calibration, or a constant multiple. Contract rounding and margin caps apply only when explicitly configured. Strategy state and intraday open risk are not rerun. "
                : p.mode === "manual"
                  ? "Manual decisions are retrospective user choices, not an out-of-sample strategy test. Existing positions keep their original exits. Strategy state, sizing and margin are not rerun. "
                  : "Exploratory entry-filter replay. Decisions use only trades closed before entry; recovery observes hypothetical trades while paused. Existing positions keep their original exits. Strategy state, sizing and margin are not rerun; skipped entries can change them in a full simulation. "}
              P&amp;L is realized on exit dates, so open risk is not shown.
              Parameters are not optimized and no live orders are controlled.
            </Alert>
            <section className="wb-card">
              <div className="wb-card-head">
                <h2>
                  {volatility
                    ? "Size band changes"
                    : "Pause / resume decisions"}{" "}
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
                        "timestamp,configuration_id,strategy,state,reason",
                        ...result.events.map((e) =>
                          [e.timestamp, e.id, e.name, e.state, e.reason]
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
                        <Table.Td
                          className="mono"
                          style={{ whiteSpace: "nowrap" }}
                        >
                          {e.timestamp.replace("T", " ").slice(0, 16)}
                        </Table.Td>
                        <Table.Td>{e.name}</Table.Td>
                        <Table.Td>
                          <Badge
                            color={stateColor[e.state]}
                            radius="xs"
                            variant="light"
                          >
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
  const counts = {
    working: catalog?.items.filter(i => i.working).length || 0,
    feasible: catalog?.items.filter(i => i.feasible).length || 0,
    backtested: catalog?.items.filter(i => !i.working && !i.benchmark).length || 0,
  };
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
          { value: "working", label: `Evaluation passed · ${counts.working}` },
          { value: "feasible", label: `Robustness checked · ${counts.feasible}` },
          { value: "all", label: `All tested · ${catalog.items.length}` },
          { value: "backtested", label: `Backtested only · ${counts.backtested}` },
        ]}
      />
      <Text size="xs" c="dimmed">Stages apply to each market and configuration. Recorded findings remain in Review notes.</Text>
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
            {[...new Set(catalog.items.map((i) => i.symbol))]
              .sort()
              .map((s) => (
                <Chip key={s} value={s} size="sm">
                  {s}
                </Chip>
              ))}
          </Chip.Group>
        </Group>
        <Group
          gap={8}
          align="end"
          wrap="nowrap"
          className="collective-filter-fields"
        >
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
      <ScrollArea
        className="collective-picker-table"
        type="always"
        viewportProps={{
          tabIndex: 0,
          role: "region",
          "aria-label": "Available strategy configurations",
        }}
      >
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
                    className="collective-milestone-badge"
                    radius="xs"
                    variant="light"
                    color={i.benchmark ? "gray" : stageColor(collectiveProgress(i).stage)}
                  >
                    {collectiveProgress(i).label}
                  </Badge>
                  <Text size="xs" c="dimmed">
                    {i.source}
                  </Text>
                </Table.Td>
                <Table.Td data-label="Test coverage">
                  <Text
                    size="xs"
                    className="mono"
                    style={{ whiteSpace: "nowrap" }}
                  >
                    {i.start} → {i.end}
                  </Text>
                </Table.Td>
                <Table.Td data-label="2024 onward" ta="right" c={tone(i.recent_pnl)} className="mono">
                  {i.end < "2024" ? "Not tested" : money(i.recent_pnl)}
                </Table.Td>
                <Table.Td maw={280}>
                  <details>
                    <summary>
                      {i.reasons[0] ? i.reasons[0].length > 60 ? i.reasons[0].slice(0, 58) + "…" : i.reasons[0] : `${i.reasons.length} notes`}
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
          <Button
            size="xs"
            variant="subtle"
            color="gray"
            onClick={() => choose({})}
          >
            Clear combination
          </Button>
          <Button
            size="xs"
            variant="default"
            onClick={() =>
              choose(
                Object.fromEntries(visible.slice(0, 100).map((i) => [i.id, 1])),
              )
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
              {latestEsNqAvailable && (!showingLatestEsNq || previousSettings) && (
                <Alert color="blue" title={showingLatestEsNq ? "Viewing refreshed ES/NQ history" : "September ES/NQ history is available"} mb="md">
                  <Group justify="space-between" align="center" gap="sm">
                    <Text size="sm">
                      {latestEsNq.length} ES/NQ books share a tested window through {latestEsNqWindow.end}.
                      {!showingLatestEsNq && " Open that combination to see its September calendar."}
                    </Text>
                    <Group gap="xs">
                      {!showingLatestEsNq && (
                        <Button size="xs" onClick={viewLatestEsNq}>View latest ES/NQ</Button>
                      )}
                      {previousSettings && (
                        <Button size="xs" variant="default" onClick={restorePreviousCombination}>
                          Restore previous combination
                        </Button>
                      )}
                    </Group>
                  </Group>
                </Alert>
              )}
              {computed.error && (
                <Alert
                  color={loading ? "blue" : "yellow"}
                  title="Combined book"
                >
                  {computed.error}
                </Alert>
              )}
              {current === "overview" && overview}
              {result?.depleted && (
                <Alert color="orange" title="Starting capital exhausted in this history" mt="md">
                  Combined equity reaches zero or below at this exposure. The replay
                  continues through those losses; it does not simulate margin liquidation.
                </Alert>
              )}
              {current === "calendar" && calendarView}
              {current === "contributions" && contributionsView}
              {current === "pause" && pauseView}
              <Text size="xs" c="dimmed" mt="md">
                {p.enabled
                  ? "UTC closed-trade P&L, net of proportionally scaled recorded costs. Independent books with the selected entry, sizing and optional margin-assumption controls; no position netting or stateful execution rerun."
                  : catalog.definitions.pnl}{" "}
                Known gaps between test windows block aggregation. Zero on a
                covered day means no recorded change. Selections were made after
                inspecting these histories; this is not untouched portfolio
                validation. Histories are imported from verified full ledgers,
                with one baseline per strategy configuration; cost and execution
                variants are not added twice. Daily drawdown does not capture
                intraday extremes. Feasibility refers to the displayed
                historical checklist, not live approval. Configuration and
                selection are saved in this browser.
              </Text>
            </>
          )}
        </div>
        {!isMobile &&
          (collapsed ? (
            <aside
              className="wb-rail-strip"
              aria-label="Combination, collapsed"
            >
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
        styles={{
          content: {
            height: "auto",
            maxHeight: "92vh",
            borderRadius: "16px 16px 0 0",
          },
        }}
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
