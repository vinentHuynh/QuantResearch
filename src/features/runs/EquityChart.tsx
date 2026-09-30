import { Box, Group, Text } from "@mantine/core";
import type { Run } from "../../../shared/ts/workbenchModels.ts";
import { formatNumber, formatPercent } from "../workspace/workbenchModel";

export function EquityChart({ run }: { run: Run }) {
  const points = run.result?.equity_preview || [];
  if (points.length < 2) return <Text>No equity preview available.</Text>;
  const values = [run.input.capital, ...points.map((point) => point.equity)];
  const low = Math.min(...values);
  const high = Math.max(...values);
  const range = high - low || 1;
  const coords = values
    .map(
      (value, index) =>
        `${(index / (values.length - 1)) * 960},${150 - ((value - low) / range) * 130}`,
    )
    .join(" ");
  return (
    <Box className="wb-chart">
      <Group justify="space-between">
        <Text size="sm" fw={600}>
          Marked equity · USD
        </Text>
        <Text size="xs" c="dimmed">
          ${formatNumber(low)} – ${formatNumber(high)}
        </Text>
      </Group>
      <svg viewBox="0 0 960 170" role="img" aria-label="Equity curve in US dollars">
        <line x1="0" x2="960" y1="150" y2="150" stroke="#dbe5e0" />
        <polyline points={coords} fill="none" stroke="#187465" strokeWidth="2" />
      </svg>
      {points.every((point) => point.drawdown !== undefined) && (
        <>
          <Text size="xs" c="dimmed">
            Continuous drawdown from equity peak ·{" "}
            {formatPercent(run.result?.metrics.max_drawdown)} maximum
          </Text>
          <svg viewBox="0 0 960 65" role="img" aria-label="Continuous drawdown chart">
            <line x1="0" x2="960" y1="5" y2="5" stroke="#dbe5e0" />
            <polyline
              points={points
                .map(
                  (point, index) =>
                    `${(index / (points.length - 1)) * 960},${5 + ((point.drawdown || 0) / (run.result?.metrics.max_drawdown || -1)) * 50}`,
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
        <Text size="xs" c="dimmed">{points[0].timestamp.slice(0, 10)}</Text>
        <Text size="xs" c="dimmed">{points.at(-1)?.timestamp.slice(0, 10)}</Text>
      </Group>
      <Text size="xs" c="dimmed">
        Preview sampled for display. Full bar-level equity is available in the CSV.
      </Text>
    </Box>
  );
}
