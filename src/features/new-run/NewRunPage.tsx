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
          checked={Boolean(input.parameters[key])}
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
      <TextInput label="Question" placeholder="What does this experiment test?" value={input.hypothesis} onChange={(event) => change("hypothesis", event.currentTarget.value)} />
      <Textarea
        required={evaluation}
        label="Pass criteria"
        description="Required to evaluate. Saved before the run so results can’t move the goalposts."
        placeholder="e.g. at least 60 trades, positive return, drawdown no deeper than 20%"
        autosize
        minRows={2}
        value={input.criteria}
        onChange={(event) => change("criteria", event.currentTarget.value)}
      />
      <TextInput
        required={evaluation}
        label="Development data ends"
        description="Must be before the start date."
        type="date"
        value={input.development_end}
        onChange={(event) => change("development_end", event.currentTarget.value)}
      />
    </Stack>
  );
  const clearDraft = () => {
    setInput(initialNewRunInput);
    setSweepText("{}");
    setEditingVariants(false);
    setPresetName("");
  };
  const setRange = (years: number | "ytd" | "all") => {
    if (!dataset) return;
    const last = dataset.last.slice(0, 10);
    const first = dataset.first.slice(0, 10);
    const start = years === "all" ? first
      : years === "ytd" ? `${last.slice(0, 4)}-01-01`
        : new Date(Date.parse(`${last}T00:00:00Z`) - years * 365.25 * 86_400_000).toISOString().slice(0, 10);
    setInput((current) => ({ ...current, start: start < first ? first : start, end: last }));
  };
  const extraMarkets = (input.dataset_ids || []).filter((id) => id !== input.dataset_id);
  const marketSummary = dataset
    ? [dataset.symbol, ...extraMarkets.map((id) => state.datasets.find((candidate) => candidate.id === id)?.symbol || shortId(id))].join(" + ")
    : "—";
  const jobs = current?.jobs || 0;
  const purposes = [
    { value: "Exploratory", label: "Explore", hint: "Try an idea. Not scored." },
    { value: "Evaluation", label: "Evaluate", hint: "Score against criteria you set first." },
  ];

  return (
    <>
      <PageHeader crumb="Backtest" title="New backtest" actions={
        <Button variant="subtle" size="xs" onClick={clearDraft}>Clear draft</Button>
      } />
      <WorkbenchAlerts controller={controller} />
      <div className="wb-content wb-new-backtest">
        <p className="wb-page-lede">Pick what to test, check the settings, launch. Drafts save automatically.</p>
        <div className="wb-backtest-layout">
          <div className="wb-backtest-steps" aria-label="Backtest setup">
            <Select
              className="wb-start-from"
              label="Start from"
              placeholder={state.presets.length ? `Blank, or one of ${state.presets.length} presets` : "No saved presets"}
              disabled={!state.presets.length}
              searchable
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
            <section className="wb-card wb-backtest-step" aria-label="What to test">
              <h2><span className="wb-step-number">1</span> What to test</h2>
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                <Select
                  label="Strategy"
                  placeholder="Choose a strategy"
                  searchable
                  data={state.strategies.map((candidate) => ({ value: candidate.id, label: strategyTitle(candidate.name) }))}
                  value={input.strategy_id || null}
                  onChange={(value) => value && chooseStrategy(value)}
                />
                <Select
                  label="Market"
                  placeholder="Choose market data"
                  description={dataset ? `${dataset.rows.toLocaleString()} bars · $${dataset.point_value}/point · tick ${dataset.tick_size} · version ${shortId(dataset.id)}` : undefined}
                  data={state.datasets.map((candidate) => ({
                    value: candidate.id,
                    label: `${candidate.symbol} · data to ${candidate.last.slice(0, 10)} · ${shortId(candidate.id)}`,
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
                <Select
                  label="Timeframe"
                  description="Only timeframes this strategy supports are shown."
                  data={strategy?.timeframes || []}
                  value={input.timeframe}
                  onChange={(value) => value && change("timeframe", value)}
                />
                <Select label="Session" data={sessionOptions} value={input.session} onChange={(value) => value && change("session", value)} />
                <TextInput label="Start date (UTC)" type="date" value={input.start} onChange={(event) => change("start", event.currentTarget.value)} />
                <TextInput label="End date (UTC, inclusive)" type="date" value={input.end} onChange={(event) => change("end", event.currentTarget.value)} />
              </SimpleGrid>
              <Group gap={6} mt="xs" className="wb-range-buttons">
                {([["ytd", "YTD"], [1, "1 year"], [5, "5 years"], ["all", "All data"]] as const).map(([value, label]) => (
                  <Button key={label} size="compact-xs" variant="default" disabled={!dataset} onClick={() => setRange(value)}>{label}</Button>
                ))}
              </Group>
            </section>

            <section className="wb-card wb-backtest-step" aria-label="Settings">
              <h2><span className="wb-step-number">2</span> Settings</h2>
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                {parameterFields}
              </SimpleGrid>
              {strategy?.migration_scope && <Text size="xs" c="dimmed" mt="xs">{strategy.migration_scope}</Text>}
              <details className="wb-costs">
                <summary>
                  <strong>Costs &amp; execution:</strong> ${input.capital.toLocaleString()} capital · ${input.fee} fee per contract per side · {input.slippage} tick slippage · {input.warmup_days}-day warm-up · {input.timeout} s timeout <span className="wb-link">Edit</span>
                </summary>
                <SimpleGrid cols={{ base: 1, sm: 2 }} mt="sm">
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
                <Text size="xs" c="dimmed" mt="xs">
                  {strategy?.execution_model === "event-v1"
                    ? "Whole contracts. This strategy uses its declared bar-close/next-open orders and working brackets; see its migration scope."
                    : "Fixed whole contracts. Decisions use completed bars and fill at the next available bar open."}{" "}
                  Final positions close at the final bar close. No cash flows.
                </Text>
              </details>
              <Switch
                mt="md"
                label="Test variants"
                description="Run the same setup on more markets, timeframes or setting values."
                checked={variants}
                onChange={(event) => {
                  const enabled = event.currentTarget.checked;
                  setEditingVariants(enabled);
                  if (!enabled) {
                    setInput((current) => ({ ...current, dataset_ids: [], timeframes: [], sweep: {} }));
                    setSweepText("{}");
                  }
                }}
              />
              {variants && (
                <Stack gap="sm" mt="sm" className="wb-variants">
                  <div>
                    <Text size="sm" fw={600} mb={4}>Also run on</Text>
                    <Chip.Group
                      multiple
                      value={extraMarkets}
                      onChange={(value) => change("dataset_ids", value)}
                    >
                      <Group gap={6}>
                        {state.datasets
                          .filter((candidate) => candidate.id !== input.dataset_id)
                          .map((candidate) => (
                            <Chip key={candidate.id} value={candidate.id} size="sm">
                              {candidate.symbol} · {shortId(candidate.id)}
                            </Chip>
                          ))}
                      </Group>
                    </Chip.Group>
                  </div>
                  {strategy && strategy.timeframes.length > 1 && (
                    <MultiSelect
                      searchable
                      label="Also run on timeframes"
                      data={strategy.timeframes.filter((timeframe) => timeframe !== input.timeframe)}
                      value={(input.timeframes || []).filter((timeframe) => timeframe !== input.timeframe)}
                      onChange={(value) => change("timeframes", value)}
                    />
                  )}
                  {sweepable.length > 0 && (
                    <Stack gap={8}>
                      <Text size="sm" fw={600}>Try these setting values</Text>
                      {!sweep && <Text size="xs" c="red">Fix the JSON below to use the value builder.</Text>}
                      {sweepable.map(([key, field]) => {
                        const values = (sweep?.[key] as unknown[]) || [];
                        if (field.type === "enum" || field.type === "boolean") {
                          const choices = field.type === "boolean" ? ["true", "false"] : field.choices || [];
                          return (
                            <div className="wb-dim" key={key}>
                              <span>{key.replaceAll("_", " ")}</span>
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
                            <span>{key.replaceAll("_", " ")}</span>
                            <TextInput
                              size="xs"
                              aria-label={`Values to try for ${key}`}
                              placeholder="Comma-separated, e.g. 10, 20, 40"
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
                    description={'The value builder writes this field. {} runs one setup; {"lookback": [10, 20, 40]} runs a grid.'}
                    autosize
                    minRows={2}
                    value={sweepText}
                    onChange={(event) => setSweepText(event.currentTarget.value)}
                    styles={{ input: { fontFamily: "var(--mono)" } }}
                  />
                </Stack>
              )}
            </section>

            <section className="wb-card wb-backtest-step" aria-label="Purpose">
              <h2><span className="wb-step-number">3</span> Why are you running it?</h2>
              <div className="wb-purpose-cards" role="group" aria-label="Run purpose">
                {purposes.map((purpose) => (
                  <button
                    key={purpose.value}
                    type="button"
                    className={`wb-choice${input.stage === purpose.value ? " active" : ""}`}
                    aria-pressed={input.stage === purpose.value}
                    onClick={() => change("stage", purpose.value)}
                  >
                    <strong>{purpose.label}</strong>
                    <span>{purpose.hint}</span>
                  </button>
                ))}
              </div>
              {evaluation ? <div className="wb-step-body">{recordFields}</div> : (
                <details className="wb-costs">
                  <summary>Add research notes (optional)</summary>
                  <div className="wb-step-body">{recordFields}</div>
                </details>
              )}
            </section>
          </div>

          <aside className="wb-card wb-backtest-summary" aria-label="Summary">
            <h2>Summary</h2>
            <dl>
              <dt>Strategy</dt><dd>{strategy ? strategyTitle(strategy.name) : "—"}</dd>
              <dt>Market</dt><dd>{marketSummary}</dd>
              <dt>Window</dt><dd>{input.start && input.end ? `${input.start} – ${input.end} · ${input.timeframe}` : "—"}</dd>
              <dt>Purpose</dt><dd>{evaluation ? "Evaluate" : "Explore"}</dd>
            </dl>
            {strategy && dataset && (
              <div className="wb-summary-stage">
                <Text size="xs" c="dimmed">Current stage of this setup</Text>
                <StrategyStageBadge stage={configurationStage?.stage || 0} {...configurationStatus} />
              </div>
            )}
            <div className="wb-summary-count" aria-live="polite">
              {!sweep && <Text size="sm" c="red">Enter valid sweep JSON with an array for each parameter.</Text>}
              {current?.error && <Alert color="red" title="Check these settings">{current.error}{" "}
                <Button variant="subtle" size="compact-xs" onClick={() => setRetry(value => value + 1)}>Check again</Button>
              </Alert>}
              {!readyToCheck && <Text size="sm" c="dimmed">{evaluation ? "Pick a strategy, market and dates, and set pass criteria and the development end." : "Pick a strategy, market and dates."}</Text>}
              {payload && readyToCheck && !current && <Text size="sm">Checking settings…</Text>}
              {!!jobs && (
                <>
                  <strong>{jobs} {jobs === 1 ? "backtest" : "backtests"}</strong>
                  <Text size="xs" c="dimmed">
                    {jobs > state.limits.maxBatch ? `Over the ${state.limits.maxBatch}-per-launch limit: remove a market or a value.` : `Runs ${state.limits.concurrency} at a time · settings checked`}
                  </Text>
                </>
              )}
            </div>
            {!!current?.warmup?.length && <details className="wb-costs" open={current.warmup.some(item => item.status === "insufficient") || undefined}>
              <summary>Warm-up checks ({current.warmup.length})</summary>
              {current.warmup.map((item, index) => <Text size="xs" key={index} mt="xs">
                {item.symbol} {item.timeframe} · {item.status} · {item.available_bars} bars available, {item.required_bars} required
                {item.warning && " · " + item.warning} · {JSON.stringify(item.parameters)}
              </Text>)}
            </details>}
            <Button fullWidth leftSection={<IconPlayerPlay size={16} />} disabled={!jobs || busy}
              onClick={() => void action(async () => {
                const runs = await request<Run[]>("/runs", payload);
                setNotice(runs.length + " backtest(s) queued. You can leave this page while they run.");
                go("runs");
              })}>
              {jobs > 1 ? `Launch ${jobs} backtests` : "Launch backtest"}
            </Button>
            <details className="wb-costs">
              <summary>Save as preset</summary>
              <Group align="end" mt="xs" gap="xs">
                <TextInput style={{ flex: 1 }} label="Preset name" value={presetName} onChange={event => setPresetName(event.currentTarget.value)} />
                <Button variant="light" disabled={!presetName.trim() || !payload || busy}
                  onClick={() => void action(async () => {
                    await request("/presets", { name: presetName.trim(), input: payload });
                    setNotice("Preset saved.");
                  })}>Save</Button>
              </Group>
            </details>
          </aside>
        </div>
      </div>
    </>
  );
}
