import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { strategyTitle } from "./strategyTitle";
import {
  Alert,
  Badge,
  Box,
  Button,
  Checkbox,
  Chip,
  Code,
  Drawer,
  Group,
  Menu,
  Modal,
  MultiSelect,
  NumberInput,
  Popover,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import {
  IconArrowDown,
  IconArrowUp,
  IconArrowUpRight,
  IconArrowsSort,
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconDatabase,
  IconDots,
  IconFlask,
  IconPlayerPlay,
  IconPlus,
  IconRefresh,
  IconStar,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import "./workbench.css";
import { ResearchPage, type EvaluationView, type RegimeView } from "./Research";
import { StrategyLibrary, type Library } from "./StrategyLibrary";
import { StrategyTesting } from "./StrategyTesting";
import { testingEvidence, comparePromising } from "./testingEvidence";
import { StrategyScorecards } from "./StrategyDashboard";
import { NqMonthlyComparison } from "./NqMonthlyComparison";
import { CollectiveDashboard } from "./CollectiveDashboard";
import { EventStudies } from "./EventStudies";
import { PageHeader, Shell, type SearchResult } from "./Shell";
import { href, navGroups, useRoute, type Page } from "./navigation";

type Field = {
  type: string;
  default: unknown;
  minimum?: number;
  maximum?: number;
  choices?: string[];
  description?: string;
};
type Strategy = {
  id: string;
  name: string;
  description: string;
  version: string;
  file: string;
  file_hash: string;
  timeframes: string[];
  parameters: Record<string, Field>;
  migration_scope?: string;
  default_warmup_days?: number;
  default_session?: string;
  execution_model?: string;
};
type Dataset = {
  id: string;
  symbol: string;
  source: string;
  rows: number;
  first: string;
  last: string;
  registered_at: string;
  archive: string;
  checksum: string;
  tick_size: number;
  point_value: number;
  warnings: string[];
  quality: Record<string, number>;
};
type Metrics = {
  net_return: number;
  net_pnl: number;
  max_drawdown: number;
  sharpe: number | null;
  cagr: number | null;
  volatility: number | null;
  trades: number | null;
  observations: number;
  costs: number;
  underwater_bars: number;
  current_underwater_bars: number;
  monthly: { month: string; return: number }[];
  basis: string;
  undefined_reason: string;
  first: string;
  last: string;
};
type Input = {
  delay_bars?: number;
  dataset_ids?: string[];
  timeframes?: string[];
  strategy_id: string;
  dataset_id: string;
  start: string;
  end: string;
  timeframe: string;
  session: string;
  stage: string;
  capital: number;
  fee: number;
  slippage: number;
  timeout: number;
  warmup_days: number;
  development_end: string;
  hypothesis: string;
  criteria: string;
  parameters: Record<string, unknown>;
  sweep: Record<string, unknown[]>;
};
type RunInput = Omit<Input, "strategy_id" | "dataset_id" | "sweep"> & {
  research?: {
    evaluation_id: string;
    fold: number;
    role: string;
    candidate: number;
    scenario: string;
  };
  strategy: Strategy;
  dataset: Dataset;
  source_hash: string;
  configuration_id: string;
  experiment_id: string;
  selection_time: string;
  retry_of?: string;
};
export type RunSummary = {
  id: string;
  status: string;
  created_at: string;
  started_at?: string;
  ended_at?: string;
  input: RunInput;
  error?: string;
  notes?: string;
  tags?: string;
  watch_id?: string;
  log?: string;
  result?: {
    metrics: Metrics;
    warnings: string[];
    artifacts: { name: string }[];
  };
};
export type Run = Omit<RunSummary, "result"> & {
  result?: NonNullable<RunSummary["result"]> & {
    equity_preview: { timestamp: string; equity: number; drawdown?: number }[];
    trade_preview: Record<string, unknown>[];
  };
};
type RunSortValue = string | number | null | undefined;
type RunSortColumn = {
  key: string;
  label: string;
  numeric?: boolean;
  value: (run: RunSummary, now: number) => RunSortValue;
};
function runtimeSeconds(run: RunSummary, now: number) {
  return run.started_at
    ? Math.max(0, (run.ended_at ? Date.parse(run.ended_at) : now) - Date.parse(run.started_at)) / 1000
    : null;
}
const runSortColumns: RunSortColumn[] = [
  { key: "created", label: "Created", value: (run) => Date.parse(run.created_at) },
  { key: "strategy", label: "Strategy / run", value: (run) => strategyTitle(run.input.strategy.name) },
  { key: "data", label: "Data / window", value: (run) => `${run.input.dataset.symbol} ${run.input.timeframe} ${run.input.start} ${run.input.end}` },
  { key: "stage", label: "Run purpose", value: (run) => run.input.stage },
  { key: "status", label: "Execution", value: (run) => run.status },
  { key: "return", label: "Net return", numeric: true, value: (run) => run.result?.metrics.net_return },
  { key: "drawdown", label: "Drawdown", numeric: true, value: (run) => run.result?.metrics.max_drawdown },
  { key: "trades", label: "Trades", numeric: true, value: (run) => run.result?.metrics.trades },
  { key: "runtime", label: "Runtime", numeric: true, value: runtimeSeconds },
];
const runSortOptions = runSortColumns.flatMap((column) =>
  ["asc", "desc"].map((direction) => ({
    value: `${column.key}:${direction}`,
    label: column.key === "created"
      ? direction === "asc" ? "Oldest" : "Newest"
      : `${column.label} (${direction === "asc" ? "ascending" : "descending"})`,
  })),
);
function compareRunValues(a: RunSortValue, b: RunSortValue, descending: boolean) {
  const missing = (value: RunSortValue) => value == null || (typeof value === "number" && !Number.isFinite(value));
  if (missing(a)) return missing(b) ? 0 : 1;
  if (missing(b)) return -1;
  const order = typeof a === "number" && typeof b === "number"
    ? a - b
    : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  return descending ? -order : order;
}

type Watch = {
  id: string;
  run_id: string;
  frozen_at: string;
  reason: string;
  configuration_id: string;
  source: string;
};
type View = {
  id: string;
  name: string;
  filter: string;
  stage: string;
  status: string;
};
type State = {
  library?: Library;
  evaluations?: EvaluationView[];
  regimes?: RegimeView[];
  strategies: Strategy[];
  errors: { file?: string; error: string }[];
  datasets: Dataset[];
  runs: RunSummary[];
  watchlist: Watch[];
  presets: { id: string; name: string; input: Input }[];
  views: View[];
  experiments: { id: string; attempted_variants: number; hypothesis: string }[];
  import: { status: string; log: string; error?: string };
  limits: { concurrency: number; maxBatch: number };
};
type Comparison = {
  mode: string;
  start?: string;
  end?: string;
  boundary?: string;
  runs?: Run[];
  rows?: { id: string; metrics: Metrics; baseline_equity: number }[];
};
type WarmupCheck = {
  symbol: string;
  timeframe: string;
  parameters: Record<string, unknown>;
  status: string;
  required_bars: number;
  available_bars: number;
  warning: string | null;
};
const API = "/api/workbench";
async function request<T>(
  path: string,
  data?: unknown,
  method = "POST",
): Promise<T> {
  const response = await fetch(
    API + path,
    data === undefined
      ? undefined
      : {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
  );
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Request failed");
  return value;
}
const pct = (value: number | null | undefined) =>
  value == null ? "—" : `${(value * 100).toFixed(2)}%`;
const num = (value: number | null | undefined) =>
  value == null
    ? "—"
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
const short = (value: string) => value.slice(0, 8);
const tone = (status: string) =>
  status === "Succeeded"
    ? "teal"
    : ["Failed", "Interrupted", "Error"].includes(status)
      ? "red"
      : ["Running", "Queued"].includes(status)
        ? "blue"
        : "gray";
const sessions = [
  { value: "new-york-rth", label: "New York RTH" },
  { value: "full-trading-day", label: "Full Globex day" },
  { value: "london", label: "London" },
  { value: "asia", label: "Tokyo" },
];
const initial: Input = {
  strategy_id: "",
  dataset_id: "",
  start: "2026-01-01",
  end: "2026-09-03",
  timeframe: "1h",
  session: "new-york-rth",
  stage: "Exploratory",
  capital: 100000,
  fee: 1.25,
  slippage: 1,
  timeout: 300,
  warmup_days: 60,
  development_end: "",
  hypothesis: "",
  criteria: "",
  parameters: {},
  sweep: {},
};
const STEPS = [
  "Script & dataset",
  "Parameters",
  "Assumptions & record",
  "Preview & launch",
];

function parseSweep(text: string): Record<string, unknown[]> | null {
  try {
    const value = JSON.parse(text);
    return value && typeof value === "object" && !Array.isArray(value)
      ? value
      : null;
  } catch {
    return null;
  }
}

function EquityChart({ run }: { run: Run }) {
  const points = run.result?.equity_preview || [];
  if (points.length < 2) return <Text>No equity preview available.</Text>;
  const values = [run.input.capital, ...points.map((p) => p.equity)];
  const low = Math.min(...values),
    high = Math.max(...values),
    range = high - low || 1;
  const coords = values
    .map(
      (v, i) =>
        `${(i / (values.length - 1)) * 960},${150 - ((v - low) / range) * 130}`,
    )
    .join(" ");
  return (
    <Box className="wb-chart">
      <Group justify="space-between">
        <Text size="sm" fw={600}>
          Marked equity · USD
        </Text>
        <Text size="xs" c="dimmed">
          ${num(low)} – ${num(high)}
        </Text>
      </Group>
      <svg
        viewBox="0 0 960 170"
        role="img"
        aria-label="Equity curve in US dollars"
      >
        <line x1="0" x2="960" y1="150" y2="150" stroke="#dbe5e0" />
        <polyline
          points={coords}
          fill="none"
          stroke="#187465"
          strokeWidth="2"
        />
      </svg>
      {points.every((p) => p.drawdown !== undefined) && (
        <>
          <Text size="xs" c="dimmed">
            Continuous drawdown from equity peak ·{" "}
            {pct(run.result?.metrics.max_drawdown)} maximum
          </Text>
          <svg
            viewBox="0 0 960 65"
            role="img"
            aria-label="Continuous drawdown chart"
          >
            <line x1="0" x2="960" y1="5" y2="5" stroke="#dbe5e0" />
            <polyline
              points={points
                .map(
                  (p, i) =>
                    `${(i / (points.length - 1)) * 960},${5 + ((p.drawdown || 0) / (run.result?.metrics.max_drawdown || -1)) * 50}`,
                )
                .join(" ")}
              fill="none"
              stroke="#a56945"
              strokeWidth="2"
            />
          </svg>
        </>
      )}
      <Group justify="space-between">
        <Text size="xs" c="dimmed">
          {points[0].timestamp.slice(0, 10)}
        </Text>
        <Text size="xs" c="dimmed">
          {points.at(-1)?.timestamp.slice(0, 10)}
        </Text>
      </Group>
      <Text size="xs" c="dimmed">
        Preview sampled for display. Full bar-level equity is available in the
        CSV.
      </Text>
    </Box>
  );
}

export function Workbench() {
  const [deletion, setDeletion] = useState<{
    ids: string[];
    token: string;
    counts: Record<string, number>;
    explanation: string;
  } | null>(null);
  const [state, setState] = useState<State | null>(null);
  const stateEtag = useRef("");
  const [route, go] = useRoute();
  const [researchSelection, setResearchSelection] = useState<string>("");
  const [dashboardRefresh, setDashboardRefresh] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState<Input>(initial);
  const [sweepText, setSweepText] = useState("{}");
  const [preview, setPreview] = useState<number | null>(null);
  const [warmupChecks, setWarmupChecks] = useState<WarmupCheck[]>([]);
  const [step, setStep] = useState(0);
  const [filter, setFilter] = useState("");
  const [testingMarket, setTestingMarket] = useState("");
  const [stage, setStage] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("created:desc");
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [detail, setDetail] = useState<Run | null>(null);
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [reason, setReason] = useState("");
  const [presetName, setPresetName] = useState("");
  const [viewName, setViewName] = useState("");
  const [viewOpen, setViewOpen] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const response = await fetch(API + "/state?view=summary", {
        headers: stateEtag.current ? { "If-None-Match": stateEtag.current } : {},
      });
      if (response.status === 304) return;
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || response.statusText);
      stateEtag.current = response.headers.get("ETag") || "";
      setState(data as State);
    } catch (e) {
      setError(String(e));
    }
  }, []);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!document.hidden) await refresh();
      if (!stopped) timer = setTimeout(() => void poll(), 10000);
    };
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [refresh]);
  useEffect(() => {
    if (!detail || !["Queued", "Running"].includes(detail.status)) return;
    const timer = setInterval(() => {
      request<Run>(`/runs/${detail.id}`)
        .then(setDetail)
        .catch((e) => setError(String(e)));
    }, 1000);
    return () => clearInterval(timer);
  }, [detail]);
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [route.page]);
  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  function change<K extends keyof Input>(key: K, value: Input[K]) {
    setInput((v) => ({ ...v, [key]: value }));
    setPreview(null);
  }
  function chooseStrategy(id: string) {
    const s = state?.strategies.find((s) => s.id === id);
    if (!s) return;
    setInput((v) => ({
      ...v,
      strategy_id: id,
      warmup_days: Math.max(v.warmup_days, s.default_warmup_days || 0),
      session: s.default_session || v.session,
      timeframes: [],
      parameters: Object.fromEntries(
        Object.entries(s.parameters).map(([key, f]) => [key, f.default]),
      ),
      timeframe: s.timeframes.includes(v.timeframe)
        ? v.timeframe
        : s.timeframes[0],
    }));
    setPreview(null);
    setSweepText("{}");
  }
  function configure(id: string) {
    chooseStrategy(id);
    setStep(0);
    go("new-run");
  }
  function runInput() {
    return {
      ...input,
      dataset_ids: [
        ...new Set([input.dataset_id, ...(input.dataset_ids || [])]),
      ],
      timeframes: [...new Set([input.timeframe, ...(input.timeframes || [])])],
      sweep: JSON.parse(sweepText),
    };
  }
  async function inspect(run: RunSummary) {
    const result = await request<Run>(`/runs/${run.id}`);
    setDetail(result);
    setNotes(result.notes || "");
    setTags(result.tags || "");
    setReason("");
  }
  function reuse(run: Run) {
    setInput({
      ...run.input,
      strategy_id: run.input.strategy.id,
      dataset_id: run.input.dataset.id,
      dataset_ids: [],
      timeframes: [],
      stage: run.input.stage === "Tracking" ? "Exploratory" : run.input.stage,
      sweep: {},
    });
    setSweepText("{}");
    setPreview(null);
    setDetail(null);
    setStep(0);
    go("new-run");
  }
  function updateSweep(key: string, values: unknown[]) {
    const current = parseSweep(sweepText);
    if (!current) return;
    const next = { ...current };
    if (values.length) next[key] = values;
    else delete next[key];
    setSweepText(JSON.stringify(next));
    setPreview(null);
  }
  const strategy = state?.strategies.find((s) => s.id === input.strategy_id);
  const dataset = state?.datasets.find((d) => d.id === input.dataset_id);
  const [sortKey, sortDirection] = sort.split(":");
  const sortColumn = runSortColumns.find((column) => column.key === sortKey)!;
  const now = Date.now();
  const filtered = (state?.runs || [])
    .filter(
      (r) =>
        (!stage || r.input.stage === stage) &&
        (!status || r.status === status) &&
        `${r.input.strategy.name} ${r.input.dataset.symbol} ${r.id} ${r.tags || ""} ${r.input.hypothesis}`
          .toLowerCase()
          .includes(filter.toLowerCase()),
    )
    .sort((a, b) => compareRunValues(
      sortColumn.value(a, now), sortColumn.value(b, now), sortDirection === "desc",
    ));
  const compareRuns =
    comparison?.runs ||
    (comparison?.rows || [])
      .map((row) => state?.runs.find((r) => r.id === row.id))
      .filter((r): r is RunSummary => !!r);
  const counts = {
    total: state?.runs.length || 0,
    active:
      state?.runs.filter((r) => ["Running", "Queued"].includes(r.status))
        .length || 0,
    success: state?.runs.filter((r) => r.status === "Succeeded").length || 0,
  };
  const compareBlocked =
    selected.length < 2 ||
    selected.length > 8 ||
    busy ||
    selected.some(
      (id) => state?.runs.find((r) => r.id === id)?.status !== "Succeeded",
    );
  const navCounts: Partial<Record<Page, number>> = state
    ? {
        runs: state.runs.length,
        evaluations: (state.evaluations || []).length,
        watchlist: state.watchlist.length,
        scripts: state.strategies.length,
        datasets: state.datasets.length,
      }
    : {};
  const sweep = parseSweep(sweepText);
  const planDatasets = [
    ...new Set([input.dataset_id, ...(input.dataset_ids || [])].filter(Boolean)),
  ].length;
  const planTimeframes = [
    ...new Set([input.timeframe, ...(input.timeframes || [])].filter(Boolean)),
  ].length;
  const planCombos = sweep
    ? Object.values(sweep).reduce(
        (n, v) => n * (Array.isArray(v) ? Math.max(1, v.length) : 1),
        1,
      )
    : null;
  const estimate =
    planCombos === null ? null : Math.max(1, planDatasets) * planTimeframes * planCombos;
  const planned = preview ?? estimate;
  const maxBatch = state?.limits.maxBatch || 24;

  const search = useMemo(
    () =>
      (query: string): SearchResult[] => {
        const q = query.trim().toLowerCase();
        const pages: SearchResult[] = [
          ...navGroups({}).flatMap((g) =>
            g.items.map((item) => ({
              group: "Pages",
              label: item.label,
              detail: g.label,
              run: () => go(item.page),
            })),
          ),
          { group: "Pages", label: "New run", detail: "Research", run: () => go("new-run") },
        ].filter((p) => !q || p.label.toLowerCase().includes(q));
        if (!q || !state) return pages;
        const runs: SearchResult[] = state.runs
          .filter((r) =>
            `${r.input.strategy.name} ${r.input.dataset.symbol} ${r.id} ${r.tags || ""}`
              .toLowerCase()
              .includes(q),
          )
          .slice(0, 5)
          .map((r) => ({
            group: "Runs",
            label: `${strategyTitle(r.input.strategy.name)} · ${r.input.dataset.symbol} ${r.input.timeframe}`,
            detail: `${short(r.id)} · ${r.status} · ${r.input.start} → ${r.input.end}`,
            run: () => {
              go("runs");
              void action(() => inspect(r));
            },
          }));
        const strategies: SearchResult[] = state.strategies
          .filter((s) => `${s.name} ${s.id}`.toLowerCase().includes(q))
          .slice(0, 4)
          .map((s) => ({
            group: "Configure a run",
            label: strategyTitle(s.name),
            detail: s.timeframes.join(" · "),
            run: () => configure(s.id),
          }));
        const evaluations: SearchResult[] = (state.evaluations || [])
          .filter((e) => e.name.toLowerCase().includes(q))
          .slice(0, 4)
          .map((e) => ({
            group: "Evaluations",
            label: e.name,
            detail: e.outcome || e.status,
            run: () => {
              setResearchSelection(e.id);
              go("evaluations");
            },
          }));
        return [...pages, ...runs, ...strategies, ...evaluations];
      },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state, go],
  );

  const alerts =
    error || notice ? (
      <div className="wb-alerts">
        {error && (
          <Alert
            color="red"
            title="Action could not complete"
            withCloseButton
            onClose={() => setError("")}
          >
            {error}
          </Alert>
        )}
        {notice && (
          <Alert color="teal" withCloseButton onClose={() => setNotice("")}>
            {notice}
          </Alert>
        )}
      </div>
    ) : null;

  const refreshButton = (
    <Button
      variant="default"
      size="xs"
      leftSection={<IconRefresh size={14} />}
      onClick={() => {
        void refresh();
        setDashboardRefresh((value) => value + 1);
      }}
    >
      Refresh
    </Button>
  );

  function page() {
    if (route.page === "portfolio")
      return (
        <CollectiveDashboard
          refreshKey={dashboardRefresh}
          view={route.sub}
          alerts={alerts}
        />
      );
    if (route.page === "scorecards")
      return (
        <>
          <PageHeader
            crumb="Portfolio"
            title="Strategy scorecards"
            actions={refreshButton}
          />
          {alerts}
          <div className="wb-content">
            <StrategyScorecards
              refreshKey={dashboardRefresh}
              openEvaluation={(id) => {
                setResearchSelection(id);
                go("evaluations");
              }}
              inspectRun={(id) => {
                const run = state?.runs.find((r) => r.id === id);
                if (run) void action(() => inspect(run));
              }}
            />
          </div>
        </>
      );
    if (!state)
      return (
        <>
          <PageHeader crumb="Workbench" title="Connecting…" />
          {alerts}
          <div className="wb-content">
            <div className="wb-card">
              Connecting to the workbench… Start with{" "}
              <Code>npm run dev:full</Code>.
            </div>
          </div>
        </>
      );
    if (route.page === "evaluations")
      return (
        <ResearchPage
          selectedId={researchSelection}
          onSelect={setResearchSelection}
          alerts={alerts}
          runs={state.runs}
          evaluations={state.evaluations || []}
          regimes={state.regimes || []}
          refresh={refresh}
          inspect={(run) => void action(() => inspect(run))}
        />
      );
    if (route.page === "runs") return runsPage(state);
    if (route.page === "event-studies") return <EventStudies datasets={state.datasets} />;
    if (route.page === "new-run") return newRunPage(state);
    if (route.page === "scripts") return scriptsPage(state);
    if (route.page === "datasets") return datasetsPage(state);
    return watchlistPage(state);
  }

  function runsPage(state: State) {
    const activeView = state.views.find(
      (v) => v.filter === filter && v.stage === stage && v.status === status,
    );
    const experiments = route.sub === "experiments";
    const monthly = route.sub === "nq-monthly";
    return (
      <>
        <PageHeader
          crumb="Research"
          title="Runs & compare"
          actions={
            <>
              {refreshButton}
              <Menu position="bottom-end" withinPortal>
                <Menu.Target>
                  <Button variant="default" size="xs" aria-label="More run actions">
                    <IconDots size={15} />
                  </Button>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item
                    leftSection={<IconPlayerPlay size={14} />}
                    component="a"
                    href={href("new-run")}
                  >
                    New run
                  </Menu.Item>
                  <Menu.Divider />
                  <Menu.Item
                    color="red"
                    leftSection={<IconTrash size={14} />}
                    disabled={!state.runs.length || busy}
                    onClick={() =>
                      void action(async () =>
                        setDeletion(
                          await request("/runs/delete-preview", {
                            ids: state.runs.map((r) => r.id),
                          }),
                        ),
                      )
                    }
                  >
                    Clear all runs
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            </>
          }
          tabsLabel="Run views"
          tabs={[
            {
              label: "All runs",
              count: state.runs.length,
              active: !experiments && !monthly && !activeView,
              onClick: () => {
                setFilter("");
                setStage("");
                setStatus("");
                go("runs");
              },
            },
            {
              label: "NQ monthly",
              active: monthly,
              href: href("runs", "nq-monthly"),
            },
            {
              label: "Experiments",
              count: state.experiments.length,
              active: experiments,
              href: href("runs", "experiments"),
            },
            ...state.views.map((v) => ({
              label: v.name,
              active: !experiments && !monthly && activeView?.id === v.id,
              onClick: () => {
                setFilter(v.filter);
                setStage(v.stage);
                setStatus(v.status);
                go("runs");
              },
            })),
          ]}
          tabsExtra={
            !experiments && !monthly && (
              <Popover
                opened={viewOpen}
                onChange={setViewOpen}
                position="bottom-start"
                withinPortal
              >
                <Popover.Target>
                  <button
                    type="button"
                    className="wb-tab-action"
                    onClick={() => setViewOpen((o) => !o)}
                  >
                    <IconPlus size={13} />
                    Save current view
                  </button>
                </Popover.Target>
                <Popover.Dropdown>
                  <Stack gap="xs" w={240}>
                    <TextInput
                      label="View name"
                      placeholder="Name this view"
                      value={viewName}
                      onChange={(e) => setViewName(e.currentTarget.value)}
                    />
                    <Text size="xs" c="dimmed">
                      Saves the current search, run purpose and execution filters.
                    </Text>
                    <Button
                      size="xs"
                      disabled={!viewName}
                      onClick={() =>
                        void action(async () => {
                          await request("/views", {
                            name: viewName,
                            filter,
                            stage,
                            status,
                          });
                          setViewName("");
                          setViewOpen(false);
                        })
                      }
                    >
                      Save view
                    </Button>
                  </Stack>
                </Popover.Dropdown>
              </Popover>
            )
          }
        />
        {alerts}
        {monthly ? (
          <NqMonthlyComparison
            refreshKey={dashboardRefresh}
            onInspect={(id) => {
              const run = state.runs.find((candidate) => candidate.id === id);
              if (run) void action(() => inspect(run));
              else setError(`Saved run ${id} is no longer in the Workbench.`);
            }}
          />
        ) : experiments ? (
          <div className="wb-content">
            <p className="wb-context">
              All attempted variants remain recorded, including failed and
              losing runs.
            </p>
            <div className="wb-card">
              <h2>Experiment history</h2>
              {state.experiments.map((e) => (
                <Group
                  key={e.id}
                  justify="space-between"
                  className="wb-history"
                  wrap="nowrap"
                >
                  <Text size="sm">
                    {e.hypothesis || "Unlabeled experiment"}{" "}
                    <Text component="span" c="dimmed" size="xs">
                      {short(e.id)}
                    </Text>
                  </Text>
                  <Badge variant="light" color="gray">
                    {e.attempted_variants} variants launched
                  </Badge>
                </Group>
              ))}
              {!state.experiments.length && (
                <Text c="dimmed" size="sm" py="md">
                  No experiments recorded yet.
                </Text>
              )}
            </div>
          </div>
        ) : (
          <div className="wb-content">
            <div className="wb-toolbar">
              <TextInput
                aria-label="Search runs"
                placeholder="Strategy, market, tags, or run ID"
                value={filter}
                onChange={(e) => setFilter(e.currentTarget.value)}
              />
              <Select
                aria-label="Run purpose"
                placeholder="All run purposes"
                clearable
                data={["Exploratory", "Evaluation", "Tracking"]}
                value={stage || null}
                onChange={(v) => setStage(v || "")}
              />
              <Select
                aria-label="Execution"
                placeholder="All statuses"
                clearable
                data={[
                  "Queued",
                  "Running",
                  "Succeeded",
                  "Failed",
                  "Canceled",
                  "Interrupted",
                ]}
                value={status || null}
                onChange={(v) => setStatus(v || "")}
              />
              <Select
                aria-label="Sort"
                data={runSortOptions}
                value={sort}
                onChange={(v) => setSort(v || "created:desc")}
              />
              <span className="wb-toolbar-note">
                {state.limits.concurrency} workers · up to{" "}
                {state.limits.maxBatch} jobs per launch
              </span>
            </div>
            <div className="wb-statline">
              <span>
                <b>{counts.total}</b> recorded
              </span>
              <span>
                <b>{counts.active}</b> queued or running
              </span>
              <span>
                <b>{counts.success}</b> succeeded
              </span>
              <span>
                <b>{state.datasets.length}</b> dataset versions
              </span>
              {filtered.length !== counts.total && (
                <span>
                  <b>{filtered.length}</b> shown
                </span>
              )}
            </div>
            <section className="wb-table-card" aria-label="Run ledger">
              <ScrollArea>
                <Table miw={1100} highlightOnHover verticalSpacing="sm">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th />
                      {runSortColumns.slice(1).map((column) => (
                        <Table.Th
                          key={column.key}
                          ta={column.numeric ? "right" : undefined}
                          aria-sort={sortKey === column.key
                            ? sortDirection === "asc" ? "ascending" : "descending"
                            : "none"}
                        >
                          <button
                            type="button"
                            className={`wb-sort-header${column.numeric ? " wb-sort-numeric" : ""}`}
                            title={`Sort ${column.label} ${sortKey === column.key && sortDirection === "asc" ? "descending" : "ascending"}`}
                            onClick={() => setSort(`${column.key}:${sortKey === column.key && sortDirection === "asc" ? "desc" : "asc"}`)}
                          >
                            {column.label}
                            {sortKey !== column.key ? <IconArrowsSort size={14} aria-hidden="true" />
                              : sortDirection === "asc" ? <IconArrowUp size={14} aria-hidden="true" />
                                : <IconArrowDown size={14} aria-hidden="true" />}
                          </button>
                        </Table.Th>
                      ))}
                      <Table.Th />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {filtered.map((run) => (
                      <Table.Tr
                        key={run.id}
                        className={`wb-run-row${selected.includes(run.id) ? " selected" : ""}`}
                        onClick={() => void action(() => inspect(run))}
                      >
                        <Table.Td onClick={(e) => e.stopPropagation()}>
                          <Checkbox
                            aria-label={`Compare ${run.id}`}
                            disabled={["Queued", "Running"].includes(run.status)}
                            checked={selected.includes(run.id)}
                            onChange={(e) => {
                              const checked = e.currentTarget.checked;
                              setSelected((v) =>
                                checked
                                  ? [...v, run.id]
                                  : v.filter((id) => id !== run.id),
                              );
                            }}
                          />
                        </Table.Td>
                        <Table.Td>
                          <Text fw={600} size="sm">
                            {strategyTitle(run.input.strategy.name)}
                          </Text>
                          <Text size="xs" c="dimmed" ff="monospace">
                            {short(run.id)} · code {short(run.input.source_hash)}
                          </Text>
                          {run.tags && <Text size="xs">{run.tags}</Text>}
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">
                            {run.input.dataset.symbol} · {run.input.timeframe}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {run.input.start} → {run.input.end}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Badge
                            color={
                              run.input.stage === "Evaluation" ? "violet" : "gray"
                            }
                            variant="light"
                            radius="xs"
                          >
                            {run.input.stage}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          <Badge color={tone(run.status)} variant="light" radius="xs">
                            {run.status}
                          </Badge>
                        </Table.Td>
                        <Table.Td
                          ta="right"
                          className={`mono ${(run.result?.metrics.net_return || 0) < 0 ? "wb-loss" : "wb-gain"}`}
                        >
                          {pct(run.result?.metrics.net_return)}
                        </Table.Td>
                        <Table.Td ta="right" className="mono">
                          {pct(run.result?.metrics.max_drawdown)}
                        </Table.Td>
                        <Table.Td ta="right">
                          {num(run.result?.metrics.trades)}
                        </Table.Td>
                        <Table.Td ta="right" c="dimmed">
                          {run.started_at
                            ? `${runtimeSeconds(run, now)!.toFixed(1)}s`
                            : "—"}
                        </Table.Td>
                        <Table.Td onClick={(e) => e.stopPropagation()}>
                          <Button
                            variant="subtle"
                            size="compact-sm"
                            onClick={() => void action(() => inspect(run))}
                          >
                            Inspect
                          </Button>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
              {!filtered.length && (
                <div className="wb-empty">
                  <IconFlask size={36} />
                  <Title order={3} mt="sm">
                    {state.runs.length
                      ? "No matching runs"
                      : "A clean research notebook"}
                  </Title>
                  <Text c="dimmed" size="sm" mt="xs">
                    {state.runs.length
                      ? "Change the filters to see more experiments."
                      : "Register your local ZIP data, choose a script, and launch your first experiment."}
                  </Text>
                  <Button
                    mt="md"
                    variant="light"
                    component="a"
                    href={href(state.datasets.length ? "new-run" : "datasets")}
                  >
                    {state.datasets.length ? "Configure a run" : "Open datasets"}
                  </Button>
                </div>
              )}
            </section>
            {selected.length > 0 && (
              <div className="wb-selection-bar" role="toolbar" aria-label="Selected runs">
                <span className="count">{selected.length} selected</span>
                <button
                  type="button"
                  className="primary"
                  disabled={compareBlocked}
                  onClick={() =>
                    void action(async () =>
                      setComparison(
                        await request("/compare", {
                          ids: selected,
                          mode: "as-run",
                        }),
                      ),
                    )
                  }
                >
                  Compare as run
                </button>
                <button
                  type="button"
                  disabled={compareBlocked}
                  onClick={() =>
                    void action(async () =>
                      setComparison(
                        await request("/compare", {
                          ids: selected,
                          mode: "aligned",
                        }),
                      ),
                    )
                  }
                >
                  Align evaluation interval
                </button>
                <button
                  type="button"
                  className="danger"
                  disabled={busy}
                  onClick={() =>
                    void action(async () =>
                      setDeletion(
                        await request("/runs/delete-preview", {
                          ids: selected,
                        }),
                      ),
                    )
                  }
                >
                  Delete selected
                </button>
                <button
                  type="button"
                  className="clear"
                  aria-label="Clear selection"
                  onClick={() => setSelected([])}
                >
                  <IconX size={14} />
                </button>
              </div>
            )}
            {comparison && (
              <section className="wb-card">
                <div className="wb-card-head">
                  <Title order={2} className="wb-comparison-title" fz={16}>
                    {comparison.mode} comparison
                  </Title>
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={() => setComparison(null)}
                  >
                    Close comparison
                  </Button>
                </div>
                <Text size="sm" c="dimmed" mb="sm">
                  {comparison.boundary ||
                    "Original windows and accounting assumptions are shown below. Different assumptions require new runs for a fair comparison."}
                </Text>
                {comparison.start && (
                  <Text size="sm">
                    {comparison.start} → {comparison.end}
                  </Text>
                )}
                <ScrollArea>
                  <Table miw={850}>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Input / result</Table.Th>
                        {compareRuns.map((r) => (
                          <Table.Th key={r.id}>
                            {r.input.dataset.symbol} · {short(r.id)}
                          </Table.Th>
                        ))}
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {[
                        "window",
                        "stage",
                        "timeframe",
                        "session",
                        "capital",
                        "fee",
                        "slippage",
                        "delay_bars",
                        "parameters",
                        "source_hash",
                        "dataset",
                        "net_return",
                        "max_drawdown",
                        "sharpe",
                        "trades",
                      ].map((key) => {
                        const vals = compareRuns.map((r) => {
                          const metrics =
                            comparison.rows?.find((row) => row.id === r.id)
                              ?.metrics || r.result!.metrics;
                          if (key in metrics) {
                            const val = metrics[key as keyof Metrics];
                            return ["net_return", "max_drawdown"].includes(key)
                              ? pct(val as number)
                              : num(val as number);
                          }
                          if (key === "window")
                            return `${r.input.start} → ${r.input.end}`;
                          if (key === "dataset") return short(r.input.dataset.id);
                          return typeof r.input[key as keyof RunInput] ===
                            "object"
                            ? JSON.stringify(r.input[key as keyof RunInput])
                            : String(r.input[key as keyof RunInput]);
                        });
                        return (
                          <Table.Tr
                            key={key}
                            className={
                              new Set(vals).size > 1 ? "wb-difference" : ""
                            }
                          >
                            <Table.Td>{key.replaceAll("_", " ")}</Table.Td>
                            {vals.map((v, i) => (
                              <Table.Td key={i}>{v}</Table.Td>
                            ))}
                          </Table.Tr>
                        );
                      })}
                    </Table.Tbody>
                  </Table>
                </ScrollArea>
                <Text size="xs" c="dimmed" mt="sm">
                  Highlighted rows differ. Undefined statistics are shown as —.
                </Text>
              </section>
            )}
          </div>
        )}
      </>
    );
  }

  function parameterFields() {
    if (!strategy)
      return (
        <Text size="sm" c="dimmed">
          Choose a script in step 1 to load its parameter schema.
        </Text>
      );
    return Object.entries(strategy.parameters).map(([key, field]) =>
      field.type === "boolean" ? (
        <Checkbox
          key={key}
          label={key.replaceAll("_", " ")}
          description={field.description}
          checked={Boolean(input.parameters[key])}
          onChange={(e) =>
            change("parameters", {
              ...input.parameters,
              [key]: e.currentTarget.checked,
            })
          }
        />
      ) : field.type === "enum" ? (
        <Select
          key={key}
          label={key.replaceAll("_", " ")}
          description={field.description}
          data={field.choices || []}
          value={String(input.parameters[key])}
          onChange={(v) =>
            change("parameters", {
              ...input.parameters,
              [key]: v,
            })
          }
        />
      ) : ["integer", "number"].includes(field.type) ? (
        <NumberInput
          key={key}
          label={key.replaceAll("_", " ")}
          description={field.description}
          min={field.minimum}
          max={field.maximum}
          allowDecimal={field.type !== "integer"}
          value={input.parameters[key] as number}
          onChange={(v) =>
            change("parameters", {
              ...input.parameters,
              [key]: v,
            })
          }
        />
      ) : (
        <TextInput
          key={key}
          label={key.replaceAll("_", " ")}
          description={field.description}
          value={String(input.parameters[key] || "")}
          onChange={(e) =>
            change("parameters", {
              ...input.parameters,
              [key]: e.currentTarget.value,
            })
          }
        />
      ),
    );
  }

  function newRunPage(state: State) {
    const summaries = [
      strategy
        ? `${strategyTitle(strategy.name)} · ${dataset ? `${dataset.symbol} ${input.timeframe}` : "choose a dataset"} · ${input.start} to ${input.end}`
        : "Choose a script and dataset",
      strategy
        ? Object.entries(input.parameters)
            .map(([k, v]) => `${k} ${String(v)}`)
            .join(" · ") || "No parameters"
        : "Loads from the script",
      `${input.stage} · capital $${input.capital.toLocaleString()} · fee $${input.fee} · slippage ${input.slippage}`,
      preview !== null
        ? `${preview} job${preview === 1 ? "" : "s"} validated`
        : "Grid, then validate",
    ];
    const sweepable = strategy
      ? Object.entries(strategy.parameters).filter(([, f]) =>
          ["enum", "boolean", "integer", "number"].includes(f.type),
        )
      : [];
    return (
      <>
        <PageHeader
          crumb="Research / Runs & compare"
          title="New run"
          actions={
            <Button
              variant="subtle"
              size="xs"
              onClick={() => {
                setInput(initial);
                setSweepText("{}");
                setPreview(null);
                setStep(0);
              }}
            >
              Clear draft
            </Button>
          }
        />
        {alerts}
        <div className="wb-wizard">
          <ol className="wb-steps" aria-label="Steps">
            {STEPS.map((label, i) => (
              <li key={label}>
                <button
                  type="button"
                  className={`wb-step${i === step ? " current" : ""}${i < step ? " done" : ""}`}
                  aria-current={i === step ? "step" : undefined}
                  onClick={() => setStep(i)}
                >
                  <span className="wb-step-num">
                    {i < step ? <IconCheck size={13} /> : i + 1}
                  </span>
                  <span>
                    <b>{label}</b>
                    <small>{summaries[i]}</small>
                  </span>
                </button>
              </li>
            ))}
          </ol>
          <section className="wb-wizard-form" aria-label={STEPS[step]}>
            <h2>
              {step + 1}. {STEPS[step]}
            </h2>
            {step === 0 && (
              <>
                <Select
                  label="Strategy"
                  placeholder="Choose a Python strategy"
                  searchable
                  data={state.strategies.map((s) => ({
                    value: s.id,
                    label: strategyTitle(s.name),
                  }))}
                  value={input.strategy_id || null}
                  onChange={(v) => v && chooseStrategy(v)}
                />
                {strategy?.migration_scope && (
                  <Alert color="blue" title="Signal adapter scope">
                    {strategy.migration_scope}
                  </Alert>
                )}
                <Select
                  label="Dataset version"
                  placeholder="Choose a registered archive"
                  data={state.datasets.map((d) => ({
                    value: d.id,
                    label: `${d.symbol} · ${d.first.slice(0, 10)} → ${d.last.slice(0, 10)} · ${short(d.id)}`,
                  }))}
                  value={input.dataset_id || null}
                  onChange={(v) => {
                    if (!v) return;
                    const d = state.datasets.find((d) => d.id === v)!;
                    setInput((i) => ({
                      ...i,
                      dataset_id: v,
                      end: d.last.slice(0, 10),
                      start:
                        i.start < d.first.slice(0, 10) ||
                        i.start > d.last.slice(0, 10)
                          ? d.first.slice(0, 10)
                          : i.start,
                    }));
                    setPreview(null);
                  }}
                />
                {dataset && (
                  <Text size="xs" c="dimmed">
                    {dataset.rows.toLocaleString()} bars · UTC · USD · $
                    {dataset.point_value}/point · tick {dataset.tick_size}
                  </Text>
                )}
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  <Select
                    label="Timeframe"
                    data={strategy?.timeframes || []}
                    value={input.timeframe}
                    onChange={(v) => v && change("timeframe", v)}
                  />
                  <Select
                    label="Session"
                    data={sessions}
                    value={input.session}
                    onChange={(v) => v && change("session", v)}
                  />
                  <TextInput
                    label="Start date (UTC)"
                    type="date"
                    value={input.start}
                    onChange={(e) => change("start", e.currentTarget.value)}
                  />
                  <TextInput
                    label="End date (UTC, inclusive)"
                    type="date"
                    value={input.end}
                    onChange={(e) => change("end", e.currentTarget.value)}
                  />
                </SimpleGrid>
              </>
            )}
            {step === 1 && (
              <>
                {parameterFields()}
                <SimpleGrid cols={{ base: 1, sm: 2 }} mt="sm">
                  <Select
                    label="Load saved preset"
                    placeholder="Select preset"
                    data={state.presets.map((p) => ({
                      value: p.id,
                      label: p.name,
                    }))}
                    onChange={(id) => {
                      const p = state.presets.find((p) => p.id === id);
                      if (p) {
                        setInput(p.input);
                        setSweepText(JSON.stringify(p.input.sweep || {}));
                        setPreview(null);
                      }
                    }}
                  />
                  <Group align="end" wrap="nowrap">
                    <TextInput
                      label="Preset name"
                      value={presetName}
                      onChange={(e) => setPresetName(e.currentTarget.value)}
                      style={{ flex: 1 }}
                    />
                    <Button
                      variant="light"
                      disabled={!presetName || busy}
                      onClick={() =>
                        void action(async () => {
                          await request("/presets", {
                            name: presetName,
                            input: runInput(),
                          });
                          setNotice("Preset saved.");
                        })
                      }
                    >
                      Save preset
                    </Button>
                  </Group>
                </SimpleGrid>
              </>
            )}
            {step === 2 && (
              <>
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  {(
                    [
                      ["capital", "Initial capital (USD)"],
                      ["fee", "Fee / contract / side (USD)"],
                      ["slippage", "Slippage / side (ticks)"],
                      ["warmup_days", "Warmup calendar days"],
                      ["timeout", "Timeout (seconds)"],
                    ] as const
                  ).map(([key, label]) => (
                    <NumberInput
                      key={key}
                      label={label}
                      min={key === "capital" || key === "timeout" ? 1 : 0}
                      value={input[key]}
                      onChange={(v) => change(key, Number(v))}
                    />
                  ))}
                </SimpleGrid>
                <Text size="xs" c="dimmed">
                  {strategy?.execution_model === "event-v1"
                    ? "Whole contracts. This strategy uses its declared bar-close/next-open orders and working brackets; see its migration scope."
                    : "Fixed whole contracts. Decisions use completed bars and fill at the next available bar open."}{" "}
                  Final positions close at the final bar close. No cash flows.
                </Text>
                <Select
                  label="Run purpose"
                  description="Records the intent of this run. Testing milestones are earned from its evidence."
                  data={["Exploratory", "Evaluation"]}
                  value={input.stage}
                  onChange={(v) => v && change("stage", v)}
                />
                <Textarea
                  label="Question / hypothesis"
                  placeholder="What does this experiment test?"
                  value={input.hypothesis}
                  onChange={(e) => change("hypothesis", e.currentTarget.value)}
                />
                <TextInput
                  label="Development ends (before scored start)"
                  type="date"
                  value={input.development_end}
                  onChange={(e) =>
                    change("development_end", e.currentTarget.value)
                  }
                />
                <Textarea
                  label="Evaluation criteria"
                  description="Required for Evaluation. Recorded before execution; outcomes require your research judgment."
                  value={input.criteria}
                  onChange={(e) => change("criteria", e.currentTarget.value)}
                />
              </>
            )}
            {step === 3 && (
              <>
                <Text size="sm" c="dimmed">
                  Every combination below becomes one job. Nothing launches
                  until you validate and then press Launch.
                </Text>
                <MultiSelect
                  searchable
                  label="Additional dataset versions"
                  description="Optional: run the same experiment on more markets."
                  data={state.datasets
                    .filter((d) => d.id !== input.dataset_id)
                    .map((d) => ({
                      value: d.id,
                      label: `${d.symbol} · ${short(d.id)}`,
                    }))}
                  value={(input.dataset_ids || []).filter(
                    (id) => id !== input.dataset_id,
                  )}
                  onChange={(v) => change("dataset_ids", v)}
                />
                <MultiSelect
                  searchable
                  label="Additional timeframes"
                  description={
                    strategy && strategy.timeframes.length <= 1
                      ? `${strategyTitle(strategy.name)} runs on ${strategy.timeframes[0] || "one timeframe"} only.`
                      : "Datasets × timeframes × parameter combinations form the batch."
                  }
                  data={(strategy?.timeframes || []).filter(
                    (tf) => tf !== input.timeframe,
                  )}
                  value={(input.timeframes || []).filter(
                    (tf) => tf !== input.timeframe,
                  )}
                  onChange={(v) => change("timeframes", v)}
                />
                {sweepable.length > 0 && (
                  <Stack gap={8}>
                    <Text size="sm" fw={600}>
                      Parameter sweep
                    </Text>
                    {!sweep && (
                      <Text size="xs" c="red">
                        Fix the JSON below to use the sweep builder.
                      </Text>
                    )}
                    {sweepable.map(([key, field]) => {
                      const values = (sweep?.[key] as unknown[]) || [];
                      if (field.type === "enum" || field.type === "boolean") {
                        const choices =
                          field.type === "boolean"
                            ? ["true", "false"]
                            : field.choices || [];
                        return (
                          <div className="wb-dim" key={key}>
                            <span>{key}</span>
                            <Chip.Group
                              multiple
                              value={values.map(String)}
                              onChange={(v) =>
                                updateSweep(
                                  key,
                                  field.type === "boolean"
                                    ? v.map((x) => x === "true")
                                    : choices.filter((c) => v.includes(c)),
                                )
                              }
                            >
                              <Group gap={6}>
                                {choices.map((c) => (
                                  <Chip
                                    key={c}
                                    value={c}
                                    size="xs"
                                    disabled={!sweep}
                                  >
                                    {c}
                                  </Chip>
                                ))}
                              </Group>
                            </Chip.Group>
                          </div>
                        );
                      }
                      return (
                        <div className="wb-dim" key={key}>
                          <span>{key}</span>
                          <TextInput
                            size="xs"
                            aria-label={`Values to try for ${key}`}
                            placeholder="Comma-separated values, e.g. 10, 20, 40"
                            disabled={!sweep}
                            key={`${key}-${values.join(",")}`}
                            defaultValue={values.join(", ")}
                            onBlur={(e) =>
                              updateSweep(
                                key,
                                e.currentTarget.value
                                  .split(",")
                                  .map((x) => x.trim())
                                  .filter(Boolean)
                                  .map(Number)
                                  .filter((x) => Number.isFinite(x)),
                              )
                            }
                          />
                        </div>
                      );
                    })}
                  </Stack>
                )}
                <Textarea
                  label="Parameter sweep (JSON)"
                  description={
                    'The builder above writes this field. Use {} for a single run, or {"lookback": [10, 20, 40]} for a grid.'
                  }
                  autosize
                  minRows={2}
                  value={sweepText}
                  onChange={(e) => {
                    setSweepText(e.currentTarget.value);
                    setPreview(null);
                  }}
                  styles={{ input: { fontFamily: "var(--mono)" } }}
                />
                <Group>
                  <Button
                    variant="light"
                    loading={busy}
                    onClick={() =>
                      void action(async () => {
                        setPreview(null);
                        const result = await request<{ jobs: number; warmup: WarmupCheck[] }>(
                          "/preview",
                          runInput(),
                        );
                        setPreview(result.jobs);
                        setWarmupChecks(result.warmup || []);
                      })
                    }
                  >
                    Validate & preview
                  </Button>
                  <Button
                    leftSection={<IconPlayerPlay size={16} />}
                    disabled={preview === null || busy}
                    onClick={() =>
                      void action(async () => {
                        const runs = await request<Run[]>("/runs", runInput());
                        setNotice(
                          `${runs.length} run(s) queued. You can leave this page while they execute.`,
                        );
                        setPreview(null);
                        go("runs");
                      })
                    }
                  >
                    Launch {preview || ""} {preview === 1 ? "run" : "runs"}
                  </Button>
                </Group>
                {preview !== null && (
                  <Alert
                    color="teal"
                    title={`${preview} job${preview === 1 ? "" : "s"} ready`}
                  >
                    Inputs passed preflight. Launching preserves this
                    experiment's code and resolved parameters.
                  </Alert>
                )}
                {preview !== null && warmupChecks.map((check, index) => (
                  <Alert key={index} color={check.status === "insufficient" ? "orange" : "teal"}
                    title={`${check.symbol} ${check.timeframe}: warmup ${check.status}`}>
                    <Text size="sm">{check.available_bars} completed bars before scoring; {check.required_bars} required.</Text>
                    <Text size="xs">Parameters: {JSON.stringify(check.parameters)}</Text>
                    {check.warning && <Text size="sm">{check.warning}</Text>}
                  </Alert>
                ))}
              </>
            )}
            <div className="wb-wizard-nav">
              <Button
                variant="default"
                leftSection={<IconChevronLeft size={14} />}
                disabled={step === 0}
                onClick={() => setStep((s) => Math.max(0, s - 1))}
              >
                Back
              </Button>
              {step < STEPS.length - 1 && (
                <Button
                  ml="auto"
                  rightSection={<IconChevronRight size={14} />}
                  onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
                >
                  Continue to {STEPS[step + 1].toLowerCase()}
                </Button>
              )}
            </div>
          </section>
          <aside className="wb-plan" aria-label="Launch plan">
            <div className="wb-crumb">Launch plan</div>
            <div>
              <span className="wb-plan-big">{planned ?? "—"}</span>{" "}
              <b>{planned === 1 ? "job" : "jobs"}</b>{" "}
              <Text span size="xs" c="dimmed">
                {preview !== null
                  ? "validated"
                  : planned === null
                    ? "sweep JSON is invalid"
                    : "estimated"}
              </Text>
            </div>
            <div className={`wb-meter${(planned || 0) > maxBatch ? " over" : ""}`}>
              <span
                style={{
                  width: `${Math.min(100, ((planned || 0) / maxBatch) * 100)}%`,
                }}
              />
            </div>
            <Text size="xs" c={(planned || 0) > maxBatch ? "red" : "dimmed"}>
              {planned ?? 0} of {maxBatch} allowed per launch ·{" "}
              {state.limits.concurrency} run at once
            </Text>
            {planCombos !== null && (
              <div className="wb-plan-formula">
                {Math.max(1, planDatasets)} dataset
                {planDatasets === 1 ? "" : "s"} × {planTimeframes} timeframe
                {planTimeframes === 1 ? "" : "s"} × {planCombos} parameter set
                {planCombos === 1 ? "" : "s"}
              </div>
            )}
            <dl className="wb-kv">
              <dt>Script</dt>
              <dd>{strategy ? strategyTitle(strategy.name) : "—"}</dd>
              <dt>Dataset</dt>
              <dd>{dataset ? `${dataset.symbol} · ${short(dataset.id)}` : "—"}</dd>
              <dt>Window (UTC)</dt>
              <dd>
                {input.start} → {input.end}
              </dd>
              <dt>Session</dt>
              <dd>{input.session}</dd>
              <dt>Run purpose</dt>
              <dd>{input.stage}</dd>
              <dt>Capital</dt>
              <dd>${input.capital.toLocaleString()}</dd>
              <dt>Fee</dt>
              <dd>${input.fee}</dd>
              <dt>Slippage</dt>
              <dd>{input.slippage} ticks</dd>
              <dt>Warmup</dt>
              <dd>{input.warmup_days} days</dd>
            </dl>
            <Text size="xs" c="dimmed">
              Every resolved default is saved with each run. Each variant keeps
              its own artifacts and status.
            </Text>
          </aside>
        </div>
      </>
    );
  }

  function scriptsPage(state: State) {
    const library = route.sub === "library";
    const evidence = Object.fromEntries(state.strategies.map(s => [s.id, testingEvidence(s, state.runs, state.evaluations || [], testingMarket)]));
    const testingActions = {
      inspectRun: (id: string) => { const run = state.runs.find(r => r.id === id); if (run) void action(() => inspect(run)); },
      openEvaluation: (id: string) => { setResearchSelection(id); go("evaluations"); },
    };
    return (
      <>
        <PageHeader
          crumb="Sources"
          title="Scripts & library"
          actions={
            <Button
              variant="default"
              size="xs"
              leftSection={<IconRefresh size={14} />}
              onClick={() =>
                void action(async () => {
                  await request("/discover", {});
                  setNotice("Strategy folder scanned.");
                })
              }
            >
              Scan scripts
            </Button>
          }
          tabsLabel="Script views"
          tabs={[
            {
              label: "Runnable scripts",
              count: state.strategies.length,
              active: !library,
              href: href("scripts"),
            },
            {
              label: "Library",
              count: state.library?.total,
              active: library,
              href: href("scripts", "library"),
            },
          ]}
        />
        {alerts}
        <div className="wb-content">
          <Group justify="space-between" align="end" mb="md">
            <Text size="sm" c="dimmed">Most promising first — validation strength, then return / drawdown.</Text>
            <Select label="Testing evidence market" value={testingMarket} onChange={v => setTestingMarket(v || "")}
              data={[{ value: "", label: "All markets" }, ...[...new Set(state.datasets.map(d => d.symbol))].sort().map(symbol => ({ value: symbol, label: symbol }))]} />
          </Group>
          {library ? (
            <StrategyLibrary library={state.library} configure={configure} evidence={evidence} testingActions={testingActions} />
          ) : (
            <>
              <details className="wb-card">
                <summary>Create your next strategy</summary>
                <Text size="sm" mt="xs">
                  Copy <Code>strategies/_template.py</Code> to{" "}
                  <Code>strategies/my_strategy.py</Code>, give it a unique{" "}
                  <Code>STRATEGY['id']</Code>, and implement{" "}
                  <Code>signals(bars, parameters)</Code>. The workbench picks it
                  up automatically within five seconds.
                </Text>
                <Text size="sm" c="dimmed" mt="xs">
                  The template documents signal timing, parameters, and helper
                  imports. Source snapshots preserve registered scripts and
                  local helpers when you launch. Existing scripts can be wrapped
                  by this small adapter.
                </Text>
              </details>
              {state.errors.map((e, i) => (
                <Alert key={i} color="red" title={e.file || "Discovery error"}>
                  {e.error}
                </Alert>
              ))}
              <SimpleGrid cols={{ base: 1, md: 2 }}>
                {[...state.strategies].sort((a, b) => comparePromising(evidence[a.id], evidence[b.id]) || a.name.localeCompare(b.name)).map((s) => (
                  <section className="wb-card" key={s.id}>
                    <Group justify="space-between" wrap="nowrap" align="start">
                      <Title order={3}>{strategyTitle(s.name)}</Title>
                    </Group>
                    <StrategyTesting evidence={evidence[s.id]} {...testingActions} />
                    <details className="script-source-details">
                      <summary>Script details</summary>
                    <Text size="sm" c="dimmed" my="sm">
                      {s.description}
                    </Text>
                    {s.migration_scope && (
                      <Text size="xs" mb="sm">
                        {s.migration_scope}
                      </Text>
                    )}
                    <Text size="xs">
                      <Code>{s.file}</Code> · {short(s.file_hash)}
                    </Text>
                    <Text size="sm" mt="sm">
                      {s.timeframes.join(" · ")}
                    </Text>
                    <Text size="xs" c="dimmed" mt="xs">
                      {Object.keys(s.parameters).join(", ")}
                    </Text>
                    <Text size="xs" mt="sm">
                      Last successful run:{" "}
                      {state.runs
                        .find(
                          (r) =>
                            r.input.strategy.id === s.id &&
                            r.status === "Succeeded",
                        )
                        ?.ended_at?.slice(0, 19)
                        .replace("T", " ") || "No runs yet"}
                    </Text>
                    </details>
                    <Button
                      mt="md"
                      variant="light"
                      rightSection={<IconArrowUpRight size={15} />}
                      onClick={() => configure(s.id)}
                    >
                      Configure run
                    </Button>
                  </section>
                ))}
              </SimpleGrid>
            </>
          )}
        </div>
      </>
    );
  }

  function datasetsPage(state: State) {
    return (
      <>
        <PageHeader
          crumb="Sources"
          title="Datasets"
          actions={
            <Button
              size="xs"
              leftSection={<IconDatabase size={14} />}
              loading={state.import.status === "Running"}
              onClick={() =>
                void action(async () => {
                  await request("/import", {});
                  setNotice("Dataset import started. Progress appears below.");
                })
              }
            >
              Import data ZIPs
            </Button>
          }
        />
        {alerts}
        <div className="wb-content">
          <section className="wb-card">
            <h2>Local archive ingestion</h2>
            <p className="wb-card-sub">
              Import scans ZIP files under data/. Existing versions are reused;
              changed archives create new versions.
            </p>
            {state.import.log && (
              <Code block mt="md" className="wb-log">
                {state.import.log}
              </Code>
            )}
            {state.import.error && (
              <Alert color="red" mt="md">
                {state.import.error}
              </Alert>
            )}
          </section>
          <section className="wb-table-card">
            <ScrollArea>
              <Table miw={1000} verticalSpacing="md">
                <Table.Thead>
                  <Table.Tr>
                    {[
                      "Market / source",
                      "Version",
                      "Coverage (UTC)",
                      "Bars",
                      "Quality",
                      "",
                    ].map((h) => (
                      <Table.Th key={h}>{h}</Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {state.datasets.map((d) => (
                    <Table.Tr key={d.id}>
                      <Table.Td>
                        <Text fw={600}>{d.symbol}</Text>
                        <Text c="dimmed" size="xs">
                          {d.source} · 1m
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Code>{short(d.id)}</Code>
                        <Text size="xs" c="dimmed">
                          {d.registered_at.slice(0, 10)}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">
                          {d.first.slice(0, 10)} → {d.last.slice(0, 10)}
                        </Text>
                        <Text size="xs" c="dimmed">
                          Last bar: {d.last}
                        </Text>
                      </Table.Td>
                      <Table.Td>{d.rows.toLocaleString()}</Table.Td>
                      <Table.Td>
                        <Badge color="yellow" variant="light" radius="xs">
                          Validated with limitations
                        </Badge>
                        <Text size="xs" c="dimmed">
                          {d.quality.gaps_over_one_minute.toLocaleString()} gaps
                          · {d.quality.contract_changes} contract changes
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <details>
                          <summary>Provenance</summary>
                          <Text size="xs">{d.archive}</Text>
                          <Code block>{JSON.stringify(d.quality, null, 2)}</Code>
                          <Text size="xs" className="wb-break">
                            SHA256 {d.checksum}
                          </Text>
                          {d.warnings.map((w) => (
                            <Text key={w} size="xs" mt="xs">
                              {w}
                            </Text>
                          ))}
                        </details>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
            {!state.datasets.length && (
              <div className="wb-empty">
                <Text>
                  No registered datasets. Import the local ZIP archives to
                  begin.
                </Text>
              </div>
            )}
          </section>
        </div>
      </>
    );
  }

  function watchlistPage(state: State) {
    return (
      <>
        <PageHeader crumb="Research" title="Watchlist" actions={refreshButton} />
        {alerts}
        <div className="wb-content">
          <p className="wb-context">
            These are updated historical replays. Freezing a configuration
            records a research choice; it does not establish an edge or
            prospective paper performance.
          </p>
          {!state.watchlist.length && (
            <section className="wb-card">
              <h2>No frozen configurations yet</h2>
              <Text size="sm" c="dimmed" mt="sm">
                Inspect a successful run and record your reason to add it to the
                watchlist.
              </Text>
              <Button
                mt="md"
                variant="light"
                component="a"
                href={href("runs")}
              >
                Open runs
              </Button>
            </section>
          )}
          {state.watchlist.map((w) => {
            const original = state.runs.find((r) => r.id === w.run_id);
            if (!original) return null;
            const snapshots = state.runs.filter((r) => r.watch_id === w.id);
            const latest =
              snapshots.find((r) => r.status === "Succeeded") || original;
            const m = latest.result!.metrics,
              newest = state.datasets
                .filter((d) => d.symbol === original.input.dataset.symbol)
                .sort(
                  (a, b) =>
                    b.last.localeCompare(a.last) ||
                    b.registered_at.localeCompare(a.registered_at),
                )[0];
            const pending = snapshots.find((r) =>
              ["Queued", "Running"].includes(r.status),
            );
            const trackingStatus = pending
              ? pending.status
              : snapshots[0]?.status === "Failed"
                ? "Error"
                : !newest
                  ? "Incomplete"
                  : newest.id !== latest.input.dataset.id ||
                      newest.last.slice(0, 10) > latest.input.end
                    ? "Stale"
                    : "Current";
            const currentMonth = m.last.slice(0, 7),
              previousMonth = new Date(
                Date.UTC(
                  Number(currentMonth.slice(0, 4)),
                  Number(currentMonth.slice(5, 7)) - 2,
                  1,
                ),
              )
                .toISOString()
                .slice(0, 7);
            const recent = (count: number) => {
              const first = new Date(
                Date.UTC(
                  Number(currentMonth.slice(0, 4)),
                  Number(currentMonth.slice(5, 7)) - count - 1,
                  1,
                ),
              )
                .toISOString()
                .slice(0, 7);
              const months = m.monthly.filter(
                (x) => x.month >= first && x.month < currentMonth,
              );
              return months.length === count && m.first.slice(0, 7) < first
                ? months.reduce((value, row) => value * (1 + row.return), 1) -
                    1
                : null;
            };
            return (
              <section key={w.id} className="wb-card">
                <Group justify="space-between" align="start">
                  <Box>
                    <Title order={3}>
                      {strategyTitle(original.input.strategy.name)} ·{" "}
                      {original.input.dataset.symbol}
                    </Title>
                    <Text size="xs" c="dimmed">
                      Frozen {w.frozen_at.slice(0, 10)} · configuration{" "}
                      {short(w.configuration_id)}
                    </Text>
                  </Box>
                  <Badge color={tone(trackingStatus)} radius="xs">
                    {trackingStatus}
                  </Badge>
                </Group>
                <Text my="sm" size="sm">
                  {w.reason}
                </Text>
                <Text size="xs" c="dimmed" mb="md">
                  Covered through {m.last} · source: {w.source} · Current means
                  matching the latest registered data.
                </Text>
                <SimpleGrid cols={{ base: 2, md: 6 }}>
                  {[
                    [
                      "MTD (data month)",
                      pct(
                        latest.input.start <= currentMonth + "-01"
                          ? m.monthly.find((x) => x.month === currentMonth)
                              ?.return
                          : null,
                      ),
                    ],
                    [
                      "Last completed month",
                      pct(
                        latest.input.start <= previousMonth + "-01"
                          ? m.monthly.find((x) => x.month === previousMonth)
                              ?.return
                          : null,
                      ),
                    ],
                    ["Trailing 3 months", pct(recent(3))],
                    ["Trailing 6 months", pct(recent(6))],
                    ["Trailing 12 months", pct(recent(12))],
                    ["Continuous drawdown", pct(m.max_drawdown)],
                  ].map(([label, value]) => (
                    <Box key={label} className="metricBox">
                      <Text size="xs" c="dimmed">
                        {label}
                      </Text>
                      <Text fw={600}>{value}</Text>
                    </Box>
                  ))}
                </SimpleGrid>
                <Text size="xs" c="dimmed" mt="sm">
                  {m.trades} trades · currently {m.current_underwater_bars} bars
                  underwater · recent returns use completed calendar months;
                  unavailable windows stay blank.
                </Text>
                <Group mt="md">
                  <Button
                    variant="light"
                    disabled={!!pending || busy}
                    onClick={() =>
                      void action(async () => {
                        const result = await request<{ status: string }>(
                          `/watchlist/${w.id}/update`,
                          {},
                        );
                        setNotice(
                          result.status === "No new data"
                            ? "No new data. The previous tracking snapshot is unchanged."
                            : "Frozen configuration queued on the latest dataset version.",
                        );
                      })
                    }
                  >
                    Run on latest data
                  </Button>
                  <Button
                    variant="subtle"
                    onClick={() => void action(() => inspect(latest))}
                  >
                    Inspect latest
                  </Button>
                  <Text size="xs" c="dimmed">
                    {snapshots.length} tracking attempts preserved
                  </Text>
                </Group>
                <details className="wb-history">
                  <summary>Snapshot history & selection boundary</summary>
                  <Text size="xs">
                    Data after {original.input.end} is newer than the original
                    selection window. Replay results can still be influenced by
                    later human selection.
                  </Text>
                  {[...snapshots, original].map((r) => (
                    <Button
                      key={r.id}
                      variant="subtle"
                      size="xs"
                      onClick={() => void action(() => inspect(r))}
                    >
                      {short(r.id)} · {r.input.end} · {r.status}
                    </Button>
                  ))}
                </details>
              </section>
            );
          })}
        </div>
      </>
    );
  }

  return (
    <Shell route={route} counts={navCounts} onSearch={search}>
      {page()}
      <Drawer
        opened={!!detail}
        onClose={() => setDetail(null)}
        title="Run evidence"
        position="right"
        size="xl"
      >
        {detail && (
          <Stack>
            <Group justify="space-between">
              <Title order={3}>{strategyTitle(detail.input.strategy.name)}</Title>
              <Badge color={tone(detail.status)}>{detail.status}</Badge>
            </Group>
            <Text size="xs" c="dimmed">
              {detail.id} · {detail.input.stage}
            </Text>
            <Text size="sm">
              {detail.input.dataset.symbol} · {detail.input.timeframe} ·{" "}
              {detail.input.start} → {detail.input.end}
            </Text>
            {detail.error && <Alert color="red">{detail.error}</Alert>}
            <Group>
              <Button
                color="red"
                variant="subtle"
                disabled={["Queued", "Running"].includes(detail.status) || busy}
                onClick={() =>
                  void action(async () =>
                    setDeletion(
                      await request("/runs/delete-preview", {
                        ids: [detail.id],
                      }),
                    ),
                  )
                }
              >
                Delete run
              </Button>
              {["Running", "Queued"].includes(detail.status) && (
                <Button
                  color="red"
                  variant="light"
                  onClick={() =>
                    void action(async () => {
                      await request(`/runs/${detail.id}/cancel`, {});
                      await inspect(detail);
                    })
                  }
                >
                  Cancel run
                </Button>
              )}
              <Button
                variant="light"
                onClick={() =>
                  void action(async () => {
                    await request(`/runs/${detail.id}/retry`, {});
                    setNotice(
                      "A new attempt was created using the preserved inputs.",
                    );
                    setDetail(null);
                  })
                }
              >
                Rerun identical inputs
              </Button>
              <Button variant="subtle" onClick={() => reuse(detail)}>
                Use settings
              </Button>
              <Button
                component="a"
                href={`${API}/runs/${detail.id}/export`}
                target="_blank"
                variant="subtle"
              >
                Export evidence JSON
              </Button>
            </Group>
            {detail.result && (
              <>
                <SimpleGrid cols={3}>
                  {[
                    ["Net return", pct(detail.result.metrics.net_return)],
                    ["Drawdown", pct(detail.result.metrics.max_drawdown)],
                    ["Closed trades", num(detail.result.metrics.trades)],
                    ["Net P&L (USD)", num(detail.result.metrics.net_pnl)],
                    ["Costs (USD)", num(detail.result.metrics.costs)],
                    ["Daily Sharpe", num(detail.result.metrics.sharpe)],
                  ].map(([label, value]) => (
                    <Box key={label} className="metricBox">
                      <Text size="xs" c="dimmed">
                        {label}
                      </Text>
                      <Text fw={600}>{value}</Text>
                    </Box>
                  ))}
                </SimpleGrid>
                <EquityChart run={detail} />
                <Text size="xs" c="dimmed">
                  {detail.result.metrics.basis}
                </Text>
                <Text size="xs" c="dimmed">
                  {detail.result.metrics.undefined_reason}
                </Text>
                <details>
                  <summary>Monthly returns</summary>
                  <Table>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Month</Table.Th>
                        <Table.Th>Net return</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {detail.result.metrics.monthly.map((m) => (
                        <Table.Tr key={m.month}>
                          <Table.Td>{m.month}</Table.Td>
                          <Table.Td>{pct(m.return)}</Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </details>
                <details>
                  <summary>Trades (first 100; full ledger downloadable)</summary>
                  <Code block className="wb-log">
                    {JSON.stringify(detail.result.trade_preview, null, 2)}
                  </Code>
                </details>
                <Alert color="yellow" title="Evidence limitations">
                  <Stack gap="xs">
                    {detail.result.warnings.map((w) => (
                      <Text key={w} size="xs">
                        {w}
                      </Text>
                    ))}
                  </Stack>
                </Alert>
                <Group>
                  {detail.result.artifacts.map((a) => (
                    <Button
                      component="a"
                      key={a.name}
                      href={`${API}/runs/${detail.id}/artifact?name=${a.name}`}
                      variant="light"
                      size="xs"
                    >
                      {a.name}
                    </Button>
                  ))}
                </Group>
                <Textarea
                  label="Reason for freezing this configuration"
                  value={reason}
                  onChange={(e) => setReason(e.currentTarget.value)}
                />
                <Button
                  leftSection={<IconStar size={16} />}
                  variant="light"
                  disabled={!reason.trim() || busy}
                  onClick={() =>
                    void action(async () => {
                      await request("/watchlist", {
                        run_id: detail.id,
                        reason,
                      });
                      setNotice("Configuration frozen in the watchlist.");
                      setReason("");
                    })
                  }
                >
                  Freeze in watchlist
                </Button>
              </>
            )}
            <Textarea
              label="Research notes"
              value={notes}
              onChange={(e) => setNotes(e.currentTarget.value)}
            />
            <TextInput
              label="Tags"
              value={tags}
              onChange={(e) => setTags(e.currentTarget.value)}
            />
            <Button
              variant="light"
              onClick={() =>
                void action(async () => {
                  await request(`/runs/${detail.id}`, { notes, tags }, "PATCH");
                  setNotice("Notes and tags saved.");
                })
              }
            >
              Save notes
            </Button>
            <details>
              <summary>Exact inputs & lineage</summary>
              <Code block className="wb-log">
                {JSON.stringify(detail.input, null, 2)}
              </Code>
            </details>
            <details open>
              <summary>Process log</summary>
              <Code block className="wb-log">
                {detail.log || "Waiting for process output…"}
              </Code>
            </details>
          </Stack>
        )}
      </Drawer>
      <Modal
        opened={!!deletion}
        onClose={() => setDeletion(null)}
        title="Review run deletion"
        centered
      >
        {deletion && (
          <Stack>
            <Text>{deletion.explanation}</Text>
            <Text>
              {Object.entries(deletion.counts)
                .map(([name, count]) => `${count} ${name}`)
                .join(" · ")}
            </Text>
            <Alert color="yellow">
              Deletion removes these records from the app. Deleting losing
              trials changes the visible research history; keep them when
              assessing an optimization.
            </Alert>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setDeletion(null)}>
                Keep runs
              </Button>
              <Button
                color="red"
                loading={busy}
                onClick={() =>
                  void action(async () => {
                    const result = await request<{
                      backup: string;
                      counts: { runs: number };
                      warnings: string[];
                    }>("/runs/delete", {
                      ids: deletion.ids,
                      token: deletion.token,
                    });
                    setDeletion(null);
                    setDetail(null);
                    setSelected([]);
                    setComparison(null);
                    setNotice(
                      `${result.counts.runs} runs deleted. Local backup: ${result.backup}${result.warnings.length ? " · " + result.warnings.join("; ") : ""}`,
                    );
                  })
                }
              >
                Delete reviewed runs
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Shell>
  );
}
