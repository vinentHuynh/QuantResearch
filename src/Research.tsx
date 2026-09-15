import { useState } from "react";
import {
  Alert,
  Badge,
  Box,
  Button,
  Code,
  Group,
  NumberInput,
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
import type { Run } from "./Workbench";

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

export function ResearchPage({
  initialSelected,
  runs,
  evaluations,
  regimes,
  refresh,
  inspect,
}: {
  initialSelected?: string;
  runs: Run[];
  evaluations: EvaluationView[];
  regimes: RegimeView[];
  refresh: () => Promise<void>;
  inspect: (run: Run) => void;
}) {
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
  const [selected, setSelected] = useState(initialSelected || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feature, setFeature] = useState("volatility");
  const [window, setWindow] = useState(20);
  const [quantile, setQuantile] = useState(0.5);
  const seed = runs.find((r) => r.id === seedId),
    current = evaluations.find((e) => e.id === selected) || evaluations[0];
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
  return (
    <Stack gap="lg">
      {error && (
        <Alert
          color="red"
          title="Research action failed"
          withCloseButton
          onClose={() => setError("")}
        >
          {error}
        </Alert>
      )}
      <Alert color="blue">
        Select using earlier data, then evaluate the next interval. This is a
        historical simulation. Prior overlapping runs are recorded; no result is
        certified as untouched evidence.
      </Alert>
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
        <Paper p="lg" withBorder>
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
            <SimpleGrid cols={2}>
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
        </Paper>
        <Paper p="lg" withBorder>
          <Stack>
            <Title order={3}>Declare criteria & stress tests</Title>
            <SimpleGrid cols={2}>
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
                  seed?.input.strategy.execution_model === "event-v1"
                    ? 0
                    : delay
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
              Each selected candidate receives baseline and higher-cost tests,
              plus delayed-execution tests when enabled and supported. These
              scenarios never influence selection. Each fold starts and ends
              flat; test P&L is joined without resetting equity peaks.
            </Text>
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
            {validPreview && (
              <>
                <Text fw={600}>
                  {preview.jobs} planned jobs · {preview.folds.length}{" "}
                  chronological folds
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
            <Button
              disabled={!validPreview || busy}
              onClick={() =>
                void act(async () => {
                  const created = await send<EvaluationView>(
                    "/evaluations",
                    payload(),
                  );
                  setSelected(created.id);
                  setPreview(null);
                })
              }
            >
              Launch walk-forward
            </Button>
          </Stack>
        </Paper>
      </SimpleGrid>
      <Paper p="lg" withBorder>
        <Group justify="space-between" mb="md">
          <Title order={3}>Evaluation ledger</Title>
          <Text size="xs" c="dimmed">
            Complete grids and selection records stay visible.
          </Text>
        </Group>
        <ScrollArea>
          <Table miw={850} highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name / source</Table.Th>
                <Table.Th>Execution</Table.Th>
                <Table.Th>Research outcome</Table.Th>
                <Table.Th>Progress</Table.Th>
                <Table.Th>Prior overlap</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {evaluations.map((e) => {
                const jobs = runs.filter(
                  (r) => r.input.research?.evaluation_id === e.id,
                );
                return (
                  <Table.Tr key={e.id}>
                    <Table.Td>
                      <Text size="sm" fw={600}>
                        {e.name}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {e.id.slice(0, 8)} · code {e.source_hash.slice(0, 8)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge color={color(e.status)}>{e.status}</Badge>
                    </Table.Td>
                    <Table.Td>{e.outcome || "Not scored"}</Table.Td>
                    <Table.Td>
                      {jobs.filter((r) => r.status === "Succeeded").length} /{" "}
                      {e.jobs} jobs
                    </Table.Td>
                    <Table.Td>{e.inspected_overlap.length} saved runs</Table.Td>
                    <Table.Td>
                      <Button
                        size="compact-sm"
                        variant="subtle"
                        onClick={() => setSelected(e.id)}
                      >
                        Open evaluation
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </ScrollArea>
        {!evaluations.length && (
          <Text p="xl" c="dimmed">
            No evaluations yet. Start with a declared chronological plan above.
          </Text>
        )}
      </Paper>
      {current && (
        <Paper p="lg" withBorder>
          <Stack>
            <Group justify="space-between">
              <div>
                <Title order={3}>{current.name}</Title>
                <Text size="xs" c="dimmed">
                  {current.id}
                </Text>
              </div>
              {["Running", "Summarizing"].includes(current.status) && (
                <Button
                  variant="light"
                  color="red"
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
            <Title order={4}>Fold selection & parameter sensitivity</Title>
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
                              <Code>
                                {JSON.stringify(candidate.parameters)}
                              </Code>
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
            {current.result && (
              <>
                <Title order={4}>Joined subsequent test path</Title>
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
                <Title order={4} mt="md">
                  Investigate historical market states
                </Title>
                <Text size="sm" c="dimmed">
                  Each fold calibrates its threshold on earlier training data. A
                  preceding-bar feature labels the following test outcome. All
                  investigations remain recorded.
                </Text>
                <Group align="end">
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
              </>
            )}
            {regimes
              .filter((r) => r.evaluation_id === current.id)
              .map((task) => (
                <Box key={task.id} className="wb-history">
                  <Group justify="space-between">
                    <Text fw={600}>
                      {task.feature} · {task.window} bars ·{" "}
                      {task.id.slice(0, 8)}
                    </Text>
                    <Badge color={color(task.status)}>{task.status}</Badge>
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
                                <Table.Td>
                                  {pct(s.invested_bar_fraction)}
                                </Table.Td>
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
                        names={[
                          "result.json",
                          "observations.csv",
                          "request.json",
                        ]}
                      />
                    </>
                  )}
                </Box>
              ))}
          </Stack>
        </Paper>
      )}
    </Stack>
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
