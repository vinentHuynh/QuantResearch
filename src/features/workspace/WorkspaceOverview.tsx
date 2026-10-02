import { useMemo, useState, type ReactNode } from "react";
import { Alert, Badge, Button, Group, Select, Text, TextInput } from "@mantine/core";
import { IconArchive, IconArchiveOff, IconSearch } from "@tabler/icons-react";
import type { RunSummary, Strategy } from "../../../shared/ts/workbenchModels.ts";
import { runConfigurationKey, testingEvidence } from "../../../shared/ts/evidence.ts";
import { readinessChecks } from "../../../shared/ts/readiness.ts";
import { researchStages } from "../../../shared/ts/progress.ts";
import { lifecycleStatus, type StrategyStageStatus } from "../../../shared/ts/strategyLifecycle.ts";
import { href } from "../../app/navigation";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import { PageHeader } from "../../shared/ui/PageHeader";
import { StrategyNextActionButton, StrategyStageBadge } from "../../shared/ui/StrategyStageBadge";
import { isInvalidRun } from "../runs/model";
import { isCurrentStrategyRun } from "../../../shared/ts/stageStatus.ts";
import { isConfigurationArchived } from "../../../shared/ts/researchArchive.ts";
import type { WorkbenchState } from "./workbenchModel";
import "./researchWorkspace.css";

const stageNames = ["", "Backtest", "Historical validation", "Robustness", "Forward test", "Practical readiness"];
const stageCriteria = ["", "Declared hypothesis, settings, and minimum traded result", "Frozen later-period baseline and stress criteria", "Parameter, coverage, execution, and risk evidence", "Frozen paper-test plan and reconciled observations", "Operating, risk, and monitoring checklist"];
type ResearchRow = { id: string; strategy: Strategy; config?: ReturnType<typeof testingEvidence>["configurations"][number]; status: StrategyStageStatus };

