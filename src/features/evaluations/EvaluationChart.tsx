import { Box, Group, Text } from "@mantine/core";
import type { EvaluationView } from "../../../shared/ts/workbenchModels.ts";

const number = (value: number) =>
  value.toLocaleString(undefined, { maximumFractionDigits: 2 });

export function EvaluationChart({
  scenarios,
}: {
  scenarios: NonNullable<EvaluationView["result"]>["scenarios"];
}) {
  const points = scenarios.flatMap((scenario) => scenario.equity_preview);
  if (points.length < 2) return null;
  const min = Math.min(...points.map((point) => point.equity));
  const max = Math.max(...points.map((point) => point.equity));
  const start = Math.min(
    ...points.map((point) => Date.parse(point.timestamp)),
  );
  const end = Math.max(...points.map((point) => Date.parse(point.timestamp)));
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
        {scenarios.map((scenario, index) => (
          <polyline
            key={scenario.name}
            fill="none"
            stroke={colors[index]}
            strokeWidth="2"
            points={scenario.equity_preview
              .map(
                (point) =>
                  `${((Date.parse(point.timestamp) - start) / (end - start || 1)) * 960},${165 - ((point.equity - min) / (max - min || 1)) * 150}`,
              )
              .join(" ")}
          />
        ))}
      </svg>
      <Group>
        {scenarios.map((scenario, index) => (
          <Text size="xs" c={colors[index]} key={scenario.name}>
            {scenario.name}
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
