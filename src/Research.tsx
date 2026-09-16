import { useState, type ReactNode } from "react";
import {
  Alert,
  Badge,
  Box,
  Button,
  Code,
  Drawer,
  Group,
  NumberInput,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconPlus, IconSearch } from "@tabler/icons-react";
import type { Run } from "./Workbench";
import { PageHeader } from "./Shell";

type Metrics = {
  net_return: number;
  max_drawdown: number;
  trades: number;
  costs: number;
  sharpe: number | null;
  net_pnl: number;
};
type Fold = {
  index: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  training: string[];
  tests: string[];
  selection?: {
    run_id: string;
    candidate: number;
    score: number;
    selected_at: string;
    permitted_through: string;
    ranked: {
      run_id: string;
      candidate: number;
      score: number | null;
      eligible: boolean;
    }[];
  };
};
export type EvaluationView = {
  note?: string;
  id: string;
  name: string;
  status: string;
  created_at: string;
  folds: Fold[];
  jobs: number;
  metric: string;
  source_hash: string;
  inspected_overlap: string[];
  error?: string;
  outcome?: string;
  hypothesis?: string;
  min_trades?: number;
  min_test_trades?: number;
  min_return?: number;
  max_drawdown?: number;
  stress_multiple?: number;
  delay_bars?: number;
  candidates: { parameters: Record<string, unknown> }[];
  result?: {
    scenarios: {
      name: string;
      metrics: Metrics;
      outcome: string;
      equity_preview: { timestamp: string; equity: number }[];
    }[];
    boundary: string;
    warnings: string[];
  };
};
export type RegimeView = {
  id: string;
  evaluation_id: string;
  status: string;
  feature: string;
  window: number;
  error?: string;
  result?: {
    source: string;
    formula: string;
    states: {
      state: string;
      observations: number;
      episodes: number;
      net_pnl: number;
      costs: number;
      invested_bar_fraction: number;
      entry_count: number;
      mean_episode_pnl: number;
      mean_episode_pnl_interval_95: number[] | null;
      evidence: string;
    }[];
    thresholds: {
      fold: number;
      threshold: number;
      training_observations: number;
      calibrated_through: string;
    }[];
    warnings: string[];
  };
};
const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${(v * 100).toFixed(2)}%`;
const number = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
const color = (status: string) =>
  status === "Succeeded"
    ? "teal"
    : ["Failed", "Interrupted"].includes(status)
      ? "red"
      : "blue";
const outcomeColor = (outcome?: string) =>
  outcome === "Meets criteria"
    ? "teal"
    : outcome === "Does not meet criteria"
      ? "red"
      : "gray";
async function send<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch("/api/workbench" + url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}
function Downloads({
  id,
  kind,
  names,
}: {
  id: string;
  kind: string;
  names: string[];
}) {
  return (
    <Group gap="xs">
      {names.map((name) => (
        <Button
          key={name}
          component="a"
          size="xs"
          variant="light"
          href={`/api/workbench/research-artifact?kind=${kind}&id=${id}&name=${name}`}
        >
          {name}
        </Button>
      ))}
    </Group>
  );
}

const DETAIL_TABS = [
  "Summary",
  "Fold selection & sensitivity",
  "Joined test path",
  "Regime study",
] as const;

export function ResearchPage({
  selectedId,
  onSelect,
  alerts,
  runs,
  evaluations,
  regimes,
  refresh,
  inspect,
}: {
  selectedId?: string;
  onSelect: (id: string) => void;
  alerts?: ReactNode;
  runs: Run[];
  evaluations: EvaluationView[];
  regimes: RegimeView[];
  refresh: () => Promise<void>;
  inspect: (run: Run) => void;
}) {
  const isMobile = useMediaQuery("(max-width: 900px)");
  const [planOpen, setPlanOpen] = useState(false);
  const [seedId, setSeedId] = useState("");
  const [name, setName] = useState("Rolling trend evaluation");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [train, setTrain] = useState(60);
  const [test, setTest] = useState(30);
  const [folds, setFolds] = useState(3);
  const [metric, setMetric] = useState("net_pnl");
  const [minTrades, setMinTrades] = useState(1);
  const [minTest, setMinTest] = useState(10);
  const [minReturn, setMinReturn] = useState(0);
  const [maxDrawdown, setMaxDrawdown] = useState(20);
  const [cost, setCost] = useState(2);
  const [delay, setDelay] = useState(1);
  const [sweep, setSweep] = useState('{"lookback": [10, 20, 40]}');
  const [hypothesis, setHypothesis] = useState("");
  const [preview, setPreview] = useState<{
    jobs: number;
    folds: Fold[];
  } | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feature, setFeature] = useState("volatility");
  const [window, setWindow] = useState(20);
  const [quantile, setQuantile] = useState(0.5);
  const [outcomeFilter, setOutcomeFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<(typeof DETAIL_TABS)[number]>("Summary");
  const seed = runs.find((r) => r.id === seedId),
    current = evaluations.find((e) => e.id === selectedId) || evaluations[0];
  const key = JSON.stringify([
    seedId,
    start,
    end,
    name,
    train,
    test,
    folds,
    metric,
    minTrades,
    minTest,
    minReturn,
    maxDrawdown,
    cost,
    delay,
    sweep,
    hypothesis,
  ]);
  const validPreview = preview && key === previewKey;
  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  function payload() {
    if (!seed)
      throw new Error("Choose a successful run as the starting configuration");
    return {
      name,
      base: {
        ...seed.input,
        strategy_id: seed.input.strategy.id,
        dataset_id: seed.input.dataset.id,
        start,
        end,
      },
      sweep: JSON.parse(sweep),
      train_days: train,
      test_days: test,
      folds,
      metric,
      min_trades: minTrades,
      min_test_trades: minTest,
      min_return: minReturn / 100,
      max_drawdown: maxDrawdown / 100,
      stress_multiple: cost,
      delay_bars:
        seed.input.strategy.execution_model === "event-v1" ? 0 : delay,
      hypothesis,
    };
  }
  function chooseSeed(id: string | null) {
    const run = runs.find((r) => r.id === id);
    if (!run) return;
    setSeedId(run.id);
    setEnd(run.input.end);
    const suggested = new Date(
      Date.parse(run.input.end) - (train + test * folds - 1) * 86400000,
    )
      .toISOString()
      .slice(0, 10);
    setStart(
      suggested < run.input.dataset.first.slice(0, 10)
        ? run.input.dataset.first.slice(0, 10)
        : suggested,
    );
    const field = Object.keys(run.input.parameters).find(
      (k) => k === "lookback",
    );
    setSweep(field ? '{"lookback": [10, 20, 40]}' : "{}");
    setPreview(null);
  }
  const runLink = (id: string) => {
    const run = runs.find((r) => r.id === id);
    return (
      <Button
        key={id}
        size="compact-xs"
        variant="subtle"
        onClick={() => run && inspect(run)}
      >
        {id.slice(0, 8)} · {run?.status || "Loading"}
      </Button>
    );
  };
  const meets = evaluations.filter((e) => e.outcome === "Meets criteria");
  const fails = evaluations.filter(
    (e) => e.outcome === "Does not meet criteria",
  );
  const listed = (
    outcomeFilter === "meets"
      ? meets
      : outcomeFilter === "fails"
        ? fails
        : evaluations
  ).filter((e) => e.name.toLowerCase().includes(query.toLowerCase()));

  const planForm = (
    <Stack gap="lg">
      <Alert color="blue">
        Select using earlier data, then evaluate the next interval. This is a
        historical simulation. Prior overlapping runs are recorded; no result
        is certified as untouched evidence.
      </Alert>
      <Stack>
        <Title order={3}>Plan a walk-forward evaluation</Title>
        <Select
          label="Starting run"
          placeholder="Use settings from a successful run"
          searchable
          data={runs
            .filter((r) => r.status === "Succeeded" && !r.input.research)
            .map((r) => ({
              value: r.id,
              label: `${r.input.strategy.name} · ${r.input.dataset.symbol} · ${r.id.slice(0, 8)}`,
            }))}
          value={seedId || null}
          onChange={chooseSeed}
        />
        <Text size="xs" c="dimmed">
          Settings are reused with a newly preserved current code version.
          Existing run artifacts remain unchanged. Each evaluation uses one
          market and timeframe.
        </Text>
        <TextInput
          label="Evaluation name"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput
            type="date"
            label="Research interval starts (UTC)"
            value={start}
            onChange={(e) => setStart(e.currentTarget.value)}
          />
          <TextInput
            type="date"
            label="Research interval ends (UTC)"
            value={end}
            onChange={(e) => setEnd(e.currentTarget.value)}
          />
          <NumberInput
            label="Training calendar days"
            value={train}
            min={7}
            max={2000}
            onChange={(v) => setTrain(Number(v))}
          />
          <NumberInput
            label="Test calendar days"
            value={test}
            min={7}
            max={365}
            onChange={(v) => setTest(Number(v))}
          />
          <NumberInput
            label="Number of folds"
            value={folds}
            min={1}
            max={12}
            onChange={(v) => setFolds(Number(v))}
          />
          <Select
            label="Select highest training"
            data={[
              { value: "net_pnl", label: "Net P&L (USD)" },
              { value: "sharpe", label: "Daily Sharpe" },
            ]}
            value={metric}
            onChange={(v) => v && setMetric(v)}
          />
        </SimpleGrid>
        <Textarea
          label="Candidate parameter grid (JSON)"
          description="Every candidate is retained. Ties use the original candidate order."
          minRows={2}
          value={sweep}
          onChange={(e) => setSweep(e.currentTarget.value)}
        />
        <Textarea
          label="Evaluation hypothesis"
          value={hypothesis}
          onChange={(e) => setHypothesis(e.currentTarget.value)}
        />
      </Stack>
      <Stack>
        <Title order={3}>Declare criteria & stress tests</Title>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <NumberInput
            label="Minimum training trades"
            value={minTrades}
            min={0}
            onChange={(v) => setMinTrades(Number(v))}
          />
          <NumberInput
            label="Minimum combined test trades"
            value={minTest}
            min={1}
            onChange={(v) => setMinTest(Number(v))}
          />
          <NumberInput
            label="Minimum test return (%)"
            value={minReturn}
            onChange={(v) => setMinReturn(Number(v))}
          />
          <NumberInput
            label="Maximum test drawdown (%)"
            value={maxDrawdown}
            min={0}
            max={100}
            onChange={(v) => setMaxDrawdown(Number(v))}
          />
          <NumberInput
            label="Stress cost multiplier"
            value={cost}
            min={1}
            max={10}
            onChange={(v) => setCost(Number(v))}
          />
          <NumberInput
            label="Additional execution delay (bars)"
            value={
              seed?.input.strategy.execution_model === "event-v1" ? 0 : delay
            }
            disabled={seed?.input.strategy.execution_model === "event-v1"}
            description={
              seed?.input.strategy.execution_model === "event-v1"
                ? "Unavailable for Pine event orders; baseline and cost stress remain supported."
                : "Zero omits delay stress."
            }
            min={0}
            max={20}
            onChange={(v) => setDelay(Number(v))}
          />
        </SimpleGrid>
        <Text size="xs" c="dimmed">
          Each selected candidate receives baseline and higher-cost tests, plus
          delayed-execution tests when enabled and supported. These scenarios
          never influence selection. Each fold starts and ends flat; test P&L
          is joined without resetting equity peaks.
        </Text>
        {validPreview && (
          <>
            <Text fw={600}>
              {preview.jobs} planned jobs · {preview.folds.length} chronological
              folds
            </Text>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Fold</Table.Th>
                  <Table.Th>Training</Table.Th>
                  <Table.Th>Subsequent test</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {preview.folds.map((f) => (
                  <Table.Tr key={f.index}>
                    <Table.Td>{f.index + 1}</Table.Td>
                    <Table.Td>
                      {f.train_start} → {f.train_end}
                    </Table.Td>
                    <Table.Td>
                      {f.test_start} → {f.test_end}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </>
        )}
        {error && (
          <Alert color="red" title="Research action failed">
            {error}
          </Alert>
        )}
        <Group>
          <Button
            variant="light"
            loading={busy}
            onClick={() =>
              void act(async () => {
                const value = await send<{ jobs: number; folds: Fold[] }>(
                  "/evaluations/preview",
                  payload(),
                );
                setPreview(value);
                setPreviewKey(key);
              })
            }
          >
            Preview evaluation
          </Button>
          <Button
            disabled={!validPreview || busy}
            onClick={() =>
              void act(async () => {
                const created = await send<EvaluationView>(
                  "/evaluations",
                  payload(),
                );
                onSelect(created.id);
                setTab("Summary");
                setPreview(null);
                setPlanOpen(false);
              })
            }
          >
            Launch walk-forward
          </Button>
        </Group>
      </Stack>
    </Stack>
  );

  function detail(current: EvaluationView) {
    const jobs = runs.filter(
      (r) => r.input.research?.evaluation_id === current.id,
    );
    const scenarios = current.result?.scenarios || [];
    const worstTrades = scenarios.length
      ? Math.min(...scenarios.map((s) => s.metrics.trades))
      : null;
    const worstReturn = scenarios.length
      ? Math.min(...scenarios.map((s) => s.metrics.net_return))
      : null;
    const worstDrawdown = scenarios.length
      ? Math.max(...scenarios.map((s) => Math.abs(s.metrics.max_drawdown)))
      : null;
    const firstFold = current.folds[0],
      lastFold = current.folds.at(-1);
    const currentRegimes = regimes.filter((r) => r.evaluation_id === current.id);
    return (
      <div className="wb-ledger-detail">
        <Group justify="space-between" align="start" wrap="nowrap">
          <div>
            <Group gap="sm" align="center">
              <h2>{current.name}</h2>
              {current.outcome && (
                <Badge color={outcomeColor(current.outcome)} radius="xs" variant="light">
                  {current.outcome}
                </Badge>
              )}
              {current.status !== "Succeeded" && (
                <Badge color={color(current.status)} radius="xs">
                  {current.status}
                </Badge>
              )}
            </Group>
            {firstFold && lastFold && (
              <p className="wb-meta">
                {current.folds.length} fold
                {current.folds.length === 1 ? "" : "s"} · train{" "}
                {firstFold.train_start} → {lastFold.train_end} · test{" "}
                {firstFold.test_start} → {lastFold.test_end}
              </p>
            )}
            <p className="wb-meta">
              {current.id.slice(0, 8)} · code {current.source_hash.slice(0, 8)}{" "}
              · created {current.created_at.slice(0, 10)} ·{" "}
              {jobs.filter((r) => r.status === "Succeeded").length} /{" "}
              {current.jobs} jobs · selects on {current.metric}
            </p>
          </div>
          {["Running", "Summarizing"].includes(current.status) && (
            <Button
              variant="light"
              color="red"
              size="xs"
              onClick={() =>
                void act(async () => {
                  await send(`/evaluations/${current.id}/cancel`, {});
                })
              }
            >
              Cancel evaluation
            </Button>
          )}
        </Group>
        {current.note && <Alert color="blue">{current.note}</Alert>}
        {current.error && (
          <Alert color="red">
            {current.error} Start a new evaluation to retry the protocol;
            existing selections remain unchanged.
          </Alert>
        )}
        <nav className="wb-tabs wb-inner-tabs" aria-label="Evaluation views">
          {DETAIL_TABS.map((t) => (
            <button
              key={t}
              type="button"
              className={tab === t ? "active" : ""}
              aria-pressed={tab === t}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </nav>
        {tab === "Summary" && (
          <>
            {current.hypothesis && (
              <p className="wb-context">{current.hypothesis}</p>
            )}
            <section className="wb-card">
              <h3>Scenarios</h3>
              {scenarios.length ? (
                <ScrollArea>
                  <Table miw={640} mt={6}>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Scenario</Table.Th>
                        <Table.Th ta="right">Net P&L</Table.Th>
                        <Table.Th ta="right">Net return</Table.Th>
                        <Table.Th ta="right">Max drawdown</Table.Th>
                        <Table.Th ta="right">Test trades</Table.Th>
                        <Table.Th>Outcome</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {scenarios.map((s) => (
                        <Table.Tr key={s.name}>
                          <Table.Td>{s.name}</Table.Td>
                          <Table.Td
                            ta="right"
                            className={`mono ${s.metrics.net_pnl < 0 ? "wb-loss" : "wb-gain"}`}
                          >
                            {number(s.metrics.net_pnl)}
                          </Table.Td>
                          <Table.Td ta="right" className="mono">
                            {pct(s.metrics.net_return)}
                          </Table.Td>
                          <Table.Td ta="right" className="mono">
                            {pct(s.metrics.max_drawdown)}
                          </Table.Td>
                          <Table.Td ta="right">{s.metrics.trades}</Table.Td>
                          <Table.Td>
                            <Badge
                              color={outcomeColor(s.outcome)}
                              radius="xs"
                              variant="light"
                            >
                              {s.outcome}
                            </Badge>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </ScrollArea>
              ) : (
                <Text size="sm" c="dimmed" mt="xs">
                  Not scored yet · {jobs.filter((r) => r.status === "Succeeded").length}{" "}
                  of {current.jobs} jobs succeeded.
                </Text>
              )}
            </section>
            <div className="wb-two">
              <section className="wb-card">
                <h3>Criteria, declared before launch</h3>
                <ul className="wb-criteria">
                  {current.min_test_trades !== undefined && (
                    <li>
                      <span>At least {current.min_test_trades} combined test trades</span>
                      <span>{worstTrades ?? "—"} fewest</span>
                    </li>
                  )}
                  {current.min_return !== undefined && (
                    <li>
                      <span>Test return at least {pct(current.min_return)}</span>
                      <span>{pct(worstReturn)} worst</span>
                    </li>
                  )}
                  {current.max_drawdown !== undefined && (
                    <li>
                      <span>Drawdown no deeper than {pct(current.max_drawdown)}</span>
                      <span>{pct(worstDrawdown)} worst</span>
                    </li>
                  )}
                  {current.min_trades !== undefined && (
                    <li>
                      <span>At least {current.min_trades} training trades</span>
                      <span>per candidate</span>
                    </li>
                  )}
                  {current.stress_multiple !== undefined && (
                    <li>
                      <span>Higher-cost stress</span>
                      <span>× {current.stress_multiple}</span>
                    </li>
                  )}
                  {current.delay_bars !== undefined && (
                    <li>
                      <span>Additional execution delay</span>
                      <span>
                        {current.delay_bars
                          ? `${current.delay_bars} bars`
                          : "not run"}
                      </span>
                    </li>
                  )}
                </ul>
                <Text size="xs" c="dimmed" mt="sm">
                  Outcomes come from the evaluation record.{" "}
                  {current.inspected_overlap.length} saved runs overlapped this
                  interval before launch.
                </Text>
              </section>
              <div className="wb-warnings">
                <b>
                  {current.result?.warnings.length || 0} warning
                  {current.result?.warnings.length === 1 ? "" : "s"}
                </b>
                {(current.result?.warnings || []).slice(0, 2).map((w) => (
                  <span key={w}>{w}</span>
                ))}
                {(current.result?.warnings.length || 0) > 2 && (
                  <details>
                    <summary>Show all {current.result?.warnings.length}</summary>
                    <Stack gap={6} mt={6}>
                      {current.result?.warnings.slice(2).map((w) => (
                        <span key={w}>{w}</span>
                      ))}
                    </Stack>
                  </details>
                )}
                {!current.result && <span>Warnings appear once scored.</span>}
              </div>
            </div>
            {current.result && (
              <Downloads
                id={current.id}
                kind="evaluations"
                names={["result.json", "equity.csv", "request.json"]}
              />
            )}
          </>
        )}
        {tab === "Fold selection & sensitivity" && (
          <section className="wb-card">
            <h3>Fold selection & parameter sensitivity</h3>
            {current.folds.map((fold) => (
              <Box key={fold.index} className="wb-history">
                <Text fw={600} size="sm">
                  Fold {fold.index + 1} · train {fold.train_start} →{" "}
                  {fold.train_end} · test {fold.test_start} → {fold.test_end}
                </Text>
                <ScrollArea>
                  <Table miw={850}>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Candidate</Table.Th>
                        <Table.Th>Parameters</Table.Th>
                        <Table.Th>Status</Table.Th>
                        <Table.Th>Training P&L</Table.Th>
                        <Table.Th>Training drawdown</Table.Th>
                        <Table.Th>Trades</Table.Th>
                        <Table.Th>Selection</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {current.candidates.map((candidate, i) => {
                        const id = fold.training[i],
                          run = runs.find((r) => r.id === id),
                          ranking = fold.selection?.ranked.find(
                            (r) => r.candidate === i,
                          );
                        return (
                          <Table.Tr key={i}>
                            <Table.Td>
                              {id ? runLink(id) : `Candidate ${i + 1}`}
                            </Table.Td>
                            <Table.Td>
                              <Code>{JSON.stringify(candidate.parameters)}</Code>
                            </Table.Td>
                            <Table.Td>{run?.status || "Not queued"}</Table.Td>
                            <Table.Td>
                              {number(run?.result?.metrics.net_pnl)}
                            </Table.Td>
                            <Table.Td>
                              {pct(run?.result?.metrics.max_drawdown)}
                            </Table.Td>
                            <Table.Td>
                              {run?.result?.metrics.trades ?? "—"}
                            </Table.Td>
                            <Table.Td>
                              {fold.selection?.candidate === i
                                ? "Selected on training"
                                : ranking
                                  ? ranking.eligible
                                    ? "Not selected"
                                    : "Rule not met"
                                  : "Pending"}
                            </Table.Td>
                          </Table.Tr>
                        );
                      })}
                    </Table.Tbody>
                  </Table>
                </ScrollArea>
                {fold.selection && (
                  <Text size="xs" c="dimmed" mt="sm">
                    Selection saved {fold.selection.selected_at}; only data
                    through {fold.selection.permitted_through}; score{" "}
                    {number(fold.selection.score)} ({current.metric}).
                  </Text>
                )}
                <Group gap="xs" mt="sm">
                  {fold.tests.map((id) => {
                    const run = runs.find((r) => r.id === id);
                    return (
                      <Box key={id}>
                        <Text size="xs">{run?.input.research?.scenario}</Text>
                        {runLink(id)}
                      </Box>
                    );
                  })}
                </Group>
              </Box>
            ))}
          </section>
        )}
        {tab === "Joined test path" && (
          <section className="wb-card">
            <h3>Joined subsequent test path</h3>
            {current.result ? (
              <Stack gap="sm" mt="xs">
                <Text size="xs" c="dimmed">
                  {current.result.boundary}
                </Text>
                <ScrollArea>
                  <Table miw={800}>
                    <Table.Thead>
                      <Table.Tr>
                        {[
                          "Scenario",
                          "Net return",
                          "Continuous drawdown",
                          "Trades",
                          "Costs (USD)",
                          "Daily Sharpe",
                          "Criteria",
                        ].map((t) => (
                          <Table.Th key={t}>{t}</Table.Th>
                        ))}
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {current.result.scenarios.map((s) => (
                        <Table.Tr key={s.name}>
                          <Table.Td>{s.name}</Table.Td>
                          <Table.Td>{pct(s.metrics.net_return)}</Table.Td>
                          <Table.Td>{pct(s.metrics.max_drawdown)}</Table.Td>
                          <Table.Td>{s.metrics.trades}</Table.Td>
                          <Table.Td>{number(s.metrics.costs)}</Table.Td>
                          <Table.Td>{number(s.metrics.sharpe)}</Table.Td>
                          <Table.Td>{s.outcome}</Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </ScrollArea>
                <EvaluationChart scenarios={current.result.scenarios} />
                <Alert color="yellow">
                  <Stack gap="xs">
                    {current.result.warnings.map((w) => (
                      <Text key={w} size="xs">
                        {w}
                      </Text>
                    ))}
                  </Stack>
                </Alert>
                <Downloads
                  id={current.id}
                  kind="evaluations"
                  names={["result.json", "equity.csv", "request.json"]}
                />
              </Stack>
            ) : (
              <Text size="sm" c="dimmed" mt="xs">
                The joined test path appears once every fold has been scored.
              </Text>
            )}
          </section>
        )}
        {tab === "Regime study" && (
          <section className="wb-card">
            <h3>Investigate historical market states</h3>
            <Text size="sm" c="dimmed" mt={4}>
              Each fold calibrates its threshold on earlier training data. A
              preceding-bar feature labels the following test outcome. All
              investigations remain recorded.
            </Text>
            {current.result ? (
              <Group align="end" mt="sm">
                <Select
                  label="State feature"
                  value={feature}
                  data={[
                    { value: "volatility", label: "Trailing volatility" },
                    { value: "trend", label: "Trailing trend" },
                  ]}
                  onChange={(v) => v && setFeature(v)}
                />
                <NumberInput
                  label="Feature lookback (bars)"
                  value={window}
                  min={2}
                  max={500}
                  onChange={(v) => setWindow(Number(v))}
                />
                <NumberInput
                  label="Training threshold quantile"
                  value={quantile}
                  min={0.1}
                  max={0.9}
                  step={0.1}
                  onChange={(v) => setQuantile(Number(v))}
                />
                <Button
                  loading={busy}
                  onClick={() =>
                    void act(async () => {
                      await send(`/evaluations/${current.id}/regimes`, {
                        feature,
                        window,
                        quantile,
                        seed: 42,
                      });
                    })
                  }
                >
                  Run regime investigation
                </Button>
              </Group>
            ) : (
              <Text size="sm" c="dimmed" mt="xs">
                Regime studies need a scored evaluation.
              </Text>
            )}
            {currentRegimes.map((task) => (
              <Box key={task.id} className="wb-history">
                <Group justify="space-between">
                  <Text fw={600}>
                    {task.feature} · {task.window} bars · {task.id.slice(0, 8)}
                  </Text>
                  <Badge color={color(task.status)} radius="xs">
                    {task.status}
                  </Badge>
                </Group>
                {task.error && (
                  <Alert color="red" mt="sm">
                    {task.error}
                  </Alert>
                )}
                {task.result && (
                  <>
                    <Text size="sm" mt="sm">
                      {task.result.source}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {task.result.formula}
                    </Text>
                    <ScrollArea>
                      <Table miw={1000}>
                        <Table.Thead>
                          <Table.Tr>
                            {[
                              "State",
                              "Bars",
                              "Episodes",
                              "Net P&L (USD)",
                              "Costs",
                              "Invested bars",
                              "Entries",
                              "Mean episode P&L · 95% interval",
                              "Evidence",
                            ].map((t) => (
                              <Table.Th key={t}>{t}</Table.Th>
                            ))}
                          </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                          {task.result.states.map((s) => (
                            <Table.Tr key={s.state}>
                              <Table.Td>{s.state}</Table.Td>
                              <Table.Td>{s.observations}</Table.Td>
                              <Table.Td>{s.episodes}</Table.Td>
                              <Table.Td>{number(s.net_pnl)}</Table.Td>
                              <Table.Td>{number(s.costs)}</Table.Td>
                              <Table.Td>{pct(s.invested_bar_fraction)}</Table.Td>
                              <Table.Td>{s.entry_count}</Table.Td>
                              <Table.Td>
                                {number(s.mean_episode_pnl)} ·{" "}
                                {s.mean_episode_pnl_interval_95
                                  ?.map(number)
                                  .join(" to ") || "Unavailable"}
                              </Table.Td>
                              <Table.Td>{s.evidence}</Table.Td>
                            </Table.Tr>
                          ))}
                        </Table.Tbody>
                      </Table>
                    </ScrollArea>
                    <details>
                      <summary>Threshold chronology</summary>
                      <Code block>
                        {JSON.stringify(task.result.thresholds, null, 2)}
                      </Code>
                    </details>
                    <Alert color="yellow" my="sm">
                      <Stack gap="xs">
                        {task.result.warnings.map((w) => (
                          <Text size="xs" key={w}>
                            {w}
                          </Text>
                        ))}
                      </Stack>
                    </Alert>
                    <Downloads
                      id={task.id}
                      kind="regimes"
                      names={["result.json", "observations.csv", "request.json"]}
                    />
                  </>
                )}
              </Box>
            ))}
          </section>
        )}
      </div>
    );
  }

  return (
    <>
      <PageHeader
        crumb="Research"
        title="Evaluations & regimes"
        actions={
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlus size={14} />}
            onClick={() => setPlanOpen(true)}
          >
            Plan walk-forward evaluation
          </Button>
        }
      />
      {alerts}
      {error && !planOpen && (
        <div className="wb-alerts">
          <Alert
            color="red"
            title="Research action failed"
            withCloseButton
            onClose={() => setError("")}
          >
            {error}
          </Alert>
        </div>
      )}
      <div className="wb-ledger">
        <div className="wb-ledger-list">
          <div className="wb-ledger-tools">
            <SegmentedControl
              aria-label="Outcome filter"
              size="xs"
              fullWidth
              value={outcomeFilter}
              onChange={setOutcomeFilter}
              data={[
                { value: "all", label: `All · ${evaluations.length}` },
                { value: "meets", label: `Meets · ${meets.length}` },
                { value: "fails", label: `Does not · ${fails.length}` },
              ]}
            />
            <TextInput
              size="xs"
              aria-label="Search evaluations"
              placeholder="Strategy, market or year"
              leftSection={<IconSearch size={13} />}
              value={query}
              onChange={(e) => setQuery(e.currentTarget.value)}
            />
          </div>
          <ul className="wb-ledger-items" aria-label="Evaluation ledger">
            {listed.map((e) => (
              <li key={e.id}>
                <button
                  type="button"
                  className={`wb-ledger-item${current?.id === e.id ? " active" : ""}`}
                  aria-current={current?.id === e.id ? "true" : undefined}
                  onClick={() => {
                    onSelect(e.id);
                    if (isMobile)
                      document
                        .querySelector(".wb-ledger-detail")
                        ?.scrollIntoView({ behavior: "smooth" });
                  }}
                >
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <b>{e.name}</b>
                    <small>
                      {e.created_at.slice(0, 10)} · {e.jobs} jobs ·{" "}
                      {e.status}
                    </small>
                  </span>
                  <Badge
                    size="sm"
                    radius="xs"
                    variant="light"
                    color={e.outcome ? outcomeColor(e.outcome) : color(e.status)}
                  >
                    {e.outcome === "Meets criteria"
                      ? "Meets"
                      : e.outcome === "Does not meet criteria"
                        ? "Does not"
                        : e.outcome || "Not scored"}
                  </Badge>
                </button>
              </li>
            ))}
          </ul>
          {!listed.length && (
            <Text p="md" size="sm" c="dimmed">
              {evaluations.length
                ? "No evaluations match."
                : "No evaluations yet."}
            </Text>
          )}
          <Text px="md" py="sm" size="xs" c="dimmed">
            Complete grids and selection records stay visible.
          </Text>
        </div>
        {current ? (
          detail(current)
        ) : (
          <div className="wb-ledger-detail">
            <section className="wb-card">
              <h2>No evaluations yet</h2>
              <p className="wb-card-sub">
                Start with a declared chronological plan: choose a successful
                run, set folds and criteria, preview, then launch.
              </p>
              <Button
                mt="md"
                variant="light"
                leftSection={<IconPlus size={14} />}
                onClick={() => setPlanOpen(true)}
              >
                Plan walk-forward evaluation
              </Button>
            </section>
          </div>
        )}
      </div>
      <Drawer
        opened={planOpen}
        onClose={() => setPlanOpen(false)}
        position="right"
        size={isMobile ? "100%" : 720}
        title={
          <span className="collective-drawer-title">
            Plan walk-forward evaluation
          </span>
        }
      >
        {planForm}
      </Drawer>
    </>
  );
}

function EvaluationChart({
  scenarios,
}: {
  scenarios: NonNullable<EvaluationView["result"]>["scenarios"];
}) {
  const points = scenarios.flatMap((s) => s.equity_preview);
  if (points.length < 2) return null;
  const min = Math.min(...points.map((p) => p.equity)),
    max = Math.max(...points.map((p) => p.equity));
  const start = Math.min(...points.map((p) => Date.parse(p.timestamp))),
    end = Math.max(...points.map((p) => Date.parse(p.timestamp)));
  const colors = ["#187465", "#b06b39", "#6265ac"];
  return (
    <Box className="wb-chart">
      <Text size="sm" fw={600}>
        Test equity · USD · ${number(min)} to ${number(max)}
      </Text>
      <svg
        viewBox="0 0 960 180"
        role="img"
        aria-label="Walk-forward test equity"
      >
        <line x1="0" x2="960" y1="165" y2="165" stroke="#dbe5e0" />
        {scenarios.map((s, i) => (
          <polyline
            key={s.name}
            fill="none"
            stroke={colors[i]}
            strokeWidth="2"
            points={s.equity_preview
              .map(
                (p) =>
                  `${((Date.parse(p.timestamp) - start) / (end - start || 1)) * 960},${165 - ((p.equity - min) / (max - min || 1)) * 150}`,
              )
              .join(" ")}
          />
        ))}
      </svg>
      <Group>
        {scenarios.map((s, i) => (
          <Text size="xs" c={colors[i]} key={s.name}>
            {s.name}
          </Text>
        ))}
      </Group>
      <Text size="xs" c="dimmed">
        {new Date(start).toISOString().slice(0, 10)} →{" "}
        {new Date(end).toISOString().slice(0, 10)} · previews sampled; full
        series downloadable
      </Text>
    </Box>
  );
}
