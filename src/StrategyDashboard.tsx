import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Box,
  Button,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  IconArrowUpRight,
  IconChartLine,
  IconShieldCheck,
} from "@tabler/icons-react";
import type {
  DashboardData,
  DashboardRow,
  DashboardScenario,
  DashboardStatus,
} from "./dashboardTypes";

const cash = (v: number | null | undefined) =>
  v == null
    ? "—"
    : v.toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      });
const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${(v * 100).toFixed(1)}%`;
const ratio = (v: number | null | undefined) =>
  v == null ? "—" : v.toFixed(2);
const tone = (s: DashboardStatus) =>
  s === "Research candidate"
    ? "teal"
    : s === "Conditional"
      ? "yellow"
      : s === "Needs review" || s === "Incomplete"
        ? "red"
        : "gray";
const baseline = (r: DashboardRow) =>
  r.scenarios.find((s) => s.name === "Baseline");

function Equity({ row }: { row: DashboardRow }) {
  const [scenario, setScenario] = useState("All scenarios");
  const valid = row.scenarios.some((s) => s.name === scenario)
    ? scenario
    : "All scenarios";
  const series = row.scenarios.filter(
    (s) => valid === "All scenarios" || s.name === valid,
  );
  const points = series.flatMap((s) => s.equity_preview);
  if (!points.length) return <Text>No equity observations available.</Text>;
  const capital = row.capital || 0,
    low = Math.min(capital, ...points.map((p) => p.equity)),
    high = Math.max(capital, ...points.map((p) => p.equity));
  const first = Math.min(...points.map((p) => Date.parse(p.timestamp))),
    last = Math.max(...points.map((p) => Date.parse(p.timestamp)));
  const x = (date: string) =>
    85 + ((Date.parse(date) - first) / (last - first || 1)) * 795;
  const y = (v: number) => 230 - ((v - low) / (high - low || 1)) * 195;
  const colors = ["#14795f", "#bb792e", "#7068ab"];
  return (
    <>
      <Group justify="space-between" align="start" mb="lg">
        <Box>
          <Title order={3}>Equity & execution stress</Title>
          <Text size="xs" c="dimmed" mt={4}>
            Marked equity in USD · each scenario starts with {cash(capital)}
          </Text>
        </Box>
        <Select
          label="Equity scenario"
          size="xs"
          value={valid}
          onChange={(v) => setScenario(v || "All scenarios")}
          data={["All scenarios", ...row.scenarios.map((s) => s.name)]}
        />
      </Group>
      <svg
        className="sd-equity"
        viewBox="0 0 900 270"
        role="img"
        aria-label={`${row.name} evaluation equity`}
      >
        {[low, (high + low) / 2, high].map((v, i) => (
          <g key={i}>
            <line x1="85" x2="880" y1={y(v)} y2={y(v)} stroke="#dce5de" />
            <text
              x="74"
              y={y(v) + 4}
              textAnchor="end"
              fill="#68796f"
              fontSize="12"
            >
              {cash(v)}
            </text>
          </g>
        ))}
        <line
          x1="85"
          x2="880"
          y1={y(capital)}
          y2={y(capital)}
          stroke="#8ba499"
          strokeDasharray="4 5"
        />
        {series.map((s) => (
          <polyline
            key={s.name}
            fill="none"
            stroke={colors[row.scenarios.indexOf(s) % colors.length]}
            strokeWidth="2.5"
            points={s.equity_preview
              .map((p) => `${x(p.timestamp)},${y(p.equity)}`)
              .join(" ")}
          >
            <title>
              {s.name}: {cash(s.metrics.net_pnl)} net P&amp;L
            </title>
          </polyline>
        ))}
        <text x="85" y="258" fill="#68796f" fontSize="12">
          {row.start}
        </text>
        <text x="880" y="258" textAnchor="end" fill="#68796f" fontSize="12">
          {row.end}
        </text>
      </svg>
      <Group gap="lg" mt="sm">
        {series.map((s) => (
          <Text
            size="xs"
            key={s.name}
            c={colors[row.scenarios.indexOf(s) % colors.length]}
          >
            {s.name} · {cash(s.metrics.net_pnl)} net
          </Text>
        ))}
      </Group>
      <Text size="xs" c="dimmed" mt="sm">
        Chart samples the saved equity path. Metrics use the complete
        evaluation.{" "}
        {row.scenarios.length < 3 &&
          "Execution-delay stress is unavailable or was omitted."}
      </Text>
    </>
  );
}
function ProfitBar({ value, scale }: { value: number; scale: number }) {
  const width = Math.min(49, (Math.abs(value) / (scale || 1)) * 49);
  return (
    <div className="sd-bar">
      <span className="sd-zero" />
      <span
        style={{
          left: value < 0 ? `${50 - width}%` : "50%",
          width: `${width}%`,
          background: value < 0 ? "#bf6757" : "#379078",
        }}
      />
    </div>
  );
}
function Regimes({ row }: { row: DashboardRow }) {
  const [feature, setFeature] = useState("trend");
  const study =
    row.regimes.find((r) => r.feature === feature) || row.regimes[0];
  if (!study)
    return (
      <Paper withBorder p="lg">
        <Title order={3}>Regime evidence</Title>
        <Text mt="sm" c="dimmed">
          No completed regime study is available for this evaluation.
        </Text>
      </Paper>
    );
  const scale = Math.max(...study.states.map((s) => Math.abs(s.net_pnl)), 1);
  return (
    <Paper withBorder p="lg">
      <Group justify="space-between">
        <Box>
          <Title order={3}>Where returns came from</Title>
          <Text size="xs" c="dimmed">
            {study.window} preceding bars · {row.timeframe} chart · historical
            attribution
          </Text>
        </Box>
        <Select
          label="Regime feature"
          size="xs"
          value={study.feature}
          data={row.regimes.map((r) => ({
            value: r.feature,
            label:
              r.feature === "trend" ? "Trailing trend" : "Trailing volatility",
          }))}
          onChange={(v) => v && setFeature(v)}
        />
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2 }} mt="lg">
        {study.states.map((s) => (
          <Box key={s.state} className="sd-regime">
            <Group justify="space-between">
              <Text fw={600}>
                {s.state} {study.feature}
              </Text>
              <Text fw={600} c={s.net_pnl < 0 ? "red.8" : "teal.8"}>
                {cash(s.net_pnl)}
              </Text>
            </Group>
            <ProfitBar value={s.net_pnl} scale={scale} />
            <Text size="xs" c="dimmed">
              {s.episodes.toLocaleString()} episodes ·{" "}
              {pct(s.invested_bar_fraction)} invested bars
            </Text>
            <Text size="xs" mt={5}>
              Mean episode P&amp;L interval:{" "}
              {s.mean_episode_pnl_interval_95
                ? s.mean_episode_pnl_interval_95.map(cash).join(" to ")
                : "Unavailable (sparse evidence)"}
            </Text>
          </Box>
        ))}
      </SimpleGrid>
      <Text size="xs" c="dimmed" mt="md">
        Higher/lower is relative to the training threshold, not a live market
        label. Contributions include unequal time and exposure; trading only in
        a selected state has not been tested.
      </Text>
    </Paper>
  );
}
function Metric({
  label,
  value,
  help,
}: {
  label: string;
  value: string;
  help: string;
}) {
  return (
    <Tooltip label={help} multiline w={280} withArrow>
      <Paper withBorder className="sd-metric" tabIndex={0}>
        <Text size="xs" c="dimmed">
          {label}
        </Text>
        <Text className="sd-metric-value">{value}</Text>
      </Paper>
    </Tooltip>
  );
}
function Stress({ scenarios }: { scenarios: DashboardScenario[] }) {
  return (
    <ScrollArea>
      <Table miw={550}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Scenario</Table.Th>
            <Table.Th>Net profit</Table.Th>
            <Table.Th>Drawdown</Table.Th>
            <Table.Th>Costs</Table.Th>
            <Table.Th>Daily Sharpe</Table.Th>
            <Table.Th>Outcome</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {scenarios.map((s) => (
            <Table.Tr key={s.name}>
              <Table.Td>{s.name}</Table.Td>
              <Table.Td>{cash(s.metrics.net_pnl)}</Table.Td>
              <Table.Td>{pct(Math.abs(s.metrics.max_drawdown))}</Table.Td>
              <Table.Td>{cash(s.metrics.costs)}</Table.Td>
              <Table.Td>{ratio(s.metrics.sharpe)}</Table.Td>
              <Table.Td>
                <Badge
                  size="sm"
                  color={s.outcome === "Meets criteria" ? "teal" : "red"}
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
  );
}
export function StrategyDashboard({
  refreshKey,
  openEvaluation,
  inspectRun,
}: {
  refreshKey: number;
  openEvaluation: (id: string) => void;
  inspectRun: (id: string) => void;
}) {
  const [market, setMarket] = useState(""),
    [data, setData] = useState<DashboardData | null>(null),
    [error, setError] = useState("");
  const [selection, setSelection] = useState(""),
    [filter, setFilter] = useState("All strategies");
  useEffect(() => {
    let alive = true;
    let controller: AbortController | undefined;
    const refresh = async () => {
      controller?.abort();
      controller = new AbortController();
      try {
        const response = await fetch(
          `/api/workbench/dashboard${market ? `?symbol=${encodeURIComponent(market)}` : ""}`,
          { signal: controller.signal },
        );
        const result = await response.json();
        if (!response.ok)
          throw new Error(result.error || "Dashboard unavailable");
        if (alive) {
          setData(result);
          setError("");
        }
      } catch (e) {
        if (alive && !(e instanceof Error && e.name === "AbortError"))
          setError(String(e));
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 10000);
    return () => {
      alive = false;
      controller?.abort();
      clearInterval(timer);
    };
  }, [market, refreshKey]);
  if (!data)
    return error ? (
      <Alert color="red">{error}</Alert>
    ) : (
      <Group>
        <Loader size="sm" />
        <Text>Loading evaluation evidence…</Text>
      </Group>
    );
  const rows = data.rows.filter(
    (r) =>
      filter === "All strategies" ||
      (filter === "Shortlist"
        ? ["Research candidate", "Conditional"].includes(r.status)
        : r.status === "Needs review"),
  );
  const selected = rows.find((r) => r.strategy_id === selection) || rows[0];
  const evaluated = data.rows.filter((r) => r.scenarios.length);
  const dates = evaluated.map((r) => r.end!).sort(),
    latestDate = dates.at(-1);
  const candidate = data.rows.filter(
      (r) => r.status === "Research candidate",
    ).length,
    conditional = data.rows.filter((r) => r.status === "Conditional").length;
  const scale = Math.max(
    ...rows.map((r) => Math.abs(baseline(r)?.metrics.net_pnl || 0)),
    1,
  );
  const b = selected && baseline(selected),
    stats = selected?.trades;
  return (
    <Stack className="wb-dashboard" gap="lg">
      {error && (
        <Alert color="yellow">
          Refresh failed: {error}. Showing the last loaded snapshot from{" "}
          {new Date(data.generated_at).toLocaleString()}.
        </Alert>
      )}
      <Group justify="space-between" align="end">
        <Box>
          <Badge variant="light" color="teal">
            Latest historical evidence
          </Badge>
          <Text size="sm" c="dimmed" mt="sm">
            {latestDate
              ? `Evaluations through ${latestDate}. `
              : "No completed evaluations yet. "}
            These are research statuses, not live trade signals.
          </Text>
        </Box>
        <Group>
          <Select
            label="Dashboard market"
            value={data.symbol}
            data={data.symbols.length ? data.symbols : ["NQ"]}
            onChange={(v) => {
              if (v) {
                setData(null);
                setMarket(v);
                setSelection("");
              }
            }}
          />
          <Select
            label="Show strategies"
            value={filter}
            data={["All strategies", "Shortlist", "Needs review"]}
            onChange={(v) => {
              setFilter(v || "All strategies");
              setSelection("");
            }}
          />
        </Group>
      </Group>
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Metric
          label="Evaluated strategies"
          value={String(evaluated.length)}
          help="One latest evaluation per strategy and market. No portfolio P&L is implied."
        />
        <Metric
          label="Research candidates"
          value={String(candidate)}
          help="All declared latest scenarios are profitable and pass, complete trade evidence reconciles, adapter unchanged, and no earlier matching review flags."
        />
        <Metric
          label="Conditional candidates"
          value={String(conditional)}
          help="Latest scenarios pass but earlier matching research checks remain flagged."
        />
        <Metric
          label="Need review"
          value={String(
            data.rows.filter((r) => r.status === "Needs review").length,
          )}
          help="At least one criterion fails, evidence is unavailable, or the adapter changed."
        />
      </SimpleGrid>
      {!selected ? (
        <Paper withBorder p="xl">
          <Title order={3}>No strategies match this view</Title>
          <Text c="dimmed" mt="sm">
            Choose All strategies or another market to view the available
            evidence.
          </Text>
        </Paper>
      ) : (
        <>
          <Paper withBorder p="lg" className="sd-selected">
            <Group justify="space-between" align="start">
              <Box>
                <Text size="xs" className="eyebrow">
                  SELECTED STRATEGY
                </Text>
                <Title order={2} mt={5}>
                  {selected.name}
                </Title>
                <Group mt="sm" gap="xs">
                  <Badge color={tone(selected.status)}>{selected.status}</Badge>
                  <Text size="sm" c="dimmed">
                    {selected.symbol}
                    {selected.timeframe &&
                      ` · ${selected.timeframe} · ${selected.start} to ${selected.end}`}
                  </Text>
                </Group>
              </Box>
              <Group>
                {selected.baseline_run_ids[0] && (
                  <Button
                    variant="light"
                    onClick={() => inspectRun(selected.baseline_run_ids[0])}
                  >
                    Inspect baseline run
                  </Button>
                )}
                {selected.evaluation_id && (
                  <Button
                    rightSection={<IconArrowUpRight size={16} />}
                    onClick={() => openEvaluation(selected.evaluation_id!)}
                  >
                    Open evaluation
                  </Button>
                )}
              </Group>
            </Group>
            <Stack gap={4} mt="md">
              {selected.reasons.map((reason, i) => (
                <Text size="sm" key={i}>
                  {reason}
                </Text>
              ))}
            </Stack>
            {!!selected.prior_flags.length && (
              <Group mt="xs" gap="xs">
                {selected.prior_flags.map((flag) => (
                  <Button
                    key={flag.id}
                    size="compact-xs"
                    variant="subtle"
                    onClick={() =>
                      flag.kind === "run"
                        ? inspectRun(flag.id)
                        : openEvaluation(flag.id)
                    }
                  >
                    Earlier flagged check · {flag.end}
                  </Button>
                ))}
              </Group>
            )}
            {selected.newer_data_through &&
              selected.end &&
              selected.newer_data_through > selected.end && (
                <Text size="xs" c="dimmed" mt="sm">
                  Newer {selected.symbol} data is available through{" "}
                  {selected.newer_data_through}; this evaluation has not tested
                  it.
                </Text>
              )}
          </Paper>
          {b && (
            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
              <Metric
                label="Net profit"
                value={cash(b.metrics.net_pnl)}
                help={`${pct(b.metrics.net_return)} return on ${cash(selected.capital)} starting capital, after costs.`}
              />
              <Metric
                label="Maximum drawdown"
                value={pct(Math.abs(b.metrics.max_drawdown))}
                help="Largest decline from a previous marked-equity peak across the continuous test path."
              />
              <Metric
                label="Realized reward / risk"
                value={
                  stats?.payoff_ratio == null
                    ? "—"
                    : `${ratio(stats.payoff_ratio)} : 1`
                }
                help="Average net winning trade divided by the absolute average net losing trade. Undefined without both wins and losses."
              />
              <Metric
                label="Profit factor"
                value={
                  stats?.profit_factor == null
                    ? stats && stats.wins > 0 && stats.losses === 0
                      ? "No losses"
                      : "—"
                    : `${ratio(stats.profit_factor)}×`
                }
                help="Sum of positive net trade P&L divided by the absolute sum of negative net trade P&L. Uses every closed trade."
              />
              <Metric
                label="Win rate"
                value={pct(stats?.win_rate)}
                help="Winning closed trades divided by all closed trades, including breakeven trades."
              />
              <Metric
                label="Expectancy / trade"
                value={cash(stats?.expectancy)}
                help="Average net P&L per closed trade, after commissions and slippage."
              />
              <Metric
                label="Closed trades"
                value={stats ? stats.trades.toLocaleString() : "—"}
                help="Complete baseline trade ledgers across all test folds, not the first 100-trade preview."
              />
              <Metric
                label="Target reward / risk"
                value={
                  selected.target_rr == null
                    ? "Not defined"
                    : `${ratio(selected.target_rr)} : 1`
                }
                help="Declared target-to-stop price distance, where defined and unchanged across folds. Realized outcomes can differ."
              />
            </SimpleGrid>
          )}
          {stats && (
            <Text size="sm" c="dimmed">
              Full trade ledger: {stats.wins} wins · {stats.losses} losses ·{" "}
              {stats.breakeven} breakeven. Average net win{" "}
              {cash(stats.average_win)} / average net loss{" "}
              {cash(stats.average_loss)}.
            </Text>
          )}
          <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
            <Paper withBorder p="lg">
              {b ? (
                <Equity row={selected} />
              ) : (
                <Box py="xl">
                  <IconChartLine size={28} />
                  <Title order={3} mt="md">
                    An evaluation is needed
                  </Title>
                  <Text c="dimmed" mt="sm">
                    Complete an evaluation for this strategy and market to
                    populate its charts and trade statistics.
                  </Text>
                </Box>
              )}
            </Paper>
            <Paper withBorder p="lg">
              <Title order={3}>Profit across strategies</Title>
              <Text size="xs" c="dimmed" mt={4} mb="md">
                Select a strategy to inspect it. Separate evaluations; not a
                combined portfolio. Windows and sizing may differ.
              </Text>
              <Stack gap={5}>
                {rows.map((r) => (
                  <button
                    key={r.strategy_id}
                    className={`sd-profit-row ${r.strategy_id === selected.strategy_id ? "is-selected" : ""}`}
                    onClick={() => setSelection(r.strategy_id)}
                    aria-label={`Select ${r.name}`}
                    aria-pressed={r.strategy_id === selected.strategy_id}
                  >
                    <span className="sd-profit-label">
                      <span>{r.name}</span>
                      <strong>{cash(baseline(r)?.metrics.net_pnl)}</strong>
                    </span>
                    <ProfitBar
                      value={baseline(r)?.metrics.net_pnl || 0}
                      scale={scale}
                    />
                  </button>
                ))}
              </Stack>
            </Paper>
          </SimpleGrid>
          {b && (
            <>
              <Paper withBorder p="lg">
                <Group gap="xs" mb="md">
                  <IconShieldCheck size={20} />
                  <Title order={3}>Execution stress & costs</Title>
                </Group>
                <Text size="xs" c="dimmed" mb="md">
                  Base assumptions: {cash(selected.capital)} capital · $
                  {selected.fee?.toFixed(2)} fee per contract per side ·{" "}
                  {selected.slippage} tick(s) slippage per side. Each scenario
                  is evaluated separately.
                </Text>
                <Stress scenarios={selected.scenarios} />
              </Paper>
              <Regimes row={selected} />
            </>
          )}
        </>
      )}
      <Paper withBorder p="lg">
        <Title order={3} mb="md">
          Strategy scorecard
        </Title>
        <ScrollArea>
          <Table miw={1080} highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                {[
                  "Strategy",
                  "Research status",
                  "Test through",
                  "Net profit",
                  "Drawdown",
                  "Win rate",
                  "Profit factor",
                  "Realized R:R",
                  "Trades",
                  "",
                ].map((h, i) => (
                  <Table.Th key={i}>{h}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((r) => (
                <Table.Tr key={r.strategy_id}>
                  <Table.Td>
                    <Text fw={600} size="sm">
                      {r.name}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {r.symbol} · {r.timeframe || "No timeframe"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={tone(r.status)} variant="light">
                      {r.status}
                    </Badge>
                  </Table.Td>
                  <Table.Td>{r.end || "—"}</Table.Td>
                  <Table.Td>{cash(baseline(r)?.metrics.net_pnl)}</Table.Td>
                  <Table.Td>
                    {baseline(r)
                      ? pct(Math.abs(baseline(r)!.metrics.max_drawdown))
                      : "—"}
                  </Table.Td>
                  <Table.Td>{pct(r.trades?.win_rate)}</Table.Td>
                  <Table.Td>
                    {r.trades?.profit_factor == null &&
                    r.trades?.wins &&
                    !r.trades.losses
                      ? "No losses"
                      : ratio(r.trades?.profit_factor)}
                  </Table.Td>
                  <Table.Td>
                    {r.trades?.payoff_ratio == null
                      ? "—"
                      : `${ratio(r.trades.payoff_ratio)} : 1`}
                  </Table.Td>
                  <Table.Td>{r.trades?.trades ?? "—"}</Table.Td>
                  <Table.Td>
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      onClick={() => {
                        setSelection(r.strategy_id);
                        window.scrollTo({ top: 0, behavior: "smooth" });
                      }}
                    >
                      View strategy
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Paper>
      <details>
        <summary>How status and reward / risk are calculated</summary>
        <Text size="sm">
          The dashboard uses the latest test end date, then the newest
          evaluation attempt for that window. An incomplete latest attempt is
          not replaced by an older passing result. Candidates have positive net
          profit and meet every scenario declared in that evaluation; omitted
          tests remain untested. Conditional candidates have earlier matching
          evaluation failures or saved checks-failed flags. Status checks
          adapter identity, not every possible external dependency change.
        </Text>
        <Text size="sm" mt="sm">
          R:R and profit factor use checksum-verified full baseline trade
          ledgers, net of costs. R:R needs winning and losing trades; no-loss
          samples have no finite profit factor. Target R:R describes order
          distances, not achieved returns. These historical statuses do not
          authorize trading, and regime attribution does not validate a
          switching strategy.
        </Text>
      </details>
    </Stack>
  );
}
