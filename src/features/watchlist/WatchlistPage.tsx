import { Badge, Box, Button, Group, SimpleGrid, Text, Title } from "@mantine/core";
import { href } from "../../app/navigation";
import { workbenchRequest as request } from "../../shared/api/workbench";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import { PageHeader } from "../../shared/ui/PageHeader";
import { RefreshButton, WorkbenchAlerts } from "../workspace/WorkbenchChrome";
import type { WorkbenchController } from "../workspace/useWorkbenchController";
import { formatPercent, shortId, statusTone } from "../workspace/workbenchModel";

export function WatchlistPage({ controller }: { controller: WorkbenchController }) {
  const { action, busy, inspect, setNotice, state } = controller;
  if (!state) return null;
  return (
    <>
      <PageHeader crumb="Research" title="Watchlist" actions={<RefreshButton controller={controller} />} />
      <WorkbenchAlerts controller={controller} />
      <div className="wb-content">
        <p className="wb-context">
          These are updated historical replays. Freezing a configuration records a research choice; it does not establish an edge or prospective paper performance.
        </p>
        {!state.watchlist.length && (
          <section className="wb-card">
            <h2>No frozen configurations yet</h2>
            <Text size="sm" c="dimmed" mt="sm">Inspect a successful run and record your reason to add it to the watchlist.</Text>
            <Button mt="md" variant="light" component="a" href={href("runs")}>Open runs</Button>
          </section>
        )}
        {state.watchlist.map((entry) => {
          const original = state.runs.find((run) => run.id === entry.run_id);
          if (!original) return null;
          const snapshots = state.runs.filter((run) => run.watch_id === entry.id);
          const latest = snapshots.find((run) => run.status === "Succeeded") || original;
          const metrics = latest.result!.metrics;
          const newest = state.datasets
            .filter((dataset) => dataset.symbol === original.input.dataset.symbol)
            .sort(
              (left, right) =>
                right.last.localeCompare(left.last) ||
                right.registered_at.localeCompare(left.registered_at),
            )[0];
          const pending = snapshots.find((run) => ["Queued", "Running"].includes(run.status));
          const trackingStatus = pending
            ? pending.status
            : snapshots[0]?.status === "Failed"
              ? "Error"
              : !newest
                ? "Incomplete"
                : newest.id !== latest.input.dataset.id || newest.last.slice(0, 10) > latest.input.end
                  ? "Stale"
                  : "Current";
          const currentMonth = metrics.last.slice(0, 7);
          const previousMonth = new Date(
            Date.UTC(Number(currentMonth.slice(0, 4)), Number(currentMonth.slice(5, 7)) - 2, 1),
          ).toISOString().slice(0, 7);
          const recent = (count: number) => {
            const first = new Date(
              Date.UTC(Number(currentMonth.slice(0, 4)), Number(currentMonth.slice(5, 7)) - count - 1, 1),
            ).toISOString().slice(0, 7);
            const months = metrics.monthly.filter((month) => month.month >= first && month.month < currentMonth);
            return months.length === count && metrics.first.slice(0, 7) < first
              ? months.reduce((value, month) => value * (1 + month.return), 1) - 1
              : null;
          };
          return (
            <section key={entry.id} className="wb-card">
              <Group justify="space-between" align="start">
                <Box>
                  <Title order={3}>{strategyTitle(original.input.strategy.name)} · {original.input.dataset.symbol}</Title>
                  <Text size="xs" c="dimmed">Frozen {entry.frozen_at.slice(0, 10)} · configuration {shortId(entry.configuration_id)}</Text>
                </Box>
                <Badge color={statusTone(trackingStatus)} radius="xs">{trackingStatus}</Badge>
              </Group>
              <Text my="sm" size="sm">{entry.reason}</Text>
              <Text size="xs" c="dimmed" mb="md">
                Covered through {metrics.last} · source: {entry.source} · Current means matching the latest registered data.
              </Text>
              <SimpleGrid cols={{ base: 2, md: 6 }}>
                {[
                  ["MTD (data month)", formatPercent(latest.input.start <= currentMonth + "-01" ? metrics.monthly.find((month) => month.month === currentMonth)?.return : null)],
                  ["Last completed month", formatPercent(latest.input.start <= previousMonth + "-01" ? metrics.monthly.find((month) => month.month === previousMonth)?.return : null)],
                  ["Trailing 3 months", formatPercent(recent(3))],
                  ["Trailing 6 months", formatPercent(recent(6))],
                  ["Trailing 12 months", formatPercent(recent(12))],
                  ["Continuous drawdown", formatPercent(metrics.max_drawdown)],
                ].map(([label, value]) => (
                  <Box key={label} className="metricBox"><Text size="xs" c="dimmed">{label}</Text><Text fw={600}>{value}</Text></Box>
                ))}
              </SimpleGrid>
              <Text size="xs" c="dimmed" mt="sm">
                {metrics.trades} trades · currently {metrics.current_underwater_bars} bars underwater · recent returns use completed calendar months; unavailable windows stay blank.
              </Text>
              <Group mt="md">
                <Button
                  variant="light"
                  disabled={!!pending || busy}
                  onClick={() =>
                    void action(async () => {
                      const result = await request<{ status: string }>(`/watchlist/${entry.id}/update`, {});
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
                <Button variant="subtle" onClick={() => void action(() => inspect(latest))}>Inspect latest</Button>
                <Text size="xs" c="dimmed">{snapshots.length} tracking attempts preserved</Text>
              </Group>
              <details className="wb-history">
                <summary>Snapshot history & selection boundary</summary>
                <Text size="xs">Data after {original.input.end} is newer than the original selection window. Replay results can still be influenced by later human selection.</Text>
                {[...snapshots, original].map((run) => (
                  <Button key={run.id} variant="subtle" size="xs" onClick={() => void action(() => inspect(run))}>
                    {shortId(run.id)} · {run.input.end} · {run.status}
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
