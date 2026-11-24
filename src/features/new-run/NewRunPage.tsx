import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Chip,
  Group,
  MultiSelect,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { IconPlayerPlay } from "@tabler/icons-react";
import type { Run } from "../../../shared/ts/workbenchModels.ts";
import { workbenchRequest as request } from "../../shared/api/workbench";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import { PageHeader } from "../../shared/ui/PageHeader";
import { StrategyStageBadge } from "../../shared/ui/StrategyStageBadge";
import { testingEvidence } from "../../../shared/ts/evidence.ts";
import { useStrategyStages } from "../../shared/ui/strategyStageContext";
import { WorkbenchAlerts } from "../workspace/WorkbenchChrome";
import type { WorkbenchController } from "../workspace/useWorkbenchController";
import { sessionOptions, shortId, type WarmupCheck } from "../workspace/workbenchModel";
import { initialNewRunInput, parseSweep } from "./model";

export function NewRunPage({ controller }: { controller: WorkbenchController }) {
  const { statuses } = useStrategyStages();
  const {
    action,
    busy,
    change,
    chooseStrategy,
    dataset,
    go,
    input,
    presetName,
    setInput,
    setNotice,
    setPresetName,
    setSweepText,
    state,
    strategy,
    sweepText,
    updateSweep,
  } = controller;
  const [editingVariants, setEditingVariants] = useState(false);
  const [retry, setRetry] = useState(0);
  const sweep = useMemo(() => parseSweep(sweepText), [sweepText]);
  const payload = useMemo(() => sweep && ({
    ...input,
    dataset_ids: [...new Set([input.dataset_id, ...(input.dataset_ids || [])])],
    timeframes: [...new Set([input.timeframe, ...(input.timeframes || [])])],
    sweep,
  }), [input, sweep]);
  const variants = editingVariants || !sweep || Object.keys(sweep).length > 0
    || !!input.dataset_ids?.some(id => id !== input.dataset_id)
    || !!input.timeframes?.some(tf => tf !== input.timeframe);
  const evaluation = input.stage === "Evaluation";
  const readyToCheck = !!(strategy && dataset && input.start && input.end
    && (!evaluation || (input.criteria?.trim() && input.development_end)));
  const [check, setCheck] = useState<{
    input: typeof payload; retry: number; jobs?: number; warmup?: WarmupCheck[]; error?: string;
  } | null>(null);
  useEffect(() => {
    if (!payload || !readyToCheck) return;
    const abort = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const result = await request<{ jobs: number; warmup: WarmupCheck[] }>("/preview", payload, "POST", abort.signal);
        if (!abort.signal.aborted) setCheck({ input: payload, retry, ...result });
      } catch (error) {
        if (!abort.signal.aborted) setCheck({ input: payload, retry, error: error instanceof Error ? error.message : String(error) });
      }
    }, 350);
    return () => { window.clearTimeout(timer); abort.abort(); };
  }, [payload, readyToCheck, retry]);
  const current = readyToCheck && check && check.input === payload && check.retry === retry ? check : null;
  if (!state) return null;
  const configurationStage = strategy && dataset ? testingEvidence(strategy, state.runs, state.evaluations || [], dataset.symbol).configurations
    .filter((config) => config.timeframe === input.timeframe && config.session === input.session
      && Object.keys(config.parameters).length === Object.keys(input.parameters).length
      && Object.entries(config.parameters).every(([key, value]) => JSON.stringify(value) === JSON.stringify(input.parameters[key])))
    .sort((a, b) => b.stage - a.stage)[0] : undefined;
  const previousRun = strategy && dataset && state.runs.find(run => run.input.strategy.id === strategy.id && run.input.dataset.symbol === dataset.symbol
    && run.input.timeframe === input.timeframe && run.input.session === input.session
    && Object.keys(run.input.parameters).length === Object.keys(input.parameters).length
    && Object.entries(run.input.parameters).every(([key, value]) => JSON.stringify(value) === JSON.stringify(input.parameters[key])));
  const configurationStatus = configurationStage?.lifecycle || (previousRun ? statuses.byRun.get(previousRun.id) : undefined);
  const sweepable = strategy
    ? Object.entries(strategy.parameters).filter(([, field]) =>
        ["enum", "boolean", "integer", "number"].includes(field.type),
      )
    : [];

  const parameterFields = !strategy ? (
    <Text size="sm" c="dimmed">Choose a strategy to see its parameters.</Text>
  ) : (
    Object.entries(strategy.parameters).map(([key, field]) =>
      field.type === "boolean" ? (
        <Checkbox
          key={key}
          label={key.replaceAll("_", " ")}
          description={field.description}
          checked={Boolean(input.parameters[key] ?? field.default)}
          onChange={(event) => change("parameters", { ...input.parameters, [key]: event.currentTarget.checked })}
        />
      ) : field.type === "enum" ? (
        <Select
          key={key}
          label={key.replaceAll("_", " ")}
          description={field.description}
          data={field.choices || []}
          value={String(input.parameters[key])}
          onChange={(value) => change("parameters", { ...input.parameters, [key]: value })}
        />
      ) : ["integer", "number"].includes(field.type) ? (
        <NumberInput
          key={key}
          label={key.replaceAll("_", " ")}
          description={field.description}
          min={field.minimum}
          max={field.maximum}
          allowDecimal={field.type !== "integer"}
          value={input.parameters[key] as number}
          onChange={(value) => change("parameters", { ...input.parameters, [key]: value })}
        />
      ) : (
        <TextInput
          key={key}
          label={key.replaceAll("_", " ")}
          description={field.description}
          value={String(input.parameters[key] || "")}
          onChange={(event) => change("parameters", { ...input.parameters, [key]: event.currentTarget.value })}
        />
      ),
    )
  );

  const recordFields = (
    <Stack gap="sm">
      <Textarea label="Question / hypothesis" placeholder="What does this experiment test?" value={input.hypothesis} onChange={(event) => change("hypothesis", event.currentTarget.value)} />
      <TextInput required={evaluation} label="Development ends (before scored start)" type="date" value={input.development_end} onChange={(event) => change("development_end", event.currentTarget.value)} />
      <Textarea
        required={evaluation} label="Evaluation criteria"
        description="Required for Evaluation. Recorded before execution; outcomes require your research judgment."
        value={input.criteria}
        onChange={(event) => change("criteria", event.currentTarget.value)}
      />
    </Stack>
  );

  return (
    <>
      <PageHeader crumb="Research" title="New backtest" actions={
        <Button variant="subtle" size="xs" onClick={() => {
          setInput(initialNewRunInput);
          setSweepText("{}");
          setEditingVariants(false);
          setPresetName("");
        }}>Clear draft</Button>
      } />
      <WorkbenchAlerts controller={controller} />
      <section className="wb-content" aria-label="Backtest setup" style={{ maxWidth: 850, width: "100%", marginInline: "auto" }}>
        <Stack gap="md" className="wb-card">
          <Select
            label="Use preset"
            placeholder={state.presets.length ? "Select preset" : "No saved presets"}
            disabled={!state.presets.length}
            value={null}
            data={state.presets.map((preset) => ({ value: preset.id, label: preset.name }))}
            onChange={(id) => {
              const preset = state.presets.find((candidate) => candidate.id === id);
              if (preset) {
                setInput({ ...initialNewRunInput, ...preset.input });
                setSweepText(JSON.stringify(preset.input.sweep || {}));
                setEditingVariants(false);
              }
            }}
          />
          <Select
            label="Strategy"
            placeholder="Choose a Python strategy"
            searchable
            data={state.strategies.map((candidate) => ({ value: candidate.id, label: strategyTitle(candidate.name) }))}
            value={input.strategy_id || null}
            onChange={(value) => value && chooseStrategy(value)}
          />
          <Select
            label="Market / dataset version"
            placeholder="Choose a registered archive"
            data={state.datasets.map((candidate) => ({
              value: candidate.id,
              label: `${candidate.symbol} · ${candidate.first.slice(0, 10)} → ${candidate.last.slice(0, 10)} · ${shortId(candidate.id)}`,
            }))}
            value={input.dataset_id || null}
            onChange={(value) => {
              if (!value) return;
              const nextDataset = state.datasets.find((candidate) => candidate.id === value)!;
              setInput((current) => ({
                ...current,
                dataset_id: value,
                end: nextDataset.last.slice(0, 10),
                start:
                  current.start < nextDataset.first.slice(0, 10) || current.start > nextDataset.last.slice(0, 10)
                    ? nextDataset.first.slice(0, 10)
                    : current.start,
              }));
            }}
          />
          {dataset && (
            <Text size="xs" c="dimmed">
              {dataset.rows.toLocaleString()} bars · UTC · USD · ${dataset.point_value}/point · tick {dataset.tick_size}
            </Text>
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select label="Timeframe" data={strategy?.timeframes || []} value={input.timeframe} onChange={(value) => value && change("timeframe", value)} />
            <Select label="Session" data={sessionOptions} value={input.session} onChange={(value) => value && change("session", value)} />
            <TextInput label="Start date (UTC)" type="date" value={input.start} onChange={(event) => change("start", event.currentTarget.value)} />
            <TextInput label="End date (UTC, inclusive)" type="date" value={input.end} onChange={(event) => change("end", event.currentTarget.value)} />
          </SimpleGrid>
          <details><summary>Strategy parameters</summary>
            <Stack mt="sm" gap="sm">
              {parameterFields}
              {strategy?.migration_scope && <Text size="xs" c="dimmed">{strategy.migration_scope}</Text>}
            </Stack>
          </details>
          <details><summary>Costs and execution · ${input.fee}/contract/side · {input.slippage} ticks/side</summary>
            <Stack mt="sm" gap="sm">
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                {(
                  [
                    ["capital", "Initial capital (USD)"],
                    ["fee", "Fee / contract / side (USD)"],
                    ["slippage", "Slippage / side (ticks)"],
                    ["warmup_days", "Warmup calendar days"],
                    ["timeout", "Timeout (seconds)"],
                  ] as const
                ).map(([key, label]) => (
                  <NumberInput
                    key={key}
                    label={label}
                    min={key === "capital" || key === "timeout" ? 1 : 0}
                    value={input[key]}
                    onChange={(value) => change(key, Number(value))}
                  />
                ))}
              </SimpleGrid>
              <Text size="xs" c="dimmed">
                {strategy?.execution_model === "event-v1"
                  ? "Whole contracts. This strategy uses its declared bar-close/next-open orders and working brackets; see its migration scope."
                  : "Fixed whole contracts. Decisions use completed bars and fill at the next available bar open."}{" "}
                Final positions close at the final bar close. No cash flows.
              </Text>
            </Stack>
          </details>
          <Select label="Run purpose" data={["Exploratory", "Evaluation"]} value={input.stage}
            onChange={value => value && change("stage", value)} />
          {evaluation ? recordFields : <details><summary>Research notes and criteria</summary>{recordFields}</details>}
          <Switch label="Test multiple variants" checked={variants} onChange={event => {
            const enabled = event.currentTarget.checked;
            setEditingVariants(enabled);
            if (!enabled) {
              setInput(current => ({ ...current, dataset_ids: [], timeframes: [], sweep: {} }));
              setSweepText("{}");
            }
          }} />
          {variants && <Stack gap="sm">
            <MultiSelect
              searchable
              label="Additional dataset versions"
              description="Optional: run the same experiment on more markets."
              data={state.datasets.filter((candidate) => candidate.id !== input.dataset_id).map((candidate) => ({ value: candidate.id, label: `${candidate.symbol} · ${shortId(candidate.id)}` }))}
              value={(input.dataset_ids || []).filter((id) => id !== input.dataset_id)}
              onChange={(value) => change("dataset_ids", value)}
            />
            <MultiSelect
              searchable
              label="Additional timeframes"
              description={
                strategy && strategy.timeframes.length <= 1
                  ? `${strategyTitle(strategy.name)} runs on ${strategy.timeframes[0] || "one timeframe"} only.`
                  : "Datasets × timeframes × parameter combinations form the batch."
              }
              data={(strategy?.timeframes || []).filter((timeframe) => timeframe !== input.timeframe)}
              value={(input.timeframes || []).filter((timeframe) => timeframe !== input.timeframe)}
              onChange={(value) => change("timeframes", value)}
            />
            {sweepable.length > 0 && (
              <Stack gap={8}>
                <Text size="sm" fw={600}>Parameter sweep</Text>
                {!sweep && <Text size="xs" c="red">Fix the JSON below to use the sweep builder.</Text>}
                {sweepable.map(([key, field]) => {
                  const values = (sweep?.[key] as unknown[]) || [];
                  if (field.type === "enum" || field.type === "boolean") {
                    const choices = field.type === "boolean" ? ["true", "false"] : field.choices || [];
                    return (
                      <div className="wb-dim" key={key}>
                        <span>{key}</span>
                        <Chip.Group
                          multiple
                          value={values.map(String)}
                          onChange={(value) =>
                            updateSweep(
                              key,
                              field.type === "boolean"
                                ? value.map((choice) => choice === "true")
                                : choices.filter((choice) => value.includes(choice)),
                            )
                          }
                        >
                          <Group gap={6}>
                            {choices.map((choice) => <Chip key={choice} value={choice} size="xs" disabled={!sweep}>{choice}</Chip>)}
                          </Group>
                        </Chip.Group>
                      </div>
                    );
                  }
                  return (
                    <div className="wb-dim" key={key}>
                      <span>{key}</span>
                      <TextInput
                        size="xs"
                        aria-label={`Values to try for ${key}`}
                        placeholder="Comma-separated values, e.g. 10, 20, 40"
                        disabled={!sweep}
                        key={`${key}-${values.join(",")}`}
                        defaultValue={values.join(", ")}
                        onBlur={(event) =>
                          updateSweep(
                            key,
                            event.currentTarget.value.split(",").map((value) => value.trim()).filter(Boolean).map(Number).filter((value) => Number.isFinite(value)),
                          )
                        }
                      />
                    </div>
                  );
                })}
              </Stack>
            )}
            <Textarea
              label="Parameter sweep (JSON)"
              description={'The builder above writes this field. Use {} for a single run, or {"lookback": [10, 20, 40]} for a grid.'}
              autosize
              minRows={2}
              value={sweepText}
              onChange={(event) => {
                setSweepText(event.currentTarget.value);
              }}
              styles={{ input: { fontFamily: "var(--mono)" } }}
            />
          </Stack>}
          <details><summary>Save these settings as a preset</summary>
            <Group align="end" mt="xs">
              <TextInput label="Preset name" value={presetName} onChange={event => setPresetName(event.currentTarget.value)} />
              <Button variant="light" disabled={!presetName.trim() || !payload || busy}
                onClick={() => void action(async () => {
                  await request("/presets", { name: presetName.trim(), input: payload });
                  setNotice("Preset saved.");
                })}>Save preset</Button>
            </Group>
          </details>
          {strategy && dataset && <Group gap="xs"><Text size="xs">Current stage</Text>
            <StrategyStageBadge stage={configurationStage?.stage || 0} {...configurationStatus} />
          </Group>}
          <div aria-live="polite">
            {!sweep && <Text size="sm" c="red">Enter valid sweep JSON with an array for each parameter.</Text>}
            {current?.error && <Alert color="red" title="Check these settings">{current.error}{" "}
              <Button variant="subtle" size="compact-xs" onClick={() => setRetry(value => value + 1)}>Check again</Button>
            </Alert>}
            {payload && readyToCheck && !current && <Text size="sm">Checking settings…</Text>}
            {!!current?.jobs && <Text size="sm">{current.jobs} {current.jobs === 1 ? "run" : "runs"} ready to launch</Text>}
          </div>
          {!!current?.warmup?.length && <details open={current.warmup.some(item => item.status === "insufficient") || undefined}>
            <summary>Warmup checks ({current.warmup.length})</summary>
            {current.warmup.map((item, index) => <Text size="xs" key={index} mt="xs">
              {item.symbol} {item.timeframe} · {item.status} · {item.available_bars} bars available, {item.required_bars} required
              {item.warning && " · " + item.warning} · {JSON.stringify(item.parameters)}
            </Text>)}
          </details>}
          <Button leftSection={<IconPlayerPlay size={16} />} disabled={!current?.jobs || busy}
            onClick={() => void action(async () => {
              const runs = await request<Run[]>("/runs", payload);
              setNotice(runs.length + " run(s) queued. You can leave this page while they execute.");
              go("runs");
            })}>
            {current?.jobs && current.jobs > 1 ? "Launch " + current.jobs + " runs" : "Launch backtest"}
          </Button>
        </Stack>
      </section>
    </>
  );
}
