import {
  Alert,
  Button,
  Group,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import type {
  EvaluationFold as Fold,
  EvaluationView,
  RunSummary,
} from "../../../shared/ts/workbenchModels.ts";
import { workbenchRequest as send } from "../../shared/api/workbench";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import type { ResearchController } from "./useResearchController";

export function ResearchPlanControls({
  controller,
  onSelect,
  runs,
}: {
  controller: ResearchController;
  onSelect: (id: string) => void;
  runs: RunSummary[];
}) {
  const {
    act,
    busy,
    chooseSeed,
    cost,
    delay,
    end,
    error,
    folds,
    hypothesis,
    key,
    maxDrawdown,
    metric,
    minReturn,
    minTest,
    minTrades,
    name,
    payload,
    seed,
    seedId,
    setCost,
    setDelay,
    setEnd,
    setFolds,
    setHypothesis,
    setMaxDrawdown,
    setMetric,
    setMinReturn,
    setMinTest,
    setMinTrades,
    setName,
    setPlanOpen,
    setPreview,
    setPreviewKey,
    setStart,
    setSweep,
    setTab,
    setTest,
    setTrain,
    start,
    sweep,
    test,
    train,
    validPreview,
  } = controller;
  return (
    <Stack gap="lg">
      <Alert color="blue">
        Select using earlier data, then evaluate the next interval. This is a historical simulation. Prior overlapping runs are recorded; no result is certified as untouched evidence.
      </Alert>
      <Stack>
        <Title order={3}>Plan a walk-forward evaluation</Title>
        <Select
          label="Starting run"
          placeholder="Use settings from a successful run"
          searchable
          data={runs
            .filter((run) => run.status === "Succeeded" && (!run.input.research || run.id === seedId))
            .map((run) => ({
              value: run.id,
              label: `${strategyTitle(run.input.strategy.name)} · ${run.input.dataset.symbol} · ${run.id.slice(0, 8)}`,
            }))}
          value={seedId || null}
          onChange={chooseSeed}
        />
        <Text size="xs" c="dimmed">
          Settings are reused with a newly preserved current code version. Existing run artifacts remain unchanged. Each evaluation uses one market and timeframe.
        </Text>
        <TextInput label="Evaluation name" value={name} onChange={(event) => setName(event.currentTarget.value)} />
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput type="date" label="Research interval starts (UTC)" value={start} onChange={(event) => setStart(event.currentTarget.value)} />
          <TextInput type="date" label="Research interval ends (UTC)" value={end} onChange={(event) => setEnd(event.currentTarget.value)} />
          <NumberInput label="Training calendar days" value={train} min={7} max={2000} onChange={(value) => setTrain(Number(value))} />
          <NumberInput label="Test calendar days" value={test} min={7} max={365} onChange={(value) => setTest(Number(value))} />
          <NumberInput label="Number of folds" value={folds} min={1} max={12} onChange={(value) => setFolds(Number(value))} />
          <Select
            label="Select highest training"
            data={[
              { value: "net_pnl", label: "Net P&L (USD)" },
              { value: "sharpe", label: "Daily Sharpe" },
            ]}
            value={metric}
            onChange={(value) => value && setMetric(value)}
          />
        </SimpleGrid>
        <Textarea
          label="Candidate parameter grid (JSON)"
          description="Every candidate is retained. Ties use the original candidate order."
          minRows={2}
          value={sweep}
          onChange={(event) => setSweep(event.currentTarget.value)}
        />
        <Textarea label="Evaluation hypothesis" value={hypothesis} onChange={(event) => setHypothesis(event.currentTarget.value)} />
      </Stack>
      <Stack>
        <Title order={3}>Declare criteria & stress tests</Title>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <NumberInput label="Minimum training trades" value={minTrades} min={0} onChange={(value) => setMinTrades(Number(value))} />
          <NumberInput label="Minimum combined test trades" value={minTest} min={1} onChange={(value) => setMinTest(Number(value))} />
          <NumberInput label="Minimum test return (%)" value={minReturn} onChange={(value) => setMinReturn(Number(value))} />
          <NumberInput label="Maximum test drawdown (%)" value={maxDrawdown} min={0} max={100} onChange={(value) => setMaxDrawdown(Number(value))} />
          <NumberInput label="Stress cost multiplier" value={cost} min={1} max={10} onChange={(value) => setCost(Number(value))} />
          <NumberInput
            label="Additional execution delay (bars)"
            value={seed?.input.strategy.execution_model === "event-v1" ? 0 : delay}
            disabled={seed?.input.strategy.execution_model === "event-v1"}
            description={
              seed?.input.strategy.execution_model === "event-v1"
                ? "Unavailable for Pine event orders; baseline and cost stress remain supported."
                : "Zero omits delay stress."
            }
            min={0}
            max={20}
            onChange={(value) => setDelay(Number(value))}
          />
        </SimpleGrid>
        <Text size="xs" c="dimmed">
          Each selected candidate receives baseline and higher-cost tests, plus delayed-execution tests when enabled and supported. These scenarios never influence selection. Each fold starts and ends flat; test P&L is joined without resetting equity peaks.
        </Text>
        {validPreview && (
          <>
            <Text fw={600}>{validPreview.jobs} planned jobs · {validPreview.folds.length} chronological folds</Text>
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Fold</Table.Th><Table.Th>Training</Table.Th><Table.Th>Subsequent test</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {validPreview.folds.map((fold) => (
                  <Table.Tr key={fold.index}>
                    <Table.Td>{fold.index + 1}</Table.Td>
                    <Table.Td>{fold.train_start} → {fold.train_end}</Table.Td>
                    <Table.Td>{fold.test_start} → {fold.test_end}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </>
        )}
        {error && <Alert color="red" title="Research action failed">{error}</Alert>}
        <Group>
          <Button
            variant="light"
            loading={busy}
            onClick={() => void act(async () => {
              const value = await send<{ jobs: number; folds: Fold[] }>("/evaluations/preview", payload());
              setPreview(value);
              setPreviewKey(key);
            })}
          >
            Preview evaluation
          </Button>
          <Button
            disabled={!validPreview || busy}
            onClick={() => void act(async () => {
              const created = await send<EvaluationView>("/evaluations", payload());
              onSelect(created.id);
              setTab("Summary");
              setPreview(null);
              setPlanOpen(false);
            })}
          >
            Launch walk-forward
          </Button>
        </Group>
      </Stack>
    </Stack>
  );
}
