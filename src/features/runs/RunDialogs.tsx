import {
  Alert,
  Badge,
  Box,
  Button,
  Code,
  Drawer,
  Group,
  Modal,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { IconStar } from "@tabler/icons-react";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import {
  WORKBENCH_API as API,
  workbenchRequest as request,
} from "../../shared/api/workbench";
import type { WorkbenchController } from "../workspace/useWorkbenchController";
import {
  formatNumber,
  formatPercent,
  statusTone,
} from "../workspace/workbenchModel";
import { EquityChart } from "./EquityChart";

export function RunDialogs({ controller }: { controller: WorkbenchController }) {
  const {
    action,
    busy,
    deletion,
    detail,
    inspect,
    notes,
    reason,
    reuse,
    setComparison,
    setDeletion,
    setDetail,
    setNotes,
    setNotice,
    setReason,
    setSelected,
    setTags,
    tags,
  } = controller;
  return (
    <>
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
              <Badge color={statusTone(detail.status)}>{detail.status}</Badge>
            </Group>
            <Text size="xs" c="dimmed">{detail.id} · {detail.input.stage}</Text>
            <Text size="sm">
              {detail.input.dataset.symbol} · {detail.input.timeframe} · {detail.input.start} → {detail.input.end}
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
                      await request("/runs/delete-preview", { ids: [detail.id] }),
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
                    setNotice("A new attempt was created using the preserved inputs.");
                    setDetail(null);
                  })
                }
              >
                Rerun identical inputs
              </Button>
              <Button variant="subtle" onClick={() => reuse(detail)}>Use settings</Button>
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
                    ["Net return", formatPercent(detail.result.metrics.net_return)],
                    ["Drawdown", formatPercent(detail.result.metrics.max_drawdown)],
                    ["Closed trades", formatNumber(detail.result.metrics.trades)],
                    ["Net P&L (USD)", formatNumber(detail.result.metrics.net_pnl)],
                    ["Costs (USD)", formatNumber(detail.result.metrics.costs)],
                    ["Daily Sharpe", formatNumber(detail.result.metrics.sharpe)],
                  ].map(([label, value]) => (
                    <Box key={label} className="metricBox">
                      <Text size="xs" c="dimmed">{label}</Text>
                      <Text fw={600}>{value}</Text>
                    </Box>
                  ))}
                </SimpleGrid>
                <EquityChart run={detail} />
                <Text size="xs" c="dimmed">{detail.result.metrics.basis}</Text>
                <Text size="xs" c="dimmed">{detail.result.metrics.undefined_reason}</Text>
                <details>
                  <summary>Monthly returns</summary>
                  <Table>
                    <Table.Thead><Table.Tr><Table.Th>Month</Table.Th><Table.Th>Net return</Table.Th></Table.Tr></Table.Thead>
                    <Table.Tbody>
                      {detail.result.metrics.monthly.map((month) => (
                        <Table.Tr key={month.month}>
                          <Table.Td>{month.month}</Table.Td>
                          <Table.Td>{formatPercent(month.return)}</Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </details>
                <details>
                  <summary>Trades (first 100; full ledger downloadable)</summary>
                  <Code block className="wb-log">{JSON.stringify(detail.result.trade_preview, null, 2)}</Code>
                </details>
                <Alert color="yellow" title="Evidence limitations">
                  <Stack gap="xs">
                    {detail.result.warnings.map((warning) => <Text key={warning} size="xs">{warning}</Text>)}
                  </Stack>
                </Alert>
                <Group>
                  {detail.result.artifacts.map((artifact) => (
                    <Button
                      component="a"
                      key={artifact.name}
                      href={`${API}/runs/${detail.id}/artifact?name=${artifact.name}`}
                      variant="light"
                      size="xs"
                    >
                      {artifact.name}
                    </Button>
                  ))}
                </Group>
                <Textarea
                  label="Reason for freezing this configuration"
                  value={reason}
                  onChange={(event) => setReason(event.currentTarget.value)}
                />
                <Button
                  leftSection={<IconStar size={16} />}
                  variant="light"
                  disabled={!reason.trim() || busy}
                  onClick={() =>
                    void action(async () => {
                      await request("/watchlist", { run_id: detail.id, reason });
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
              onChange={(event) => setNotes(event.currentTarget.value)}
            />
            <TextInput label="Tags" value={tags} onChange={(event) => setTags(event.currentTarget.value)} />
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
              <Code block className="wb-log">{JSON.stringify(detail.input, null, 2)}</Code>
            </details>
            <details open>
              <summary>Process log</summary>
              <Code block className="wb-log">{detail.log || "Waiting for process output…"}</Code>
            </details>
          </Stack>
        )}
      </Drawer>

      <Modal opened={!!deletion} onClose={() => setDeletion(null)} title="Review run deletion" centered>
        {deletion && (
          <Stack>
            <Text>{deletion.explanation}</Text>
            <Text>{Object.entries(deletion.counts).map(([name, count]) => `${count} ${name}`).join(" · ")}</Text>
            <Alert color="yellow">
              Deletion removes these records from the app. Deleting losing trials changes the visible research history; keep them when assessing an optimization.
            </Alert>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setDeletion(null)}>Keep runs</Button>
              <Button
                color="red"
                loading={busy}
                onClick={() =>
                  void action(async () => {
                    const result = await request<{
                      backup: string;
                      counts: { runs: number };
                      warnings: string[];
                    }>("/runs/delete", { ids: deletion.ids, token: deletion.token });
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
    </>
  );
}
