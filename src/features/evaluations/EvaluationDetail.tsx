import {
  Alert,
  Badge,
  Box,
  Button,
  Code,
  Group,
  NumberInput,
  ScrollArea,
  Select,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import type {
  EvaluationView,
  RegimeView,
  RunSummary,
} from "../../../shared/ts/workbenchModels.ts";
import { useStrategyStages } from "../../shared/ui/strategyStageContext";
import { ResearchStages } from "./ResearchStages";
import { EvaluationStageBadge, RunStageBadge } from "../../shared/ui/StrategyStageBadge";
import { workbenchRequest as send } from "../../shared/api/workbench";
import { EvaluationChart } from "./EvaluationChart";
import { ResearchDownloads as Downloads } from "./ResearchDownloads";
import {
  detailTabs as DETAIL_TABS,
  evaluationOutcomeColor as outcomeColor,
  evaluationStatusColor as color,
  formatNumber as number,
  formatPercent as pct,
} from "./researchModel";
import type { ResearchController } from "./useResearchController";

export function EvaluationDetail({
  current,
  runs,
  regimes,
  inspect,
  controller,
}: {
  current: EvaluationView;
  runs: RunSummary[];
  regimes: RegimeView[];
  inspect: (run: RunSummary) => void;
  controller: ResearchController;
}) {
  const {
    act,
    busy,
    feature,
    quantile,
    setFeature,
    setQuantile,
    setTab,
    setWindow,
    tab,
    window,
  } = controller;
  const runLink = (id: string) => {
    const run = runs.find((r) => r.id === id);
    return (
      <Group key={id} gap="xs">
      <Button
        size="compact-xs"
        variant="subtle"
        onClick={() => run && inspect(run)}
      >
        {id.slice(0, 8)} · {run?.status || "Loading"}
      </Button>
      {run && <RunStageBadge runId={run.id} />}
      </Group>
    );
  };
  const jobs = runs.filter(
    (r) => r.input.research?.evaluation_id === current.id,
  );
  const scenarios = current.result?.scenarios || [];
  const progress = useStrategyStages().statuses.byEvaluation.get(current.id);
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
              <Badge
                color={outcomeColor(current.outcome)}
                radius="xs"
                variant="light"
              >
                Baseline outcome: {current.outcome}
              </Badge>
            )}
            {current.status !== "Succeeded" && (
              <Badge color={color(current.status)} radius="xs">
                {current.status}
              </Badge>
            )}
          </Group>
          <Text size="xs" fw={600} mt="sm">Current configuration stage</Text>
          <EvaluationStageBadge evaluationId={current.id} showFinding />
          {progress && <details><summary>Development milestones for these current configurations</summary><ResearchStages stage={progress.stage} /></details>}
          <Text size="xs" c="dimmed">
            Results apply to this evaluation's source, markets and selected
            settings. Other configurations are assessed separately.
          </Text>
          {firstFold && lastFold && (
            <p className="wb-meta">
              {current.folds.length} fold
              {current.folds.length === 1 ? "" : "s"} · train{" "}
              {firstFold.train_start} → {lastFold.train_end} · test{" "}
              {firstFold.test_start} → {lastFold.test_end}
            </p>
          )}
          <p className="wb-meta">
            {current.id.slice(0, 8)} · code {current.source_hash.slice(0, 8)} ·
            created {current.created_at.slice(0, 10)} ·{" "}
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
          {current.error} Start a new evaluation to retry the protocol; existing
          selections remain unchanged.
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
                Not scored yet ·{" "}
                {jobs.filter((r) => r.status === "Succeeded").length} of{" "}
                {current.jobs} jobs succeeded.
              </Text>
            )}
          </section>
          <div className="wb-two">
            <section className="wb-card">
              <h3>Criteria, declared before launch</h3>
              <ul className="wb-criteria">
                {current.min_test_trades !== undefined && (
                  <li>
                    <span>
                      At least {current.min_test_trades} combined test trades
                    </span>
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
                    <span>
                      Drawdown no deeper than {pct(current.max_drawdown)}
                    </span>
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
