import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Box,
  Button,
  Checkbox,
  Code,
  Container,
  Drawer,
  Group,
  NumberInput,
  MultiSelect,
  Modal,
  Paper,
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
  IconArrowUpRight,
  IconCode,
  IconDatabase,
  IconFlask,
  IconPlayerPlay,
  IconRefresh,
  IconStar,
} from "@tabler/icons-react";
import "./workbench.css";
import { ResearchPage, type EvaluationView, type RegimeView } from "./Research";
import { StrategyLibrary, type Library } from "./StrategyLibrary";
import { StrategyDashboard } from "./StrategyDashboard";

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
export type Run = {
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
    equity_preview: { timestamp: string; equity: number; drawdown?: number }[];
    trade_preview: Record<string, unknown>[];
    artifacts: { name: string }[];
  };
};
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
  runs: Run[];
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
  const [tab, setTab] = useState("Runs & Compare");
  const [researchSelection, setResearchSelection] = useState<string>();
  const [dashboardRefresh, setDashboardRefresh] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState<Input>(initial);
  const [sweepText, setSweepText] = useState("{}");
  const [preview, setPreview] = useState<number | null>(null);
  const [filter, setFilter] = useState("");
  const [stage, setStage] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("Newest");
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [detail, setDetail] = useState<Run | null>(null);
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [reason, setReason] = useState("");
  const [presetName, setPresetName] = useState("");
  const [viewName, setViewName] = useState("");
  const refresh = useCallback(async () => {
    try {
      setState(await request<State>("/state"));
    } catch (e) {
      setError(String(e));
    }
  }, []);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 2000);
    return () => clearInterval(timer);
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
  async function inspect(run: Run) {
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
    setTab("New Run");
  }
  const strategy = state?.strategies.find((s) => s.id === input.strategy_id);
  const dataset = state?.datasets.find((d) => d.id === input.dataset_id);
  const filtered = (state?.runs || [])
    .filter(
      (r) =>
        (!stage || r.input.stage === stage) &&
        (!status || r.status === status) &&
        `${r.input.strategy.name} ${r.input.dataset.symbol} ${r.id} ${r.tags || ""} ${r.input.hypothesis}`
          .toLowerCase()
          .includes(filter.toLowerCase()),
    )
    .sort((a, b) =>
      sort === "Oldest"
        ? a.created_at.localeCompare(b.created_at)
        : sort === "Strategy"
          ? a.input.strategy.name.localeCompare(b.input.strategy.name)
          : b.created_at.localeCompare(a.created_at),
    );
  const compareRuns =
    comparison?.runs ||
    (comparison?.rows || [])
      .map((row) => state?.runs.find((r) => r.id === row.id))
      .filter((r): r is Run => !!r);
  const counts = {
    total: state?.runs.length || 0,
    active:
      state?.runs.filter((r) => ["Running", "Queued"].includes(r.status))
        .length || 0,
    success: state?.runs.filter((r) => r.status === "Succeeded").length || 0,
  };
  return (
    <div className="wb">
      <header className="wb-header">
        <Container size={1440}>
          <Group justify="space-between">
            <Group gap="sm">
              <div className="wb-mark">
                <IconFlask size={23} />
              </div>
              <div>
                <Text className="wb-brand">Strategy Workbench</Text>
                <Text size="xs" c="#9fc7bb">
                  Local research · reproducible experiments
                </Text>
              </div>
            </Group>
            <Badge variant="outline" color="teal.2">
              Historical simulation
            </Badge>
          </Group>
        </Container>
      </header>
      <div className="wb-nav">
        <Container size={1440}>
          <Group gap={26}>
            {[
              "Dashboard",
              "Runs & Compare",
              "New Run",
              "Scripts",
              "Datasets",
              "Watchlist",
              "Evaluation & Regimes",
            ].map((name) => (
              <button
                key={name}
                className={tab === name ? "active" : ""}
                onClick={() => setTab(name)}
              >
                {name}
              </button>
            ))}
          </Group>
        </Container>
      </div>
      <Container size={1440} py="xl">
        {error && (
          <Alert
            color="red"
            title="Action could not complete"
            mb="md"
            withCloseButton
            onClose={() => setError("")}
          >
            {error}
          </Alert>
        )}
        {notice && (
          <Alert
            color="teal"
            mb="md"
            withCloseButton
            onClose={() => setNotice("")}
          >
            {notice}
          </Alert>
        )}
        {!state ? (
          <Paper p="xl">
            Connecting to the workbench… Start with{" "}
            <Code>npm run dev:full</Code>.
          </Paper>
        ) : (
          <>
            <Group justify="space-between" align="flex-end" mb="xl">
              <Box>
                <Text className="eyebrow">RESEARCH / {tab.toUpperCase()}</Text>
                <Title order={1} mt={7}>
                  {tab === "Dashboard"
                    ? "Your strategies, in perspective."
                    : tab === "Runs & Compare"
                      ? "Every experiment, in context."
                      : tab === "New Run"
                        ? "Turn a question into a run."
                        : tab === "Scripts"
                          ? "Your Python, ready to run."
                          : tab === "Datasets"
                            ? "Know the data behind the result."
                            : tab === "Evaluation & Regimes"
                              ? "Earlier evidence. Later tests."
                              : "Frozen rules. Continuing observation."}
                </Title>
                <Text c="dimmed" size="sm" mt="xs">
                  {tab === "Dashboard"
                    ? "Profit, risk, and the evidence behind each research candidate."
                    : tab === "Runs & Compare"
                      ? "Follow the queue, inspect the evidence, and compare like with like."
                      : tab === "New Run"
                        ? "Choose preserved data, declare assumptions, and preview your experiment before launching."
                        : tab === "Scripts"
                          ? "Drop a strategy into the local folder. Its schema becomes the run form automatically."
                          : tab === "Datasets"
                            ? "Versioned local archives with coverage, checksums, and visible limitations."
                            : tab === "Evaluation & Regimes"
                              ? "Chronological selection, sensitivity, implementation stress, and declared market states."
                              : "Updated historical replays preserve code, parameters, sizing, and costs."}
                </Text>
              </Box>
              <Button
                variant="subtle"
                leftSection={<IconRefresh size={16} />}
                onClick={() => {
                  void refresh();
                  setDashboardRefresh((value) => value + 1);
                }}
              >
                Refresh
              </Button>
            </Group>
            {tab === "Dashboard" && (
              <StrategyDashboard
                refreshKey={dashboardRefresh}
                openEvaluation={(id) => {
                  setResearchSelection(id);
                  setTab("Evaluation & Regimes");
                }}
                inspectRun={(id) => {
                  const run = state.runs.find((r) => r.id === id);
                  if (run) void action(() => inspect(run));
                }}
              />
            )}
            {tab === "Evaluation & Regimes" && (
              <ResearchPage
                initialSelected={researchSelection}
                runs={state.runs}
                evaluations={state.evaluations || []}
                regimes={state.regimes || []}
                refresh={refresh}
                inspect={(run) => void action(() => inspect(run))}
              />
            )}
            {tab === "Runs & Compare" && (
              <>
                <SimpleGrid cols={{ base: 2, md: 4 }} mb="xl">
                  {[
                    [counts.total, "RECORDED RUNS"],
                    [counts.active, "QUEUED / RUNNING"],
                    [counts.success, "SUCCEEDED"],
                    [state.datasets.length, "DATASET VERSIONS"],
                  ].map(([value, label]) => (
                    <Paper key={label} className="wb-stat" withBorder>
                      <Text className="eyebrow">{label}</Text>
                      <Text className="wb-stat-value">{value}</Text>
                    </Paper>
                  ))}
                </SimpleGrid>
                <Paper p="lg" withBorder>
                  <Group justify="space-between" mb="lg">
                    <div>
                      <Title order={3}>Run ledger</Title>
                      <Text size="xs" c="dimmed">
                        {state.limits.concurrency} workers · up to{" "}
                        {state.limits.maxBatch} jobs per launch · execution and
                        research stage stay separate
                      </Text>
                    </div>
                    <Button
                      leftSection={<IconPlayerPlay size={15} />}
                      onClick={() => setTab("New Run")}
                    >
                      New experiment
                    </Button>
                  </Group>
                  <Group mb="md" align="end">
                    <TextInput
                      label="Search runs"
                      placeholder="Strategy, market, tags, or run ID"
                      value={filter}
                      onChange={(e) => setFilter(e.currentTarget.value)}
                      style={{ flex: 1, minWidth: 230 }}
                    />
                    <Select
                      label="Research stage"
                      placeholder="All stages"
                      clearable
                      data={["Exploratory", "Evaluation", "Tracking"]}
                      value={stage || null}
                      onChange={(v) => setStage(v || "")}
                    />
                    <Select
                      label="Execution"
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
                      label="Sort"
                      data={["Newest", "Oldest", "Strategy"]}
                      value={sort}
                      onChange={(v) => setSort(v || "Newest")}
                    />
                  </Group>
                  <Group mb="md">
                    <Select
                      aria-label="Saved view"
                      placeholder="Saved views"
                      data={state.views.map((v) => ({
                        value: v.id,
                        label: v.name,
                      }))}
                      onChange={(id) => {
                        const v = state.views.find((v) => v.id === id);
                        if (v) {
                          setFilter(v.filter);
                          setStage(v.stage);
                          setStatus(v.status);
                        }
                      }}
                    />
                    <TextInput
                      aria-label="View name"
                      placeholder="Name this view"
                      value={viewName}
                      onChange={(e) => setViewName(e.currentTarget.value)}
                    />
                    <Button
                      variant="subtle"
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
                        })
                      }
                    >
                      Save view
                    </Button>
                  </Group>
                  <ScrollArea>
                    <Table miw={1150} highlightOnHover verticalSpacing="md">
                      <Table.Thead>
                        <Table.Tr>
                          {[
                            "",
                            "Strategy / run",
                            "Data / window",
                            "Stage",
                            "Execution",
                            "Net return",
                            "Drawdown",
                            "Trades",
                            "Runtime",
                            "",
                          ].map((x, i) => (
                            <Table.Th key={i}>{x}</Table.Th>
                          ))}
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {filtered.map((run) => (
                          <Table.Tr key={run.id}>
                            <Table.Td>
                              <Checkbox
                                aria-label={`Compare ${run.id}`}
                                disabled={["Queued", "Running"].includes(
                                  run.status,
                                )}
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
                                {run.input.strategy.name}
                              </Text>
                              <Text size="xs" c="dimmed">
                                {short(run.id)} · code{" "}
                                {short(run.input.source_hash)}
                              </Text>
                              {run.tags && <Text size="xs">{run.tags}</Text>}
                            </Table.Td>
                            <Table.Td>
                              <Text size="sm">
                                {run.input.dataset.symbol} ·{" "}
                                {run.input.timeframe}
                              </Text>
                              <Text size="xs" c="dimmed">
                                {run.input.start} → {run.input.end}
                              </Text>
                            </Table.Td>
                            <Table.Td>
                              <Badge
                                color={
                                  run.input.stage === "Evaluation"
                                    ? "violet"
                                    : "gray"
                                }
                                variant="light"
                              >
                                {run.input.stage}
                              </Badge>
                            </Table.Td>
                            <Table.Td>
                              <Badge color={tone(run.status)} variant="light">
                                {run.status}
                              </Badge>
                            </Table.Td>
                            <Table.Td className="mono">
                              {pct(run.result?.metrics.net_return)}
                            </Table.Td>
                            <Table.Td className="mono">
                              {pct(run.result?.metrics.max_drawdown)}
                            </Table.Td>
                            <Table.Td>
                              {num(run.result?.metrics.trades)}
                            </Table.Td>
                            <Table.Td>
                              {run.started_at
                                ? `${Math.max(0, (Date.parse(run.ended_at || new Date().toISOString()) - Date.parse(run.started_at)) / 1000).toFixed(1)}s`
                                : "—"}
                            </Table.Td>
                            <Table.Td>
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
                        onClick={() =>
                          setTab(state.datasets.length ? "New Run" : "Datasets")
                        }
                      >
                        {state.datasets.length
                          ? "Configure a run"
                          : "Open datasets"}
                      </Button>
                    </div>
                  )}
                  <Group mt="md">
                    <Button
                      color="red"
                      variant="subtle"
                      disabled={!selected.length || busy}
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
                    </Button>
                    <Button
                      color="red"
                      variant="subtle"
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
                    </Button>
                    <Text size="sm" c="dimmed">
                      {selected.length} selected
                    </Text>
                    <Button
                      variant="light"
                      disabled={
                        selected.length < 2 ||
                        selected.length > 8 ||
                        busy ||
                        selected.some(
                          (id) =>
                            state.runs.find((r) => r.id === id)?.status !==
                            "Succeeded",
                        )
                      }
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
                    </Button>
                    <Button
                      variant="light"
                      disabled={
                        selected.length < 2 ||
                        selected.length > 8 ||
                        busy ||
                        selected.some(
                          (id) =>
                            state.runs.find((r) => r.id === id)?.status !==
                            "Succeeded",
                        )
                      }
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
                    </Button>
                  </Group>
                </Paper>
                {comparison && (
                  <Paper p="lg" withBorder mt="lg">
                    <Title order={3}>{comparison.mode} comparison</Title>
                    <Text size="sm" c="dimmed" my="sm">
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
                                return ["net_return", "max_drawdown"].includes(
                                  key,
                                )
                                  ? pct(val as number)
                                  : num(val as number);
                              }
                              if (key === "window")
                                return `${r.input.start} → ${r.input.end}`;
                              if (key === "dataset")
                                return short(r.input.dataset.id);
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
                      Highlighted rows differ. Undefined statistics are shown as
                      —.
                    </Text>
                  </Paper>
                )}
                <Paper p="lg" withBorder mt="lg">
                  <Title order={3}>Experiment history</Title>
                  <Text size="sm" c="dimmed" mb="sm">
                    All attempted variants remain recorded, including failed and
                    losing runs.
                  </Text>
                  {state.experiments.slice(0, 10).map((e) => (
                    <Group
                      key={e.id}
                      justify="space-between"
                      className="wb-history"
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
                </Paper>
              </>
            )}
            {tab === "New Run" && (
              <SimpleGrid cols={{ base: 1, md: 2 }} spacing="xl">
                <Paper p="lg" withBorder>
                  <Stack>
                    <Title order={3}>1. Script & dataset</Title>
                    <Select
                      label="Strategy"
                      placeholder="Choose a Python strategy"
                      data={state.strategies.map((s) => ({
                        value: s.id,
                        label: s.name,
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
                    <SimpleGrid cols={2}>
                      <Select
                        label="Timeframe"
                        data={strategy?.timeframes || []}
                        value={input.timeframe}
                        onChange={(v) => v && change("timeframe", v)}
                      />
                      <Select
                        label="Session"
                        data={[
                          { value: "new-york-rth", label: "New York RTH" },
                          {
                            value: "full-trading-day",
                            label: "Full Globex day",
                          },
                          { value: "london", label: "London" },
                          { value: "asia", label: "Tokyo" },
                        ]}
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
                    <Title order={3} mt="md">
                      2. Parameters
                    </Title>
                    {strategy ? (
                      Object.entries(strategy.parameters).map(([key, field]) =>
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
                      )
                    ) : (
                      <Text size="sm" c="dimmed">
                        Choose a script to load its parameter schema.
                      </Text>
                    )}
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
                    <Group align="end">
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
                  </Stack>
                </Paper>
                <Paper p="lg" withBorder>
                  <Stack>
                    <Title order={3}>3. Assumptions & research record</Title>
                    <SimpleGrid cols={2}>
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
                      Final positions close at the final bar close. No cash
                      flows.
                    </Text>
                    <Select
                      label="Research stage"
                      data={["Exploratory", "Evaluation"]}
                      value={input.stage}
                      onChange={(v) => v && change("stage", v)}
                    />
                    <Textarea
                      label="Question / hypothesis"
                      placeholder="What does this experiment test?"
                      value={input.hypothesis}
                      onChange={(e) =>
                        change("hypothesis", e.currentTarget.value)
                      }
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
                      onChange={(e) =>
                        change("criteria", e.currentTarget.value)
                      }
                    />
                    <Title order={3} mt="md">
                      4. Preview & launch
                    </Title>
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
                      description="Datasets × timeframes × parameter combinations form the batch."
                      data={(strategy?.timeframes || []).filter(
                        (tf) => tf !== input.timeframe,
                      )}
                      value={(input.timeframes || []).filter(
                        (tf) => tf !== input.timeframe,
                      )}
                      onChange={(v) => change("timeframes", v)}
                    />
                    <Textarea
                      label="Parameter sweep (JSON)"
                      description={
                        'Use {} for a single run, or {"lookback": [10, 20, 40]} for a grid.'
                      }
                      autosize
                      minRows={3}
                      value={sweepText}
                      onChange={(e) => {
                        setSweepText(e.currentTarget.value);
                        setPreview(null);
                      }}
                    />
                    <Text size="xs" c="dimmed">
                      Maximum {state.limits.maxBatch} jobs per batch ·{" "}
                      {state.limits.concurrency} concurrent workers. Each
                      variant keeps its own artifacts and status.
                    </Text>
                    <Button
                      variant="light"
                      loading={busy}
                      onClick={() =>
                        void action(async () => {
                          const result = await request<{ jobs: number }>(
                            "/preview",
                            runInput(),
                          );
                          setPreview(result.jobs);
                        })
                      }
                    >
                      Validate & preview
                    </Button>
                    {preview !== null && (
                      <Alert
                        color="teal"
                        title={`${preview} job${preview === 1 ? "" : "s"} ready`}
                      >
                        Inputs passed preflight. Launching preserves this
                        experiment's code and resolved parameters.
                      </Alert>
                    )}
                    <Button
                      size="md"
                      leftSection={<IconPlayerPlay size={17} />}
                      disabled={preview === null || busy}
                      onClick={() =>
                        void action(async () => {
                          const runs = await request<Run[]>(
                            "/runs",
                            runInput(),
                          );
                          setNotice(
                            `${runs.length} run(s) queued. You can leave this page while they execute.`,
                          );
                          setPreview(null);
                          setTab("Runs & Compare");
                        })
                      }
                    >
                      Launch {preview || ""} {preview === 1 ? "run" : "runs"}
                    </Button>
                  </Stack>
                </Paper>
              </SimpleGrid>
            )}
            {tab === "Scripts" && (
              <>
                <Paper p="lg" withBorder mb="lg">
                  <Group align="flex-start">
                    <IconCode size={25} />
                    <Box style={{ flex: 1 }}>
                      <Title order={3}>Create your next strategy</Title>
                      <Text size="sm" mt="xs">
                        Copy <Code>strategies/_template.py</Code> to{" "}
                        <Code>strategies/my_strategy.py</Code>, give it a unique{" "}
                        <Code>STRATEGY['id']</Code>, and implement{" "}
                        <Code>signals(bars, parameters)</Code>. The workbench
                        picks it up automatically within five seconds.
                      </Text>
                      <Text size="sm" c="dimmed" mt="xs">
                        The template documents signal timing, parameters, and
                        helper imports. Source snapshots preserve registered
                        scripts and local helpers when you launch. Existing
                        scripts can be wrapped by this small adapter.
                      </Text>
                    </Box>
                    <Button
                      variant="light"
                      onClick={() =>
                        void action(async () => {
                          await request("/discover", {});
                          setNotice("Strategy folder scanned.");
                        })
                      }
                    >
                      Scan scripts
                    </Button>
                  </Group>
                </Paper>
                {state.errors.map((e, i) => (
                  <Alert
                    key={i}
                    color="red"
                    mb="md"
                    title={e.file || "Discovery error"}
                  >
                    {e.error}
                  </Alert>
                ))}
                <SimpleGrid cols={{ base: 1, md: 2 }}>
                  {state.strategies.map((s) => (
                    <Paper p="lg" withBorder key={s.id}>
                      <Group justify="space-between">
                        <Title order={3}>{s.name}</Title>
                        <Badge color="teal" variant="light">
                          v{s.version}
                        </Badge>
                      </Group>
                      <Text size="sm" c="dimmed" my="md">
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
                      <Button
                        mt="lg"
                        variant="light"
                        rightSection={<IconArrowUpRight size={15} />}
                        onClick={() => {
                          chooseStrategy(s.id);
                          setTab("New Run");
                        }}
                      >
                        Configure run
                      </Button>
                    </Paper>
                  ))}
                </SimpleGrid>
                <StrategyLibrary
                  library={state.library}
                  configure={(id) => {
                    chooseStrategy(id);
                    setTab("New Run");
                  }}
                />
              </>
            )}
            {tab === "Datasets" && (
              <>
                <Paper p="lg" withBorder mb="lg">
                  <Group justify="space-between">
                    <Group>
                      <IconDatabase size={26} />
                      <Box>
                        <Title order={3}>Local archive ingestion</Title>
                        <Text c="dimmed" size="sm">
                          Scan ZIP files under data/. Existing versions are
                          reused; changed archives create new versions.
                        </Text>
                      </Box>
                    </Group>
                    <Button
                      loading={state.import.status === "Running"}
                      onClick={() =>
                        void action(async () => {
                          await request("/import", {});
                          setNotice(
                            "Dataset import started. Progress appears below.",
                          );
                        })
                      }
                    >
                      Import data ZIPs
                    </Button>
                  </Group>
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
                </Paper>
                <Paper p="lg" withBorder>
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
                              <Badge color="yellow" variant="light">
                                Validated with limitations
                              </Badge>
                              <Text size="xs" c="dimmed">
                                {d.quality.gaps_over_one_minute.toLocaleString()}{" "}
                                gaps · {d.quality.contract_changes} contract
                                changes
                              </Text>
                            </Table.Td>
                            <Table.Td>
                              <details>
                                <summary>Provenance</summary>
                                <Text size="xs">{d.archive}</Text>
                                <Code block>
                                  {JSON.stringify(d.quality, null, 2)}
                                </Code>
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
                </Paper>
              </>
            )}
            {tab === "Watchlist" && (
              <>
                <Alert color="blue" mb="lg">
                  These are updated historical replays. Freezing a configuration
                  records a research choice; it does not establish an edge or
                  prospective paper performance.
                </Alert>
                {!state.watchlist.length && (
                  <Paper p="xl" withBorder>
                    <Title order={3}>No frozen configurations yet</Title>
                    <Text size="sm" c="dimmed" mt="sm">
                      Inspect a successful run and record your reason to add it
                      to the watchlist.
                    </Text>
                  </Paper>
                )}
                {state.watchlist.map((w) => {
                  const original = state.runs.find((r) => r.id === w.run_id);
                  if (!original) return null;
                  const snapshots = state.runs.filter(
                    (r) => r.watch_id === w.id,
                  );
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
                    return months.length === count &&
                      m.first.slice(0, 7) < first
                      ? months.reduce(
                          (value, row) => value * (1 + row.return),
                          1,
                        ) - 1
                      : null;
                  };
                  return (
                    <Paper key={w.id} p="lg" withBorder mb="lg">
                      <Group justify="space-between">
                        <Box>
                          <Title order={3}>
                            {original.input.strategy.name} ·{" "}
                            {original.input.dataset.symbol}
                          </Title>
                          <Text size="xs" c="dimmed">
                            Frozen {w.frozen_at.slice(0, 10)} · configuration{" "}
                            {short(w.configuration_id)}
                          </Text>
                        </Box>
                        <Badge color={tone(trackingStatus)}>
                          {trackingStatus}
                        </Badge>
                      </Group>
                      <Text my="sm" size="sm">
                        {w.reason}
                      </Text>
                      <Text size="xs" c="dimmed" mb="md">
                        Covered through {m.last} · source: {w.source} · Current
                        means matching the latest registered data.
                      </Text>
                      <SimpleGrid cols={{ base: 2, md: 6 }}>
                        {[
                          [
                            "MTD (data month)",
                            pct(
                              latest.input.start <= currentMonth + "-01"
                                ? m.monthly.find(
                                    (x) => x.month === currentMonth,
                                  )?.return
                                : null,
                            ),
                          ],
                          [
                            "Last completed month",
                            pct(
                              latest.input.start <= previousMonth + "-01"
                                ? m.monthly.find(
                                    (x) => x.month === previousMonth,
                                  )?.return
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
                        {m.trades} trades · currently{" "}
                        {m.current_underwater_bars} bars underwater · recent
                        returns use completed calendar months; unavailable
                        windows stay blank.
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
                          Data after {original.input.end} is newer than the
                          original selection window. Replay results can still be
                          influenced by later human selection.
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
                    </Paper>
                  );
                })}
              </>
            )}
          </>
        )}
        <Text size="xs" c="dimmed" mt="xl">
          Local Strategy Workbench · Source, data, assumptions, and outcomes
          stay together. Research results are descriptive.
        </Text>
      </Container>
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
              <Title order={3}>{detail.input.strategy.name}</Title>
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
                  <summary>
                    Trades (first 100; full ledger downloadable)
                  </summary>
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
    </div>
  );
}
