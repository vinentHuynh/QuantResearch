import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Badge,
  Box,
  Button,
  Checkbox,
  Group,
  Loader,
  MultiSelect,
  NumberInput,
  Paper,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import {
  IconCalendar,
  IconChartLine,
  IconChevronLeft,
  IconChevronRight,
  IconDownload,
  IconRefresh,
} from "@tabler/icons-react";
import {
  calculatePortfolio,
  commonWindow,
  defaultPolicy,
  type CollectiveCatalog,
  type CollectiveSeries,
  type DailyPoint,
  type GatePolicy,
} from "./collectiveModel";
import "./collective.css";

const money = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
const pct = (n: number) => `${(n * 100).toFixed(2)}%`;
const tone = (n: number) => (n < 0 ? "#b34338" : "#14795f");
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
  const colors = ["#2875ba", "#aa62a0", "#cc892b", "#548545", "#587382"];
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
  const x = (i: number) => 92 + (i / Math.max(1, points.length - 1)) * 920;
  const y = (v: number) => 285 - ((v - lo) / span) * 245;
  const polyline = (get: (p: DailyPoint, i: number) => number) =>
    points.map((p, i) => `${x(i)},${y(get(p, i))}`).join(" ");
  const h =
    hover == null
      ? null
      : points[Math.max(0, Math.min(points.length - 1, hover))];
  return (
    <Box className="collective-chart">
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
              ((((e.clientX - r.left) / r.width) * 1040 - 92) / 920) *
                (points.length - 1),
            ),
          );
        }}
      >
        {[lo, (lo + hi) / 2, hi].map((v, i) => (
          <g key={i}>
            <line x1="92" x2="1012" y1={y(v)} y2={y(v)} stroke="#dfe7e2" />
            <text
              x="83"
              y={y(v) + 4}
              textAnchor="end"
              fontSize="12"
              fill="#68776e"
            >
              {money(v)}
            </text>
          </g>
        ))}
        <line
          x1="92"
          x2="1012"
          y1={y(0)}
          y2={y(0)}
          stroke="#849c8c"
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
            {symbols.map((s, i) => (
              <polyline
                key={s}
                points={polyline((_, j) => marketCurves[j][s])}
                fill="none"
                stroke={colors[i % colors.length]}
                strokeWidth="1.5"
                opacity=".8"
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
              stroke="#075944"
              strokeWidth="3"
            />
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
        <text x="92" y="316" fontSize="12" fill="#68776e">
          {points[0]?.date}
        </text>
        <text x="1012" y="316" textAnchor="end" fontSize="12" fill="#68776e">
          {points.at(-1)?.date}
        </text>
      </svg>
      <Group gap="md" justify="space-between">
        <Group gap="md">
          <Text size="xs" fw={700} c="#075944">
            Combined book
          </Text>
          {mode !== "daily" &&
            symbols.map((s, i) => (
              <Text key={s} size="xs" c={colors[i % colors.length]}>
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
    </Box>
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
  const sum = points
    .filter((p) => p.date.startsWith(month))
    .reduce((v, p) => v + p.pnl, 0);
  function move(n: number) {
    onMonth(new Date(Date.UTC(year, m - 1 + n, 1)).toISOString().slice(0, 7));
  }
  return (
    <Paper withBorder p="lg">
      <Group justify="space-between" mb="md">
        <Box>
          <Group gap="xs">
            <IconCalendar size={20} />
            <Title order={3} id="collective-calendar">
              Daily P&amp;L calendar
            </Title>
          </Group>
          <Text size="sm" c={tone(sum)} mt={4}>
            {money(sum)} this month · UTC days
          </Text>
        </Box>
        <Group gap="xs">
          <Button
            variant="default"
            size="xs"
            aria-label="Previous month"
            onClick={() => move(-1)}
          >
            <IconChevronLeft size={16} />
          </Button>
          <TextInput
            aria-label="Calendar month"
            type="month"
            value={month}
            onChange={(e) =>
              e.currentTarget.value && onMonth(e.currentTarget.value)
            }
            w={160}
          />
          <Button
            variant="default"
            size="xs"
            aria-label="Next month"
            onClick={() => move(1)}
          >
            <IconChevronRight size={16} />
          </Button>
        </Group>
      </Group>
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
          return (
            <button
              key={day}
              aria-label={`${day}: ${p ? money(p.pnl) : "Outside test window"}`}
              aria-pressed={selected === day}
              disabled={!p}
              className={`calendar-day ${p ? (p.pnl > 0 ? "gain" : p.pnl < 0 ? "loss" : "flat") : "uncovered"} ${selected === day ? "selected" : ""}`}
              onClick={() => onDay(day)}
            >
              <span>{i + 1}</span>
              <strong>
                <span className="calendar-amount-full">
                  {p ? money(p.pnl) : "—"}
                </span>
                <span className="calendar-amount-short">
                  {p
                    ? p.pnl.toLocaleString("en-US", {
                        style: "currency",
                        currency: "USD",
                        notation: "compact",
                        maximumFractionDigits: 1,
                      })
                    : "—"}
                </span>
              </strong>
              <small>
                {p
                  ? p.trades
                    ? `${p.trades} exits`
                    : "No exits"
                  : "Outside window"}
              </small>
            </button>
          );
        })}
      </div>
    </Paper>
  );
}

export function CollectiveDashboard({ refreshKey }: { refreshKey: number }) {
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
    hidden = selected.filter((i) => !visible.some((v) => v.id === i.id)).length;
  const selectedDay = result?.points.find((p) => p.date === day);
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
  return (
    <Stack gap="lg" className="collective-dashboard">
      <Group justify="space-between">
        <Box>
          <Badge color="teal" variant="light">
            Portfolio builder · all charts
          </Badge>
          <Title order={2} mt="xs">
            See your strategies together
          </Title>
          <Text c="dimmed" size="sm">
            Combine tested configurations, compare their contribution, and
            inspect every day.
          </Text>
        </Box>
        <Group>
          <Button component="a" href="#collective-strategies" variant="light">
            Choose strategies
          </Button>
          <Button
            component="a"
            href="#collective-calendar"
            variant="light"
            disabled={!result}
          >
            Calendar
          </Button>
          <Button
            variant="default"
            leftSection={<IconRefresh size={16} />}
            loading={refreshing}
            onClick={() => void refreshEvidence()}
          >
            Refresh evidence
          </Button>
        </Group>
      </Group>
      {error && (
        <Alert color="red" title="Collective evidence">
          {error}
        </Alert>
      )}
      {result && (
        <>
          <Text size="sm" c="dimmed">
            {selected.length} configurations · {settings.start} to{" "}
            {settings.end} ·{" "}
            {settings.basis === "marked"
              ? "daily marked P&L"
              : "closed-trade P&L"}
          </Text>
          <SimpleGrid cols={{ base: 2, md: 4 }} data-testid="portfolio-metrics">
            {[
              [
                "Combined net P&L",
                money(result.net),
                `${pct(result.returnOnCapital)} on represented capital`,
              ],
              [
                "Capital represented",
                money(result.capital),
                "Sum of independent books; no netting",
              ],
              [
                "Maximum drawdown",
                money(result.maxDrawdownDollars),
                `${pct(Math.abs(result.maxDrawdown))} · ${settings.basis === "marked" ? "daily closes" : "closed trades only"}`,
              ],
              [
                "Combination score",
                result.recoveryFactor?.toFixed(2) || "Undefined",
                "Net P&L ÷ maximum drawdown dollars",
              ],
              [
                "Profit factor",
                result.profitFactor?.toFixed(2) ?? "No finite ratio",
                "Closed-trade gains ÷ losses",
              ],
              [
                "Winning trades",
                result.winRate == null ? "No trades" : pct(result.winRate),
                `${result.trades} closed trade events`,
              ],
              [
                "Positive days",
                `${result.positiveDays} / ${result.activeDays}`,
                "Days with P&L or a closed trade",
              ],
              [
                settings.policy.enabled
                  ? "Effect of pause rule"
                  : "Selected configurations",
                settings.policy.enabled
                  ? money(result.net - result.baseline)
                  : String(selected.length),
                settings.policy.enabled
                  ? `Always-on net ${money(result.baseline)}`
                  : `${Object.keys(totals).length} markets in this book`,
              ],
            ].map(([label, value, note]) => (
              <Paper withBorder p="md" key={label}>
                <Text size="xs" c="dimmed">
                  {label}
                </Text>
                <Text fw={700} fz={25} className="collective-kpi">
                  {value}
                </Text>
                <Text size="xs" c="dimmed">
                  {note}
                </Text>
              </Paper>
            ))}
          </SimpleGrid>
          <Paper withBorder p="lg">
            <Group justify="space-between" mb="md">
              <Box>
                <Group gap="xs">
                  <IconChartLine size={20} />
                  <Title order={3}>Combined P&amp;L across charts</Title>
                </Group>
                <Text size="xs" c="dimmed" mt={4}>
                  {settings.basis === "marked"
                    ? "Daily marked P&L, including open positions"
                    : "Closed-trade P&L assigned to UTC exit dates"}{" "}
                  · net of recorded costs
                </Text>
              </Box>
                <Select
                  aria-label="P&L chart mode"
                  w={240}
                  maw="100%"
                value={chartMode}
                onChange={(v) => setChartMode(v || "cumulative")}
                data={[
                  {
                    value: "cumulative",
                    label: "Cumulative + every market",
                  },
                  { value: "daily", label: "Daily P&L bars" },
                ]}
              />
            </Group>
            <PnlChart
              points={result.points}
              mode={chartMode}
              comparison={settings.policy.enabled}
            />
          </Paper>
        </>
      )}
      {!catalog ? (
        <Group>
          <Loader size="sm" />
          <Text>Loading strategy catalog…</Text>
        </Group>
      ) : (
        <>
          <Paper withBorder p="lg">
            <Group justify="space-between" mb="md">
              <Box>
                <Title order={3} id="collective-strategies">
                  Choose your strategies
                </Title>
                <Text size="sm" c="dimmed">
                  {catalog.items.length} strategy / market / timeframe
                  configurations ·{" "}
                  {catalog.items.filter((i) => i.working).length} working ·{" "}
                  {catalog.items.filter((i) => i.feasible).length} pass the full
                  research checklist
                </Text>
              </Box>
              <Badge size="lg" variant="light" data-testid="selected-count">
                {selected.length} selected
              </Badge>
            </Group>
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
              <Select
                label="Eligibility filter"
                value={filter}
                onChange={(v) => setFilter(v || "working")}
                data={[
                  { value: "working", label: "Working — later checks passed" },
                  {
                    value: "feasible",
                    label: "Fully tested & feasible — research",
                  },
                  { value: "all", label: "All tested configurations" },
                  { value: "screen", label: "Screened only" },
                ]}
              />
              <MultiSelect
                label="Markets / charts"
                placeholder="All markets"
                data={[...new Set(catalog.items.map((i) => i.symbol))].sort()}
                value={markets}
                onChange={setMarkets}
                clearable
              />
              <Select
                label="Chart timeframe"
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
                placeholder="Name, session or source"
                value={search}
                onChange={(e) => setSearch(e.currentTarget.value)}
              />
            </SimpleGrid>
            <Text size="xs" c="dimmed" mt="sm">
              {filter === "feasible"
                ? catalog.definitions.feasible
                : catalog.definitions.working}{" "}
              Screening profits alone do not qualify as working.
            </Text>
            <Group mt="md" mb="sm">
              <Button
                size="xs"
                onClick={() =>
                  choose(
                    Object.fromEntries(
                      visible.slice(0, 100).map((i) => [i.id, 1]),
                    ),
                  )
                }
                disabled={!visible.length || visible.length > 100}
              >
                Apply visible strategies ({visible.length})
              </Button>
              <Button size="xs" variant="default" onClick={() => choose({})}>
                Clear combination
              </Button>
              <Text size="xs" c="dimmed">
                Copies repeat each recorded book and its capital; they do not
                rerun sizing. Up to 100 configurations per combination; narrow
                the filters to apply a larger visible list.
              </Text>
            </Group>
            {hidden > 0 && (
              <Alert color="yellow" mb="sm">
                {hidden} selected configurations are hidden by these filters.
                They remain in the combined book until you remove them or apply
                the visible strategies.
              </Alert>
            )}
            <ScrollArea h={Math.min(390, 70 + visible.length * 63)}>
              <Table miw={1000} highlightOnHover data-testid="strategy-picker">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Include</Table.Th>
                    <Table.Th>Strategy / chart</Table.Th>
                    <Table.Th>Evidence</Table.Th>
                    <Table.Th>Test coverage</Table.Th>
                    <Table.Th ta="right">2024 onward marked P&amp;L</Table.Th>
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
                        <Text size="xs" c="dimmed">
                          {i.symbol} · {i.timeframe} · {i.session}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge
                          color={
                            i.feasible ? "teal" : i.working ? "blue" : "gray"
                          }
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
                        <Text size="xs">
                          {i.start}
                          <br />
                          {i.end}
                        </Text>
                      </Table.Td>
                      <Table.Td ta="right" c={tone(i.recent_pnl)}>
                        {i.end < "2024" ? "Not tested" : money(i.recent_pnl)}
                      </Table.Td>
                      <Table.Td maw={320}>
                        <details>
                          <summary>{i.reasons.length} notes</summary>
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
                No strategies meet these filters. Missing tests are not treated
                as passes.
              </Text>
            )}
            {catalog.errors.length > 0 && (
              <Alert color="yellow" mt="md">
                {catalog.errors.length} configurations could not be verified and
                are excluded:{" "}
                {catalog.errors.map((e) => e.key + ": " + e.error).join("; ")}
              </Alert>
            )}
          </Paper>
          <Paper withBorder p="lg">
            <Group justify="space-between" mb="md">
              <Title order={3}>Your combination</Title>
              <Group>
                <Button
                  size="xs"
                  variant="default"
                  onClick={exportCombination}
                  disabled={!selected.length}
                >
                  Save combination JSON
                </Button>
                <Button
                  size="xs"
                  variant="default"
                  leftSection={<IconDownload size={14} />}
                  onClick={exportDaily}
                  disabled={!result}
                >
                  Export daily P&amp;L
                </Button>
              </Group>
            </Group>
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
              <TextInput
                type="date"
                label="P&L start"
                value={settings.start}
                onChange={(e) => {
                  const start = e.currentTarget.value;
                  setSettings((s) => ({ ...s, start }));
                }}
              />
              <TextInput
                type="date"
                label="P&L end"
                value={settings.end}
                onChange={(e) => {
                  const end = e.currentTarget.value;
                  setSettings((s) => ({ ...s, end }));
                  if (end) setMonth(end.slice(0, 7));
                }}
              />
              <Select
                label="P&L accounting"
                value={settings.basis}
                disabled={settings.policy.enabled}
                onChange={(v) =>
                  setSettings((s) => ({
                    ...s,
                    basis: v === "closed" ? "closed" : "marked",
                  }))
                }
                data={[
                  {
                    value: "marked",
                    label: "Daily marked — includes open P&L",
                  },
                  { value: "closed", label: "Closed trades — exit-day P&L" },
                ]}
              />
              <Box pt={24}>
                <Button
                  variant="default"
                  onClick={useCommon}
                  disabled={!selected.length}
                >
                  Use common tested window
                </Button>
              </Box>
            </SimpleGrid>
            <Text size="xs" c="dimmed" mt="sm">
              {catalog.definitions.pnl} Known gaps between test windows block
              aggregation. Zero on a covered day means no recorded change.
              Selections were made after inspecting these histories; this is not
              untouched portfolio validation.
            </Text>
            {selected.length > 0 && (
              <ScrollArea mt="md">
                <Table miw={620} data-testid="selected-strategies">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Selected strategy</Table.Th>
                      <Table.Th>Copies</Table.Th>
                      <Table.Th>Capital represented</Table.Th>
                      <Table.Th />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {selected.map((i) => (
                      <Table.Tr key={i.id}>
                        <Table.Td>
                          {i.name} · {i.symbol} · {i.timeframe}
                          <Text size="xs" c="dimmed">
                            {i.source} / {i.session}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <NumberInput
                            aria-label={`Copies of ${i.name} ${i.symbol} ${i.timeframe}`}
                            w={85}
                            min={1}
                            max={100}
                            allowDecimal={false}
                            value={settings.copies[i.id]}
                            onChange={(n) =>
                              setSettings((s) => ({
                                ...s,
                                copies: {
                                  ...s.copies,
                                  [i.id]: Math.max(
                                    1,
                                    Math.min(100, Number(n) || 1),
                                  ),
                                },
                              }))
                            }
                          />
                        </Table.Td>
                        <Table.Td>
                          {money(i.capital * settings.copies[i.id])}
                        </Table.Td>
                        <Table.Td>
                          <Button
                            size="compact-xs"
                            variant="subtle"
                            color="red"
                            onClick={() => {
                              const next = { ...settings.copies };
                              delete next[i.id];
                              choose(next);
                            }}
                          >
                            Remove
                          </Button>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
            )}
          </Paper>
          <Paper withBorder p="lg">
            <Group justify="space-between">
              <Box>
                <Title order={3}>Automatic pause / resume experiment</Title>
                <Text size="sm" c="dimmed">
                  Test a fixed loss rule against the same strategies always on.
                </Text>
              </Box>
              <Switch
                label="Enable pause/resume replay"
                checked={settings.policy.enabled}
                onChange={(e) => policy({ enabled: e.currentTarget.checked })}
              />
            </Group>
            {settings.policy.enabled && (
              <>
                <SimpleGrid mt="md" cols={{ base: 1, sm: 2, lg: 4 }}>
                  <Select
                    label="Losing pattern"
                    value={settings.policy.mode}
                    onChange={(v) =>
                      policy({ mode: (v || "rolling") as GatePolicy["mode"] })
                    }
                    data={[
                      {
                        value: "rolling",
                        label: "Rolling closed-trade losses",
                      },
                      { value: "streak", label: "Consecutive losing trades" },
                      { value: "drawdown", label: "Shadow equity drawdown" },
                    ]}
                  />
                  {settings.policy.mode === "rolling" ? (
                    <>
                      <NumberInput
                        label="Lookback trades"
                        min={2}
                        max={100}
                        allowDecimal={false}
                        value={settings.policy.lookback}
                        onChange={(n) =>
                          policy({ lookback: Math.max(2, Number(n) || 2) })
                        }
                      />
                      <NumberInput
                        label="Rolling loss threshold ($ / copy)"
                        min={0}
                        value={settings.policy.lossLimit}
                        onChange={(n) =>
                          policy({ lossLimit: Math.max(0, Number(n) || 0) })
                        }
                      />
                    </>
                  ) : settings.policy.mode === "streak" ? (
                    <NumberInput
                      label="Consecutive losses to pause"
                      min={1}
                      max={50}
                      allowDecimal={false}
                      value={settings.policy.streak}
                      onChange={(n) =>
                        policy({ streak: Math.max(1, Number(n) || 1) })
                      }
                    />
                  ) : (
                    <NumberInput
                      label="Drawdown threshold ($ / copy)"
                      min={1}
                      value={settings.policy.drawdown}
                      onChange={(n) =>
                        policy({ drawdown: Math.max(1, Number(n) || 1) })
                      }
                    />
                  )}
                  <NumberInput
                    label="Cooldown (calendar days)"
                    min={1}
                    max={365}
                    allowDecimal={false}
                    value={settings.policy.cooldown}
                    onChange={(n) =>
                      policy({ cooldown: Math.max(1, Number(n) || 1) })
                    }
                  />
                  <NumberInput
                    label="Shadow recovery trades"
                    min={1}
                    max={100}
                    allowDecimal={false}
                    value={settings.policy.recovery}
                    onChange={(n) =>
                      policy({ recovery: Math.max(1, Number(n) || 1) })
                    }
                  />
                </SimpleGrid>
                <Alert color="yellow" mt="md">
                  Exploratory entry-filter replay. Decisions use only trades
                  closed before entry; recovery observes hypothetical trades
                  while paused. Existing positions keep their original exits.
                  P&amp;L is realized on exit dates, so open risk is not shown.
                  Strategy state, sizing and margin are not rerun; skipped
                  entries can change them in a full simulation. Parameters are
                  not optimized and no live orders are controlled.
                </Alert>
              </>
            )}
          </Paper>
          {computed.error && (
            <Alert color={loading ? "blue" : "yellow"} title="Combined book">
              {computed.error}
            </Alert>
          )}
          {result && (
            <>
              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <Paper withBorder p="lg">
                  <Title order={3} mb="sm">
                    P&amp;L by market
                  </Title>
                  <Table data-testid="market-contributions">
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Market</Table.Th>
                        <Table.Th ta="right">Net P&amp;L</Table.Th>
                        <Table.Th ta="right">Configurations</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {Object.entries(totals)
                        .sort()
                        .map(([s, n]) => (
                          <Table.Tr key={s}>
                            <Table.Td>{s}</Table.Td>
                            <Table.Td ta="right" c={tone(n)}>
                              {money(n)}
                            </Table.Td>
                            <Table.Td ta="right">
                              {selected.filter((i) => i.symbol === s).length}
                            </Table.Td>
                          </Table.Tr>
                        ))}
                    </Table.Tbody>
                  </Table>
                </Paper>
                <Paper withBorder p="lg">
                  <Title order={3} mb="sm">
                    P&amp;L by year
                  </Title>
                  <Table>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Year</Table.Th>
                        <Table.Th ta="right">Net P&amp;L</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {Object.entries(annual)
                        .sort()
                        .map(([s, n]) => (
                          <Table.Tr key={s}>
                            <Table.Td>
                              {s}
                              {s === settings.end.slice(0, 4) &&
                              !settings.end.endsWith("12-31")
                                ? " (partial)"
                                : ""}
                            </Table.Td>
                            <Table.Td ta="right" c={tone(n)}>
                              {money(n)}
                            </Table.Td>
                          </Table.Tr>
                        ))}
                    </Table.Tbody>
                  </Table>
                </Paper>
              </SimpleGrid>
              <Calendar
                points={result.points}
                month={month}
                onMonth={setMonth}
                onDay={setDay}
                selected={day}
              />
              {selectedDay && (
                <Paper withBorder p="lg">
                  <Title order={3}>
                    {day} · {money(selectedDay.pnl)}
                  </Title>
                  <Text size="sm" c="dimmed">
                    {selectedDay.trades} closed trades ·{" "}
                    {settings.basis === "marked"
                      ? "Marked changes can occur without an exit."
                      : "Only trades closing this day contribute."}
                  </Text>
                  <Table mt="sm">
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Strategy / chart</Table.Th>
                        <Table.Th ta="right">Daily contribution</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {selected.map((i) => (
                        <Table.Tr key={i.id}>
                          <Table.Td>
                            {i.name} / {i.symbol} / {i.timeframe}
                          </Table.Td>
                          <Table.Td ta="right">
                            {money(selectedDay.byStrategy[i.id] || 0)}
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </Paper>
              )}
              <Paper withBorder p="lg">
                <Title order={3} mb="md">
                  Every strategy’s contribution
                </Title>
                <ScrollArea>
                  <Table miw={850} data-testid="strategy-contributions">
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Strategy / chart</Table.Th>
                        <Table.Th ta="right">Net P&amp;L</Table.Th>
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
                            {c.name} / {c.symbol}
                            <Text size="xs" c="dimmed">
                              {selected.find((i) => i.id === c.id)?.timeframe} ·{" "}
                              {selected.find((i) => i.id === c.id)?.session}
                            </Text>
                          </Table.Td>
                          <Table.Td ta="right" c={tone(c.pnl)}>
                            {money(c.pnl)}
                          </Table.Td>
                          <Table.Td ta="right">{money(c.baseline)}</Table.Td>
                          <Table.Td ta="right">{c.trades}</Table.Td>
                          <Table.Td ta="right">{c.skipped}</Table.Td>
                          <Table.Td>
                            <Badge
                              color={c.state === "Paused" ? "orange" : "teal"}
                            >
                              {settings.policy.enabled ? c.state : "Always on"}
                            </Badge>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </ScrollArea>
              </Paper>
              {settings.policy.enabled && (
                <Paper withBorder p="lg">
                  <Group justify="space-between" mb="md">
                    <Title order={3}>
                      Pause / resume decisions ({result.events.length})
                    </Title>
                    <Button
                      size="xs"
                      variant="default"
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
                  </Group>
                  <ScrollArea h={280}>
                    <Table miw={700}>
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
                            <Table.Td>{e.timestamp}</Table.Td>
                            <Table.Td>{e.name}</Table.Td>
                            <Table.Td>{e.state}</Table.Td>
                            <Table.Td>{e.reason}</Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                    {!result.events.length && (
                      <Text c="dimmed">
                        No state changes in this reporting window.
                      </Text>
                    )}
                  </ScrollArea>
                </Paper>
              )}
            </>
          )}
          <Text size="xs" c="dimmed">
            Evidence refreshed {new Date(catalog.generated_at).toLocaleString()}
            . Configuration and selection are saved in this browser. Histories
            are imported from verified full ledgers, with one baseline per
            strategy configuration; cost and execution variants are not added
            twice. Daily drawdown does not capture intraday extremes.
            Feasibility refers to the displayed historical checklist, not live
            approval.
          </Text>
        </>
      )}
    </Stack>
  );
}
