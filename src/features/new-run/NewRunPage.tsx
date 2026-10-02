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
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { IconCheck, IconChevronLeft, IconChevronRight, IconPlayerPlay } from "@tabler/icons-react";
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
import { initialNewRunInput, newRunSteps, parseSweep } from "./model";

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
    maxBatch,
    planCombos,
    planDatasets,
    planned,
    planTimeframes,
    presetName,
    preview,
    runInput,
    setInput,
    setNotice,
    setPresetName,
    setPreview,
    setStep,
    setSweepText,
    setWarmupChecks,
    state,
    step,
    strategy,
    sweepText,
    updateSweep,
    warmupChecks,
  } = controller;
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
  const sweep = parseSweep(sweepText);
  const summaries = [
    strategy
      ? `${strategyTitle(strategy.name)} · ${dataset ? `${dataset.symbol} ${input.timeframe}` : "choose a dataset"} · ${input.start} to ${input.end}`
      : "Choose a script and dataset",
    strategy
      ? Object.entries(input.parameters).map(([key, value]) => `${key} ${String(value)}`).join(" · ") || "No parameters"
      : "Loads from the script",
    `${input.stage} · capital $${input.capital.toLocaleString()} · fee $${input.fee} · slippage ${input.slippage}`,
    preview !== null ? `${preview} job${preview === 1 ? "" : "s"} validated` : "Grid, then validate",
  ];
  const sweepable = strategy
    ? Object.entries(strategy.parameters).filter(([, field]) =>
        ["enum", "boolean", "integer", "number"].includes(field.type),
      )
    : [];

  const parameterFields = !strategy ? (
    <Text size="sm" c="dimmed">Choose a script in step 1 to load its parameter schema.</Text>
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

  return (
    <>
      <PageHeader
        crumb="Research / Runs & compare"
        title="New run"
        actions={
          <Button
            variant="subtle"
            size="xs"
            onClick={() => {
              setInput(initialNewRunInput);
              setSweepText("{}");
              setPreview(null);
              setStep(0);
            }}
          >
            Clear draft
          </Button>
        }
      />
      <WorkbenchAlerts controller={controller} />
      <div className="wb-wizard">
        {strategy && dataset && <Group gap="sm" mb="md"><Text size="sm" fw={600}>Current stage for these settings</Text><StrategyStageBadge stage={configurationStage?.stage || 0} {...configurationStatus} showFinding /></Group>}
        <ol className="wb-steps" aria-label="Steps">
          {newRunSteps.map((label, index) => (
            <li key={label}>
              <button
                type="button"
                className={`wb-step${index === step ? " current" : ""}${index < step ? " done" : ""}`}
                aria-current={index === step ? "step" : undefined}
                onClick={() => setStep(index)}
              >
                <span className="wb-step-num">{index < step ? <IconCheck size={13} /> : index + 1}</span>
                <span><b>{label}</b><small>{summaries[index]}</small></span>
              </button>
            </li>
          ))}
        </ol>
        <section className="wb-wizard-form" aria-label={newRunSteps[step]}>
          <h2>{step + 1}. {newRunSteps[step]}</h2>
          {step === 0 && (
            <>
              <Select
                label="Strategy"
                placeholder="Choose a Python strategy"
                searchable
                data={state.strategies.map((candidate) => ({ value: candidate.id, label: strategyTitle(candidate.name) }))}
                value={input.strategy_id || null}
                onChange={(value) => value && chooseStrategy(value)}
              />
              {strategy?.migration_scope && <Alert color="blue" title="Signal adapter scope">{strategy.migration_scope}</Alert>}
              <Select
                label="Dataset version"
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
                  setPreview(null);
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
            </>
          )}
          {step === 1 && (
            <>
              {parameterFields}
              <SimpleGrid cols={{ base: 1, sm: 2 }} mt="sm">
                <Select
                  label="Load saved preset"
                  placeholder="Select preset"
                  data={state.presets.map((preset) => ({ value: preset.id, label: preset.name }))}
                  onChange={(id) => {
                    const preset = state.presets.find((candidate) => candidate.id === id);
                    if (preset) {
                      setInput(preset.input);
                      setSweepText(JSON.stringify(preset.input.sweep || {}));
                      setPreview(null);
                    }
                  }}
                />
                <Group align="end" wrap="nowrap">
                  <TextInput label="Preset name" value={presetName} onChange={(event) => setPresetName(event.currentTarget.value)} style={{ flex: 1 }} />
                  <Button
                    variant="light"
                    disabled={!presetName || busy}
                    onClick={() => void action(async () => {
                      await request("/presets", { name: presetName, input: runInput() });
                      setNotice("Preset saved.");
                    })}
                  >
                    Save preset
                  </Button>
                </Group>
              </SimpleGrid>
            </>
          )}
          {step === 2 && (
            <>
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
              <Select
                label="Run purpose"
                description="Records the intent of this run. Testing milestones are earned from its evidence."
                data={["Exploratory", "Evaluation"]}
                value={input.stage}
                onChange={(value) => value && change("stage", value)}
              />
              <Textarea label="Question / hypothesis" placeholder="What does this experiment test?" value={input.hypothesis} onChange={(event) => change("hypothesis", event.currentTarget.value)} />
              <TextInput label="Development ends (before scored start)" type="date" value={input.development_end} onChange={(event) => change("development_end", event.currentTarget.value)} />
              <Textarea
                label="Evaluation criteria"
                description="Required for Evaluation. Recorded before execution; outcomes require your research judgment."
                value={input.criteria}
                onChange={(event) => change("criteria", event.currentTarget.value)}
              />
            </>
          )}
          {step === 3 && (
            <>
              <Text size="sm" c="dimmed">Every combination below becomes one job. Nothing launches until you validate and then press Launch.</Text>
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
                  setPreview(null);
                }}
                styles={{ input: { fontFamily: "var(--mono)" } }}
              />
              <Group>
                <Button
                  variant="light"
                  loading={busy}
                  onClick={() => void action(async () => {
                    setPreview(null);
                    const result = await request<{ jobs: number; warmup: WarmupCheck[] }>("/preview", runInput());
                    setPreview(result.jobs);
                    setWarmupChecks(result.warmup || []);
                  })}
                >
                  Validate & preview
                </Button>
                <Button
                  leftSection={<IconPlayerPlay size={16} />}
                  disabled={preview === null || busy}
                  onClick={() => void action(async () => {
                    const runs = await request<Run[]>("/runs", runInput());
                    setNotice(`${runs.length} run(s) queued. You can leave this page while they execute.`);
                    setPreview(null);
                    go("runs");
                  })}
                >
                  Launch {preview || ""} {preview === 1 ? "run" : "runs"}
                </Button>
              </Group>
              {preview !== null && (
                <Alert color="teal" title={`${preview} job${preview === 1 ? "" : "s"} ready`}>
                  Inputs passed preflight. Launching preserves this experiment's code and resolved parameters.
                </Alert>
              )}
              {preview !== null && warmupChecks.map((check, index) => (
                <Alert key={index} color={check.status === "insufficient" ? "orange" : "teal"} title={`${check.symbol} ${check.timeframe}: warmup ${check.status}`}>
                  <Text size="sm">{check.available_bars} completed bars before scoring; {check.required_bars} required.</Text>
                  <Text size="xs">Parameters: {JSON.stringify(check.parameters)}</Text>
                  {check.warning && <Text size="sm">{check.warning}</Text>}
                </Alert>
              ))}
            </>
          )}
          <div className="wb-wizard-nav">
            <Button variant="default" leftSection={<IconChevronLeft size={14} />} disabled={step === 0} onClick={() => setStep((current) => Math.max(0, current - 1))}>Back</Button>
            {step < newRunSteps.length - 1 && (
              <Button ml="auto" rightSection={<IconChevronRight size={14} />} onClick={() => setStep((current) => Math.min(newRunSteps.length - 1, current + 1))}>
                Continue to {newRunSteps[step + 1].toLowerCase()}
              </Button>
            )}
          </div>
        </section>
        <aside className="wb-plan" aria-label="Launch plan">
          <div className="wb-crumb">Launch plan</div>
          <div>
            <span className="wb-plan-big">{planned ?? "—"}</span>{" "}<b>{planned === 1 ? "job" : "jobs"}</b>{" "}
            <Text span size="xs" c="dimmed">{preview !== null ? "validated" : planned === null ? "sweep JSON is invalid" : "estimated"}</Text>
          </div>
          <div className={`wb-meter${(planned || 0) > maxBatch ? " over" : ""}`}>
            <span style={{ width: `${Math.min(100, ((planned || 0) / maxBatch) * 100)}%` }} />
          </div>
          <Text size="xs" c={(planned || 0) > maxBatch ? "red" : "dimmed"}>
            {planned ?? 0} of {maxBatch} allowed per launch · {state.limits.concurrency} run at once
          </Text>
          {planCombos !== null && (
            <div className="wb-plan-formula">
              {Math.max(1, planDatasets)} dataset{planDatasets === 1 ? "" : "s"} × {planTimeframes} timeframe{planTimeframes === 1 ? "" : "s"} × {planCombos} parameter set{planCombos === 1 ? "" : "s"}
            </div>
          )}
          <dl className="wb-kv">
            <dt>Script</dt><dd>{strategy ? strategyTitle(strategy.name) : "—"}</dd>
            <dt>Dataset</dt><dd>{dataset ? `${dataset.symbol} · ${shortId(dataset.id)}` : "—"}</dd>
            <dt>Window (UTC)</dt><dd>{input.start} → {input.end}</dd>
            <dt>Session</dt><dd>{input.session}</dd>
            <dt>Run purpose</dt><dd>{input.stage}</dd>
            <dt>Capital</dt><dd>${input.capital.toLocaleString()}</dd>
            <dt>Fee</dt><dd>${input.fee}</dd>
            <dt>Slippage</dt><dd>{input.slippage} ticks</dd>
            <dt>Warmup</dt><dd>{input.warmup_days} days</dd>
          </dl>
          <Text size="xs" c="dimmed">Every resolved default is saved with each run. Each variant keeps its own artifacts and status.</Text>
        </aside>
      </div>
    </>
  );
}
