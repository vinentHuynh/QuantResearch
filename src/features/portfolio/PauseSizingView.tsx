import {
  Alert,
  Badge,
  Button,
  ScrollArea,
  Select,
  SimpleGrid,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { IconCheck, IconDownload, IconX } from "@tabler/icons-react";
import { sizingSettings } from "../../../shared/ts/riskSizing.ts";
import type { GateState } from "../../../shared/ts/portfolio.ts";
import {
  csvCell,
  dependenceVerdictCopy as verdictCopy,
  dependenceVerdicts as verdicts,
  downloadFile as download,
  formatMoney as money,
  gateStateColor as stateColor,
  signedClass as signed,
} from "./collectiveViewModel";
import { StrategyConditionPanel } from "./StrategyConditionPanel";
import { PauseSizingControls } from "./PauseSizingControls";
import { CollectiveEmptyState } from "./CollectiveDashboardViews";
import type { CollectiveDashboardModel } from "./useCollectiveDashboardModel";

export function PauseSizingView({
  model,
}: {
  model: CollectiveDashboardModel;
}) {
  const {
    accountingLabel,
    catalog,
    histories,
    manualAction,
    manualBook,
    manualError,
    manualReason,
    manualTime,
    policy,
    result,
    selected,
    setManualAction,
    setManualBook,
    setManualError,
    setManualReason,
    setManualTime,
    settings,
    volatility,
  } = model;
  const currentPolicy = settings.policy;
  const sizing = sizingSettings(currentPolicy);
  const dependencies = result?.dependence || [];
  const clusters = dependencies.filter(
    (dependence) => dependence.verdict === "cluster",
  ).length;
  const single = dependencies.length === 1 ? dependencies[0] : null;
  const verdictClass = single
    ? single.verdict
    : clusters
      ? "cluster"
      : dependencies.some((dependence) => dependence.verdict === "alternate")
        ? "alternate"
        : "none";
  const skipped =
    result?.components.reduce((count, component) => count + component.skipped, 0) ||
    0;
  const cutoffStates = result
    ? Object.entries(
        result.components.reduce(
          (states, component) => ({
            ...states,
            [component.state]: (states[component.state] || 0) + 1,
          }),
          {} as Record<string, number>,
        ),
      )
    : [];

  return (
    <div className="wb-policy">
      <PauseSizingControls policy={currentPolicy} updatePolicy={policy} />
      <div className="collective-policy-results">
        <StrategyConditionPanel
          catalog={catalog}
          items={selected}
          histories={histories}
          end={settings.end}
          enabled={currentPolicy.enabled}
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
                        ...result.benchmarks.map((benchmark) => ({
                          label: `Constant ${benchmark.size * 100}%`,
                          ...benchmark,
                        })),
                      ].map((row) =>
                        [
                          row.label,
                          row.net,
                          row.drawdown,
                          row.worstDay,
                          row.recovery ?? "",
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
                    ...result.benchmarks.map((benchmark) => ({
                      label: `Constant ${benchmark.size * 100}%`,
                      ...benchmark,
                    })),
                  ].map((row) => (
                    <Table.Tr key={row.label}>
                      <Table.Td>{row.label}</Table.Td>
                      <Table.Td>{money(row.net)}</Table.Td>
                      <Table.Td>{money(row.drawdown)}</Table.Td>
                      <Table.Td>{money(row.worstDay)}</Table.Td>
                      <Table.Td>{row.recovery?.toFixed(2) ?? "â€”"}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          </section>
        )}
        {currentPolicy.enabled && result && (
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
                    ...result.sizingDecisions.map((decision) =>
                      [
                        decision.id,
                        decision.entry,
                        decision.accepted,
                        decision.multiple,
                        decision.contracts ?? "",
                      ]
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
                : "missing â€” refresh evidence; unsupported ledgers remain unavailable"}
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
                            const item = selected.find(
                              (candidate) => candidate.id === id,
                            );
                            return `${item?.name} / ${item?.symbol}`;
                          })
                          .join(" â†” ")}
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
        {currentPolicy.enabled &&
          (currentPolicy.mode === "manual" ||
            currentPolicy.mode === "deterioration") && (
            <section className="wb-card" data-testid="manual-schedule">
              <h2>Manual pause / resume</h2>
              <p className="wb-card-sub">
                Apply a dated decision to one selected book. The timestamp is
                UTC; entries at or after it follow the decision. Existing
                positions keep their recorded exits. This schedule replays
                history and does not control live orders.
              </p>
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                <Select
                  label="Strategy to control"
                  value={manualBook}
                  onChange={setManualBook}
                  data={selected.map((item) => ({
                    value: item.id,
                    label: `${item.name} / ${item.symbol} / ${item.timeframe}`,
                  }))}
                  searchable
                />
                <TextInput
                  label="Effective time (UTC)"
                  type="datetime-local"
                  value={manualTime}
                  onChange={(event) => setManualTime(event.currentTarget.value)}
                />
                <Select
                  label="Manual action"
                  value={manualAction}
                  onChange={(value) => setManualAction(value || "pause")}
                  data={[
                    { value: "pause", label: "Pause new entries" },
                    { value: "resume", label: "Resume new entries" },
                  ]}
                />
                <TextInput
                  label="Decision reason"
                  value={manualReason}
                  onChange={(event) => setManualReason(event.currentTarget.value)}
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
                    !selected.some((item) => item.id === manualBook) ||
                    !Number.isFinite(time) ||
                    !manualReason.trim()
                  ) {
                    setManualError(
                      "Choose a selected strategy, UTC time and decision reason.",
                    );
                    return;
                  }
                  const timestamp = new Date(time).toISOString();
                  const book = selected.find((item) => item.id === manualBook)!;
                  if (
                    timestamp.slice(0, 10) < book.start ||
                    timestamp.slice(0, 10) > book.end
                  ) {
                    setManualError(
                      "Choose a time within this strategy's tested history.",
                    );
                    return;
                  }
                  const decisions = currentPolicy.manual?.[manualBook] || [];
                  if (
                    decisions.some(
                      (decision) => Date.parse(decision.timestamp) === time,
                    )
                  ) {
                    setManualError(
                      "A decision already exists at that time. Remove it before replacing it.",
                    );
                    return;
                  }
                  policy({
                    manual: {
                      ...currentPolicy.manual,
                      [manualBook]: [
                        ...decisions,
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
                    {selected.flatMap((item) =>
                      (currentPolicy.manual?.[item.id] || []).map((decision) => (
                        <Table.Tr key={item.id + decision.timestamp}>
                          <Table.Td>
                            {decision.timestamp.replace("T", " ").slice(0, 16)}
                          </Table.Td>
                          <Table.Td>
                            {item.name} / {item.symbol} / {item.timeframe}
                          </Table.Td>
                          <Table.Td>
                            {decision.action}: {decision.reason}
                          </Table.Td>
                          <Table.Td>
                            <Button
                              size="compact-xs"
                              variant="subtle"
                              aria-label={`Remove ${decision.action} ${item.id} ${decision.timestamp}`}
                              onClick={() =>
                                policy({
                                  manual: {
                                    ...currentPolicy.manual,
                                    [item.id]: (
                                      currentPolicy.manual?.[item.id] || []
                                    ).filter(
                                      (candidate) =>
                                        candidate.timestamp !== decision.timestamp,
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
                Decisions persist with this browser's combination and are
                included in its JSON export. Turning replay off restores the
                always-on history; it keeps your schedule.
              </Text>
            </section>
          )}
        {currentPolicy.enabled && result && !volatility && (
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
                  {result.components.map((component) => (
                    <Table.Tr key={component.id}>
                      <Table.Td>
                        {component.name} / {component.symbol} /{" "}
                        {
                          selected.find((item) => item.id === component.id)
                            ?.timeframe
                        }
                      </Table.Td>
                      <Table.Td>
                        <Badge color={stateColor[component.state]}>
                          {component.state === "Active"
                            ? "Enabled"
                            : component.state}
                        </Badge>
                        <Text size="xs">{component.status?.reason}</Text>
                      </Table.Td>
                      <Table.Td>
                        {component.status?.cooldownUntil
                          ?.replace("T", " ")
                          .slice(0, 16) || "â€”"}
                      </Table.Td>
                      <Table.Td>
                        {component.state === "Paused" &&
                        (component.status?.required || 0) > 0
                          ? `${component.status?.recoveryTrades}/${component.status?.required} trades; ${money(component.status?.recoveryPnl || 0)}`
                          : "â€”"}
                      </Table.Td>
                      <Table.Td>
                        {money(component.baseline - component.pnl)}
                        <Text size="xs">
                          {component.skipped} trades; positive = missed profit
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          </section>
        )}
        {!currentPolicy.enabled ? (
          <section className="wb-card">
            <h2>Replay is off</h2>
            <p className="wb-card-sub">
              Turn on the replay to see whether losses cluster, how a pause or
              sizing rule compares with always-on trading, and every decision it
              would have made.
            </p>
          </section>
        ) : !result ? (
          <CollectiveEmptyState model={model} />
        ) : (
          <>
            {currentPolicy.mode !== "manual" && (
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
                    : `${clusters} of ${dependencies.length} selected books show loss clustering`}
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
                          : "â€”"}
                      </b>
                    </div>
                    <div>
                      <span>Runs z</span>
                      <b>
                        {Number.isFinite(single.runsZ)
                          ? single.runsZ.toFixed(2)
                          : "â€”"}
                      </b>
                    </div>
                    <div>
                      <span>Mean after loss</span>
                      <b>
                        {Number.isFinite(single.afterLoss)
                          ? money(single.afterLoss)
                          : "â€”"}
                      </b>
                    </div>
                    <div>
                      <span>Mean after win</span>
                      <b>
                        {Number.isFinite(single.afterWin)
                          ? money(single.afterWin)
                          : "â€”"}
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
                    ? currentPolicy.mode === "fixed"
                      ? "With constant sizing"
                      : "With volatility scaling"
                    : currentPolicy.mode === "manual"
                      ? "With manual schedule"
                      : "With pause rule"}
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
                  <span>average size Ã—{result.exposure.toFixed(2)}</span>
                ) : (
                  <span>
                    At cutoff{" "}
                    {cutoffStates.map(([state, count]) => (
                      <Badge
                        key={state}
                        color={stateColor[state as GateState]}
                        variant="light"
                        radius="xs"
                        size="sm"
                        ml={4}
                      >
                        {count > 1
                          ? `${count} ${state === "Active" ? "Enabled" : state}`
                          : state === "Active"
                            ? "Enabled"
                            : state}
                      </Badge>
                    ))}
                  </span>
                )}
              </div>
            </div>
            {currentPolicy.mode !== "manual" && (
              <section className="wb-card" data-testid="dependence-check">
                <h2>Do losses cluster?</h2>
                <p className="wb-card-sub">
                  Runs test on win/loss signs, using trades closed before the
                  window when at least 30 exist, otherwise the window itself. z
                  below âˆ’1.96 indicates clustering in the sample; above +1.96
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
                      {dependencies.map((dependence) => (
                        <Table.Tr key={dependence.id}>
                          <Table.Td>
                            {dependence.name} / {dependence.symbol}
                          </Table.Td>
                          <Table.Td ta="right">
                            {dependence.trades}{" "}
                            <Text span size="xs" c="dimmed">
                              {dependence.prior
                                ? "before window"
                                : "in window"}
                            </Text>
                          </Table.Td>
                          <Table.Td ta="right">
                            {Number.isFinite(dependence.autocorrelation)
                              ? dependence.autocorrelation.toFixed(3)
                              : "â€”"}
                          </Table.Td>
                          <Table.Td ta="right">
                            {Number.isFinite(dependence.runsZ)
                              ? dependence.runsZ.toFixed(2)
                              : "â€”"}
                          </Table.Td>
                          <Table.Td ta="right">
                            {Number.isFinite(dependence.afterLoss)
                              ? money(dependence.afterLoss)
                              : "â€”"}
                          </Table.Td>
                          <Table.Td ta="right">
                            {Number.isFinite(dependence.afterWin)
                              ? money(dependence.afterWin)
                              : "â€”"}
                          </Table.Td>
                          <Table.Td>
                            <Badge
                              color={verdicts[dependence.verdict][1]}
                              radius="xs"
                              variant="light"
                            >
                              {verdicts[dependence.verdict][0]}
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
                : currentPolicy.mode === "manual"
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
                        ...result.events.map((event) =>
                          [
                            event.timestamp,
                            event.id,
                            event.name,
                            event.state,
                            event.reason,
                          ]
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
                    {result.events.map((event, index) => (
                      <Table.Tr key={index}>
                        <Table.Td
                          className="mono"
                          style={{ whiteSpace: "nowrap" }}
                        >
                          {event.timestamp.replace("T", " ").slice(0, 16)}
                        </Table.Td>
                        <Table.Td>{event.name}</Table.Td>
                        <Table.Td>
                          <Badge
                            color={stateColor[event.state]}
                            radius="xs"
                            variant="light"
                          >
                            {event.state}
                          </Badge>
                        </Table.Td>
                        <Table.Td>{event.reason}</Table.Td>
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
}
