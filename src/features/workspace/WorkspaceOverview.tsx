import { Alert, Badge, Button, Group, ScrollArea, Table, Text } from "@mantine/core";
import { IconPlayerPlay } from "@tabler/icons-react";
import type { RunSummary } from "../../../shared/ts/workbenchModels.ts";
import { href } from "../../app/navigation";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import { PageHeader } from "../../shared/ui/PageHeader";
import { isInvalidRun, latestRunsByConfiguration } from "../runs/model";
import {
  formatNumber,
  formatPercent,
  shortId,
  statusTone,
  type WorkbenchState,
} from "./workbenchModel";

export function WorkspaceOverview({
  state,
  onInspect,
  onCleanup,
}: {
  state: WorkbenchState;
  onInspect: (run: RunSummary) => void;
  onCleanup: (ids: string[]) => void;
}) {
  const latest = latestRunsByConfiguration(state.runs);
  const completed = latest.filter((run) => run.status === "Succeeded").length;
  const invalidRuns = state.runs.filter(isInvalidRun);
  const invalid = invalidRuns.length;
  const evaluations = state.evaluations || [];
  const activeEvaluations = evaluations.filter((evaluation) =>
    ["Queued", "Running", "Summarizing"].includes(evaluation.status),
  ).length;
  const flow = [
    {
      number: "01",
      title: "Idea",
      detail: "Find a source or record a question.",
      metric: `${state.library?.total || state.strategies.length} sources`,
      link: href("scripts", "library"),
    },
    {
      number: "02",
      title: "Strategy",
      detail: "Choose an adapter and lock parameters.",
      metric: `${state.strategies.length} runnable`,
      link: href("scripts"),
    },
    {
      number: "03",
      title: "Backtest",
      detail: "Run the historical simulation.",
      metric: `${completed} latest complete`,
      link: href("new-run"),
    },
    {
      number: "04",
      title: "Validation",
      detail: "Check later data, costs, and nearby settings.",
      metric: activeEvaluations
        ? `${activeEvaluations} in progress`
        : `${evaluations.length} recorded`,
      link: href("evaluations"),
    },
    {
      number: "05",
      title: "Portfolio gates",
      detail: "Only reviewed configurations reach the book.",
      metric: `${state.watchlist.length} frozen`,
      link: href("scorecards"),
    },
  ];
  return (
    <>
      <PageHeader
        crumb="Research flow"
        title="Research workspace"
        actions={
          <Button component="a" href={href("new-run")} size="xs" leftSection={<IconPlayerPlay size={14} />}>
            New backtest
          </Button>
        }
      />
      <div className="wb-content wb-workspace">
        <section className="wb-workflow" aria-label="Research flow">
          <div className="wb-card-head">
            <div>
              <h2>From idea to portfolio</h2>
              <p className="wb-card-sub">Each step leaves a saved record for the next.</p>
            </div>
            <Badge color="teal" variant="light">Persistent workspace</Badge>
          </div>
          <div className="wb-flow-grid">
            {flow.map((item, index) => (
              <a className="wb-flow-step" href={item.link} key={item.title}>
                <span className="wb-flow-number">{item.number}</span>
                <span className="wb-flow-title">{item.title}</span>
                <span className="wb-flow-detail">{item.detail}</span>
                <span className="wb-flow-metric">{item.metric}</span>
                {index < flow.length - 1 && <span className="wb-flow-arrow" aria-hidden="true">→</span>}
              </a>
            ))}
          </div>
        </section>

        {invalid > 0 && (
          <Alert color="yellow" title={`${invalid} completed run${invalid === 1 ? "" : "s"} need cleanup`}>
            <Group justify="space-between" align="center" gap="sm">
              <Text size="sm">These records have no valid result manifest and are excluded from latest evidence.</Text>
              <Button size="xs" variant="light" color="orange" onClick={() => onCleanup(invalidRuns.map((run) => run.id))}>
                Review cleanup
              </Button>
            </Group>
          </Alert>
        )}

        <section className="wb-table-card">
          <div className="wb-card-head wb-latest-head">
            <div>
              <h2>Latest history</h2>
              <p className="wb-card-sub">One record per configuration, newest tested window first.</p>
            </div>
            <Group gap="xs">
              <Badge variant="light" color="gray">{latest.length} configurations</Badge>
              <Button component="a" href={href("runs")} variant="subtle" size="xs">All attempts</Button>
            </Group>
          </div>
          <ScrollArea>
            <Table miw={820} highlightOnHover verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Configuration</Table.Th>
                  <Table.Th>Tested through</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th ta="right">Net</Table.Th>
                  <Table.Th ta="right">DD</Table.Th>
                  <Table.Th ta="right">Trades</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {latest.slice(0, 10).map((run) => (
                  <Table.Tr key={run.id}>
                    <Table.Td>
                      <Text fw={600} size="sm">{strategyTitle(run.input.strategy.name)}</Text>
                      <Text size="xs" c="dimmed">{run.input.dataset.symbol} · {run.input.timeframe} · {shortId(run.id)}</Text>
                    </Table.Td>
                    <Table.Td><Text size="sm" className="mono">{run.input.end}</Text></Table.Td>
                    <Table.Td><Badge color={statusTone(run.status)} variant="light" radius="xs">{run.status}</Badge></Table.Td>
                    <Table.Td ta="right" className={`mono ${run.result?.metrics.net_return != null && run.result.metrics.net_return < 0 ? "wb-loss" : "wb-gain"}`}>
                      {formatPercent(run.result?.metrics.net_return)}
                    </Table.Td>
                    <Table.Td ta="right" className="mono">{formatPercent(run.result?.metrics.max_drawdown)}</Table.Td>
                    <Table.Td ta="right" className="mono">{formatNumber(run.result?.metrics.trades)}</Table.Td>
                    <Table.Td><Button size="compact-xs" variant="subtle" onClick={() => onInspect(run)}>Inspect</Button></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
          {!latest.length && <div className="wb-empty"><Text>No backtests yet.</Text><Button component="a" href={href("new-run")} mt="sm">Start with a strategy</Button></div>}
        </section>
      </div>
    </>
  );
}
