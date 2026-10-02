import { useState } from "react";
import { Alert, Button, Group, NumberInput, SimpleGrid, Stack, Text, Textarea, TextInput } from "@mantine/core";
import { forwardFailures, readinessChecks, readinessEvidenceSnapshot, validReadinessReview, type ReadinessPhase } from "../../../shared/ts/readiness.ts";
import { runConfigurationKey } from "../../../shared/ts/evidence.ts";
import type { WorkbenchController } from "../workspace/useWorkbenchController";
import { useStrategyStages } from "../../shared/ui/strategyStageContext";
import { workbenchRequest as request } from "../../shared/api/workbench";
import { ResearchStages } from "./ResearchStages";

const phaseTitles: Record<ReadinessPhase, string> = {
  robustness: "Record robustness and execution validation",
  "forward-plan": "Freeze a prospective paper-testing plan",
  "forward-complete": "Record prospective paper-test observations",
  practical: "Accept practical readiness",
};
export function ReadinessReviewPanel({ runId, controller }: { runId: string; controller: WorkbenchController }) {
  const status = useStrategyStages().statuses.byRun.get(runId);
  const phase: ReadinessPhase | undefined = status?.kind === "evaluation-passed" ? "robustness"
    : status?.kind === "robustness-validated" || status?.stage === 3 && status.kind === "failed-checks" ? "forward-plan"
    : status?.kind === "forward-testing" ? "forward-complete" : status?.kind === "forward-tested" ? "practical" : undefined;
  const [reviewer, setReviewer] = useState("");
  const [references, setReferences] = useState<Record<string, string>>({});
  const [start, setStart] = useState(new Date(Date.now() + 86400000).toISOString().slice(0, 10));
  const [end, setEnd] = useState("");
  const [minDays, setMinDays] = useState<number | string>(30);
  const [minTrades, setMinTrades] = useState<number | string>(30);
  const [minReturn, setMinReturn] = useState<number | string>(0);
  const [maxDrawdown, setMaxDrawdown] = useState<number | string>(10);
  const [trades, setTrades] = useState<number | string>("");
  const [netReturn, setNetReturn] = useState<number | string>("");
  const [observedDrawdown, setObservedDrawdown] = useState<number | string>("");
  if (!status || status.kind === "benchmark") return null;
  const latest = status.readiness;
  const seed = controller.state?.runs.find(run => run.id === runId);
  const configuration = seed && runConfigurationKey(seed);
  const matchingRuns = controller.state?.runs.filter(run => !run.input.portfolio_replay && run.input.strategy.id === seed?.input.strategy.id && runConfigurationKey(run) === configuration) || [];
  const snapshot = readinessEvidenceSnapshot(matchingRuns, controller.state?.evaluations || []);
  const history = matchingRuns.flatMap(run => run.readiness_reviews || []).filter(validReadinessReview).sort((a, b) => b.recordedAt.localeCompare(a.recordedAt));
  const numbers = phase === "forward-plan" ? [minDays, minTrades, minReturn, maxDrawdown]
    : phase === "forward-complete" ? [trades, netReturn, observedDrawdown] : [];
  const complete = phase && reviewer.trim() && readinessChecks[phase].every(check => (references[check.id] || "").trim().length >= 8)
    && numbers.every(n => n !== "" && Number.isFinite(Number(n))) && (phase !== "forward-plan" || start) && (phase !== "forward-complete" || end);
  const save = () => void controller.action(async () => {
    await request(`/runs/${runId}/readiness`, { phase, reviewer, references,
      ...(phase === "forward-plan" ? { plan: { start, minDays: Number(minDays), minTrades: Number(minTrades), minReturn: Number(minReturn) / 100, maxDrawdown: Number(maxDrawdown) / 100 } } : {}),
      ...(phase === "forward-complete" ? { observation: { end, trades: Number(trades), netReturn: Number(netReturn) / 100, maxDrawdown: Number(observedDrawdown) / 100 } } : {}),
    });
    const run = controller.state?.runs.find(candidate => candidate.id === runId);
    if (run) await controller.inspect(run);
    setReferences({});
    controller.setNotice("Development evidence recorded. The shared stage has been updated for this configuration.");
  });
  return <section className="wb-readiness-panel" aria-label="Strategy development evidence">
    <Text fw={700}>Development and practical readiness</Text>
    <ResearchStages stage={status.stage} />
    {seed && <Text size="xs" c="dimmed">{seed.input.dataset.symbol} · {seed.input.timeframe} · {seed.input.session} · parameters {JSON.stringify(seed.input.parameters)} · capital {seed.input.capital} · fee {seed.input.fee} per side · slippage {seed.input.slippage} ticks</Text>}
    <Text size="sm">{status.finding}</Text>
    {controller.error && <Alert color="red" title="Stage evidence could not be saved">{controller.error}</Alert>}
    {latest && <details><summary>Recorded stage evidence · {latest.reviewer} · {latest.recordedAt.slice(0, 10)}</summary>
      <Text size="xs">Review: {latest.phase} · baseline {latest.runId}</Text>
      {Object.entries(latest.references).map(([key, evidence]) => <Text size="xs" key={key} mt={5}><strong>{key}:</strong> {evidence}</Text>)}
      {latest.plan && <Text size="xs" mt={5}>Prospective start {latest.plan.start} · at least {latest.plan.minDays} days / {latest.plan.minTrades} trades · minimum return {(latest.plan.minReturn * 100).toFixed(2)}% · maximum drawdown {(latest.plan.maxDrawdown * 100).toFixed(2)}%</Text>}
      {latest.observation && <Text size="xs" mt={5}>Observed through {latest.observation.end} · {latest.observation.trades} paper trades · return {(latest.observation.netReturn * 100).toFixed(2)}% · drawdown {(latest.observation.maxDrawdown * 100).toFixed(2)}%</Text>}
    </details>}
    {history.length > 0 && <details><summary>Stage review history ({history.length})</summary>{history.map(review => {
      const parent = history.find(r => r.id === review.parentId);
      const failures = review.observation && parent?.plan ? forwardFailures(parent.plan, review.observation) : [];
      return <div key={review.id} style={{ borderTop: "1px solid #dce5de", padding: "8px 0" }}>
        <Text size="xs" fw={600}>{review.phase} · {review.reviewer} · {review.recordedAt.slice(0, 10)}</Text>
        {review.evidenceSnapshot !== snapshot && <Text size="xs" c="orange">Earlier evidence snapshot; current evidence needs another review.</Text>}
        {review.plan && <Text size="xs">Frozen start {review.plan.start} · minimum {review.plan.minDays} days / {review.plan.minTrades} trades · minimum return {review.plan.minReturn * 100}% · maximum drawdown {review.plan.maxDrawdown * 100}%</Text>}
        {review.observation && <Text size="xs" c={failures.length ? "red" : undefined}>Observed through {review.observation.end} · {review.observation.trades} paper trades · return {review.observation.netReturn * 100}% · drawdown {review.observation.maxDrawdown * 100}%</Text>}
        {failures.map(failure => <Text key={failure} size="xs" c="red">{failure}</Text>)}
        {Object.entries(review.references).map(([key, reference]) => <Text key={key} size="xs">{key}: {reference}</Text>)}
      </div>;
    })}</details>}
    {phase ? <details open key={phase} className="wb-readiness-form"><summary>{phaseTitles[phase]}</summary><Stack gap="sm" mt="sm">
      <Text size="xs" c="dimmed">Record a named review with report/log references and the measured findings. These are reviewed external records; the app does not execute a paper account. Historical replays do not establish prospective paper performance.</Text>
      <TextInput label="Reviewed by" value={reviewer} onChange={event => setReviewer(event.currentTarget.value)} required />
      {phase === "forward-plan" && <>
        <Text size="xs">The start must be after today and every inspected historical window. Criteria are frozen with this record.</Text>
        <TextInput label="Prospective start date (YYYY-MM-DD)" value={start} onChange={event => setStart(event.currentTarget.value)} required />
        <SimpleGrid cols={2}>
          <NumberInput label="Minimum observed calendar days" value={minDays} onChange={setMinDays} min={1} allowDecimal={false} />
          <NumberInput label="Minimum paper trades" value={minTrades} onChange={setMinTrades} min={1} allowDecimal={false} />
          <NumberInput label="Minimum net return (%)" value={minReturn} onChange={setMinReturn} />
          <NumberInput label="Maximum drawdown (%)" value={maxDrawdown} onChange={setMaxDrawdown} min={0.01} max={100} />
        </SimpleGrid>
      </>}
      {phase === "forward-complete" && <>
        <Text size="xs">Use observations from the frozen prospective window. Record failed results too; the stage reflects the frozen criteria.</Text>
        <TextInput label="Observed through date (YYYY-MM-DD)" value={end} onChange={event => setEnd(event.currentTarget.value)} required />
        <SimpleGrid cols={2}>
          <NumberInput label="Observed paper trades" value={trades} onChange={setTrades} min={0} allowDecimal={false} />
          <NumberInput label="Observed net return (%)" value={netReturn} onChange={setNetReturn} />
          <NumberInput label="Observed maximum drawdown (%)" value={observedDrawdown} onChange={setObservedDrawdown} min={0} max={100} />
        </SimpleGrid>
      </>}
      {readinessChecks[phase].map(check => <Textarea key={`${phase}-${check.id}`} label={check.label} description="Evidence location and reviewed findings (required)" minRows={2} required
        value={references[check.id] || ""} onChange={event => { const value = event.currentTarget.value; setReferences(current => ({ ...current, [check.id]: value })); }} />)}
      <Group><Button loading={controller.busy} disabled={!complete} onClick={save}>{phase === "forward-plan" ? "Freeze forward-testing plan" : phase === "practical" ? "Record practical readiness acceptance" : "Save stage evidence"}</Button></Group>
    </Stack></details> : status.stage < 2 && <Text size="xs" c="dimmed">Complete the historical evaluation before recording later-stage validation.</Text>}
  </section>;
}