export function WorkspaceOverview({ state, onInspect, onCleanup, onArchiveConfiguration, busy, alerts }: {
  state: WorkbenchState;
  onInspect: (run: RunSummary) => void;
  onCleanup: (ids: string[]) => void;
  onArchiveConfiguration: (runId: string, archived: boolean) => void;
  busy: boolean;
  alerts?: ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState("");
  const [outcome, setOutcome] = useState("all");
  const [showArchive, setShowArchive] = useState(false);
  const rows = useMemo<ResearchRow[]>(() => state.strategies.flatMap<ResearchRow>(strategy => {
    const evidence = testingEvidence(strategy, state.runs, state.evaluations || []);
    if (!evidence.configurations.length) return [{ id: strategy.id, strategy, config: undefined, status: lifecycleStatus("not-tested", 0, "No backtest recorded.", [], { kind: "configure-run", label: "Configure backtest", strategyId: strategy.id }) }];
    return evidence.configurations.map(config => ({ id: `${strategy.id}:${config.key}`, strategy, config, status: config.lifecycle }));
  }).sort((a, b) => b.status.stage - a.status.stage || a.strategy.name.localeCompare(b.strategy.name)), [state]);
  const archivedRow = (row: ResearchRow) => !!row.config && isConfigurationArchived(row.strategy.id, row.config.key, state.research_archive);
  const archivedCount = rows.filter(archivedRow).length;
  const listed = rows.filter(row => archivedRow(row) === showArchive
    && `${row.strategy.name} ${row.config?.symbol || ""} ${row.config?.timeframe || ""}`.toLowerCase().includes(query.toLowerCase())
    && (outcome === "all" || (outcome === "failed" ? row.status.kind === "failed-checks" : outcome === "passed" ? row.status.stage >= 2 && row.status.kind !== "failed-checks" : row.status.stage < 2 && row.status.kind !== "failed-checks")));
  const selected = listed.find(row => row.id === selection) || listed[0];
  const attempts = selected?.config ? state.runs.filter(run => run.input.strategy.id === selected.strategy.id && isCurrentStrategyRun(run, selected.strategy) && runConfigurationKey(run) === selected.config?.key) : [];
  const seed = attempts.find(run => run.id === selected?.config?.runId) || attempts[0];
  const evaluations = (state.evaluations || []).filter(evaluation => evaluation.folds.some(fold => [...fold.training, ...fold.tests].some(id => attempts.some(run => run.id === id))));
  const invalidRuns = state.runs.filter(isInvalidRun);
  return <>
    <PageHeader crumb="Research" title="Research" actions={<Button component="a" href={href("new-run")} size="xs">New backtest</Button>}
      tabsLabel="Research views" tabs={[
        { label: "Active configurations", count: rows.length - archivedCount, active: !showArchive, onClick: () => { setShowArchive(false); setSelection(""); } },
        { label: "Archive", count: archivedCount, active: showArchive, onClick: () => { setShowArchive(true); setSelection(""); } },
      ]}
    />
    {alerts}
    <div className="wb-content wb-workspace">
      <nav className="research-tools" aria-label="Research tools"><a href={href("runs")}>Runs & compare</a><a href={href("evaluations")}>Evaluations</a><a href={href("scorecards")}>Scorecards</a><a href={href("event-studies")}>Pattern studies</a></nav>
      {showArchive && <Text size="sm" c="dimmed" mb="md">Archived configurations keep their runs, results, and evidence. Restore a configuration to show it and its matching runs in the active lists.</Text>}
      {invalidRuns.length > 0 && <Alert color="yellow" title={`${invalidRuns.length} run records need cleanup`}><Group justify="space-between"><Text size="sm">Their result manifests are invalid.</Text><Button size="xs" variant="light" onClick={() => onCleanup(invalidRuns.map(run => run.id))}>Review cleanup</Button></Group></Alert>}
      <div className="research-layout">
        <section className="research-list" aria-label="Research configurations">
          <div className="research-list-head"><h2>{showArchive ? "Archived configurations" : "Configurations"}</h2><Text size="xs" c="dimmed">{listed.length} shown</Text></div>
          <TextInput aria-label="Search research configurations" placeholder="Strategy or market" leftSection={<IconSearch size={15} />} value={query} onChange={event => setQuery(event.currentTarget.value)} />
          <Select aria-label="Filter research outcomes" value={outcome} onChange={value => setOutcome(value || "all")} data={[{ value: "all", label: "All outcomes" }, { value: "passed", label: "Validated" }, { value: "progress", label: "In progress" }, { value: "failed", label: "Failed checks" }]} />
          <div className="research-list-scroll">{listed.map(row => <button key={row.id} type="button" className={`research-list-item${selected?.id === row.id ? " active" : ""}`} onClick={() => setSelection(row.id)}>
            <strong>{strategyTitle(row.strategy.name)}</strong><span>{row.config ? `${row.config.symbol} · ${row.config.timeframe} · ${row.config.session}` : "No configuration yet"}</span><span className="research-list-stage">{row.status.failedStage ? `Failed at ${stageNames[row.status.failedStage]}` : row.status.blockedStage ? `Blocked at ${stageNames[row.status.blockedStage]}` : row.status.label}</span>
          </button>)}</div>
          {!listed.length && <Text size="sm" c="dimmed" p="sm">{showArchive && !archivedCount ? "No archived configurations yet." : "No configurations match."}</Text>}
        </section>
        {selected && <section className="research-detail" aria-label="Selected configuration">
          <Group justify="space-between" align="start"><div><h2>{strategyTitle(selected.strategy.name)}</h2><Text size="sm" c="dimmed">{selected.config ? `${selected.config.symbol} · ${selected.config.timeframe} · ${selected.config.session}` : "Backtest needed"}</Text></div><StrategyStageBadge {...selected.status} /></Group>
          {seed && <Group mt="sm" gap="xs">
            <Button size="xs" variant="default" leftSection={showArchive ? <IconArchiveOff size={14} /> : <IconArchive size={14} />}
              disabled={busy || (!showArchive && !!selected.config?.busy)}
              title={!showArchive && selected.config?.busy ? "Wait for this configuration's active work to finish before archiving." : undefined}
              onClick={() => onArchiveConfiguration(seed.id, !showArchive)}>
              {showArchive ? "Restore configuration" : "Archive configuration"}
            </Button>
            <Text size="xs" c="dimmed">{showArchive ? "Results and evidence are preserved." : "Includes all matching runs; results and evidence are kept."}</Text>
          </Group>}
          <Text size="sm" mt="sm">{selected.status.finding}</Text>
          {!showArchive && selected.status.action && <StrategyNextActionButton action={selected.status.action} />}
          <div className="research-steps">{researchStages.map(stage => <StageRow key={stage.stage} number={stage.stage} status={selected.status} seed={seed} evaluations={evaluations} />)}</div>
          <details className="research-evidence"><summary>Attempts and evidence ({attempts.length})</summary>
            {selected.config && <Text size="xs" mt="xs">Parameters: {JSON.stringify(selected.config.parameters)}</Text>}
            {attempts.map(run => <div className="research-attempt" key={run.id}><Text size="xs">{run.created_at.slice(0, 10)} · {run.status} · {run.input.start} to {run.input.end} · {run.result?.metrics.trades ?? "—"} trades</Text><Button size="compact-xs" variant="subtle" onClick={() => onInspect(run)}>Inspect {run.id.slice(0, 8)}</Button></div>)}
            {evaluations.map(evaluation => <div className="research-attempt" key={evaluation.id}><Text size="xs">{evaluation.name} · {evaluation.outcome || evaluation.status}</Text><Button component="a" href={href("evaluations")} size="compact-xs" variant="subtle">Open evaluation</Button></div>)}
            {attempts.flatMap(run => run.stage_assessments || []).map(assessment => <Text key={assessment.id} size="xs">{assessment.recordedAt.slice(0, 10)} · {stageNames[assessment.attemptedStage]} {assessment.outcome}: {assessment.findings}</Text>)}
          </details>
        </section>}
      </div>
    </div>
  </>;
}

function StageRow({ number, status, seed, evaluations }: { number: 1 | 2 | 3 | 4 | 5; status: StrategyStageStatus; seed?: RunSummary; evaluations: WorkbenchState["evaluations"] }) {
  const failed = status.failedStage === number || status.kind === "failed-checks" && !status.failedStage && number === Math.min(5, status.stage + 1);
  const blocked = status.blockedStage === number;
  const complete = status.stage >= number && !failed && !(number === 4 && status.kind === "forward-testing");
  const waiting = !failed && !complete && (blocked || number === 4 && status.kind === "forward-testing" || number === 5 && status.kind === "forward-tested");
  const label = failed ? "Failed" : complete ? "Complete" : waiting ? "Waiting for evidence" : number === status.stage + 1 ? "Next" : "Locked";
  const criteria = number === 1 ? seed?.input.criteria || stageCriteria[number]
    : number === 2 ? evaluations?.map(e => `${e.name}: return ≥ ${((e.min_return || 0) * 100).toFixed(1)}%, drawdown ≤ ${((e.max_drawdown || 0) * 100).toFixed(1)}%, trades ≥ ${e.min_test_trades ?? "declared minimum"}`).join("; ") || stageCriteria[number]
    : number === 3 ? readinessChecks.robustness.map(c => c.label).join("; ")
    : number === 4 ? seed?.readiness_reviews?.find(review => review.phase === "forward-plan")?.plan ? "Frozen paper-test criteria on the run record" : stageCriteria[number]
    : readinessChecks.practical.map(c => c.label).join("; ");
  return <div className={`research-step ${failed ? "failed" : complete ? "complete" : ""}`}>
    <div className="research-step-title"><strong>{number}. {stageNames[number]}</strong><Badge size="xs" color={failed ? "red" : complete ? "teal" : waiting ? "blue" : "gray"}>{label}</Badge></div>
    {(failed || blocked || number === status.stage + 1) && <Text size="xs" mt={4}>{failed || blocked ? status.finding : researchStages[number - 1].description}</Text>}
    <details><summary>Criteria and evidence</summary><Text size="xs">{criteria}</Text>{failed && status.checks.map((check, index) => <Text size="xs" c="red" key={index}>{check}</Text>)}{number === 1 && seed && <Text size="xs">Run {seed.id}</Text>}{number === 2 && evaluations?.map(e => <Text size="xs" key={e.id}>{e.id} · {e.outcome || e.status}</Text>)}</details>
  </div>;
}
