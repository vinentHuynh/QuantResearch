import { Badge, Button, Group, Progress, Text, Tooltip } from "@mantine/core";
import { useState } from "react";
import { viabilityExplanation, type TestingEvidence } from "../../../shared/ts/evidence.ts";
import { progressScope } from "../../../shared/ts/progress.ts";
import { ResearchStages } from "./ResearchStages";
import { StrategyNextActionButton, StrategyStageBadge } from "../../shared/ui/StrategyStageBadge";
import { lifecycleStatus } from "../../../shared/ts/strategyLifecycle.ts";
import "./strategyTesting.css";

const cash = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const pct = (n: number) => `${(n * 100).toFixed(2)}%`;
export type TestingActions = { inspectRun: (id: string) => void; openEvaluation: (id: string) => void };

export function StrategyTesting({ evidence: e, compact = false, runnableCard = false, inspectRun, openEvaluation }: TestingActions & { evidence: TestingEvidence; compact?: boolean; runnableCard?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const best = e.best;
  const configuration = best && e.configurations.find(c => c.runId === best.run.id);
  const status = configuration?.lifecycle || e.configurations[0]?.lifecycle || lifecycleStatus(e.previousSource && !e.total ? "retest-required" : "not-tested", 0,
    e.previousSource ? "Current source needs retesting." : "Complete a backtest, then plan its evaluation.", ["Backtest the current source, then complete its declared evaluation."],
    { kind: "configure-run", label: "Configure current-source backtest", strategyId: e.strategyId });
  const bestMetrics = best?.run.result?.metrics;
  if (runnableCard) return <section className="strategy-testing-runnable" aria-label="Promising configuration">
    <div className="strategy-testing-runnable-status">
      <StrategyStageBadge {...status} />
    </div>
    {best && bestMetrics ? <div className="strategy-testing-best-run" aria-label="Best run summary" data-tier={best.tier}>
      <Text className="strategy-testing-best-run-heading" size="xs" fw={600}>
        Best run · <strong>{best.run.input.dataset.symbol} · {best.run.input.timeframe}</strong>
      </Text>
      <div className="strategy-testing-best-run-metrics">
        <div className="strategy-testing-best-run-metric"><strong>{cash(bestMetrics.net_pnl)}</strong><span>Net P&amp;L</span></div>
        <div className="strategy-testing-best-run-metric"><strong>{pct(Math.abs(bestMetrics.max_drawdown))}</strong><span>Drawdown</span></div>
        <div className="strategy-testing-best-run-metric"><strong>{bestMetrics.trades}</strong><span>Trades</span></div>
        <div className="strategy-testing-best-run-metric"><strong>{best.score?.toFixed(2) ?? "Unranked"}</strong><span>Return/DD</span></div>
      </div>
    </div> : <Text size="xs" c="dimmed" mt={6}>
      {e.previousSource && !e.total ? "Current source needs retesting." : "No positive traded run for this market and source."}
    </Text>}
  </section>;
  return <section className={`strategy-testing testing-summary ${compact ? "strategy-testing-compact" : ""}`} aria-label="Promising configuration">
    <Group justify="space-between" gap="xs">
      <Text size="sm" fw={600}>{best ? `${best.run.input.dataset.symbol} · ${best.run.input.timeframe}` : "No promising result yet"}</Text>
      <StrategyStageBadge {...status} showFinding showAction />
    </Group>
    <Text size="xs" c={best?.tier === 0 ? "orange" : "dimmed"} mt={5}>
      {best ? `${best.tier >= 2 ? "Promising candidate" : best.tier === 1 ? "Early candidate" : "Checks unresolved"} · Return/DD ${best.score?.toFixed(2) ?? "unranked"}`
        : e.previousSource && !e.total ? "Current source needs retesting." : "No positive traded result for this market and source."}
    </Text>
    {best && <Button size="compact-xs" variant="subtle" mt={5} onClick={() => inspectRun(best.run.id)}>Inspect best run</Button>}
    <details onToggle={event => setExpanded(event.currentTarget.open)}>
      <summary>Testing details</summary>
      {expanded && <DetailedTesting evidence={e} compact={compact} inspectRun={inspectRun} openEvaluation={openEvaluation} />}
    </details>
  </section>;
}

function DetailedTesting({ evidence: e, compact = false, inspectRun, openEvaluation }: TestingActions & { evidence: TestingEvidence; compact?: boolean }) {
  const best = e.best;
  const m = best?.run.result?.metrics;
  return <section className={`strategy-testing ${compact ? "strategy-testing-compact" : ""}`} aria-label="Strategy testing evidence">
    <Group justify="space-between" gap="xs">
      <Text size="sm" fw={600}>Testing progress</Text>
      <Text size="xs" c="dimmed">Current-source configuration stages below</Text>
    </Group>
    <Text size="xs" c="dimmed" mt={5}>{e.scope} · Current source · Highest recorded milestone</Text>
    <ResearchStages stage={e.stage} />
    <Text size="xs">{e.passingConfigurations} of {e.configurations.length} configurations passed evaluation · {e.failingConfigurations} with unmet criteria</Text>
    <div className="testing-markets">
      {[...new Set(e.configurations.map(c => c.symbol))].map(symbol => {
        const configs = e.configurations.filter(c => c.symbol === symbol);
        return <div key={symbol}><strong>{symbol}</strong><span>{configs.filter(c => c.stage >= 2).length}/{configs.length} evaluated & passed</span>
          {configs.some(c => c.failed) && <span className="testing-market-finding">{configs.filter(c => c.failed).length} with unmet criteria</span>}</div>;
      })}
    </div>
    {e.configurations.length > 0 && <details className="testing-configurations">
      <summary>Results and next steps by configuration ({e.configurations.length})</summary>
      <Text size="xs" c="dimmed">{progressScope}</Text>
      <div className="testing-configuration-list">{e.configurations.map(c => <div key={c.key} className="testing-configuration">
        <Group justify="space-between" gap={5}><Text size="xs" fw={600}>{c.symbol} · {c.timeframe} · {c.session}</Text><StrategyStageBadge {...c.lifecycle} /></Group>
        <Text size="xs" c={c.failed ? "orange" : "dimmed"}>{c.outcome}{c.busy ? " · Testing in progress" : ""} · {c.completed}/{c.total} runs succeeded</Text>
        <Text size="xs" c="dimmed">Source {c.sourceHash.slice(0, 10)}</Text>
        <Text size="xs" className="testing-parameters">{Object.entries(c.parameters).map(([k,v]) => `${k}: ${String(v)}`).join(" · ") || "Default parameters"}</Text>
        <Text size="xs"><strong>Next:</strong> {c.next}</Text>
        {c.lifecycle.checks.map((check, index) => <Text size="xs" key={index}>{check}</Text>)}
        {c.lifecycle.action && <StrategyNextActionButton action={c.lifecycle.action} />}
        <Button size="compact-xs" variant="subtle" onClick={() => inspectRun(c.runId)}>Inspect configuration run</Button>
      </div>)}</div>
    </details>}
    <Text size="xs" c="dimmed" mt="xs">{e.succeeded} succeeded · {e.running} running · {e.queued} queued · {e.summarizing} summarizing · {e.executionFailed} execution failures</Text>
    {e.inProgress && <div className="testing-job-progress">
      <Badge color="blue" size="xs">Testing in progress</Badge>
      <Text size="xs">{e.progress.label}: {e.progress.done} / {e.progress.total}</Text>
      <Progress aria-label={e.progress.label} value={e.progress.total ? 100 * e.progress.done / e.progress.total : 0} animated size="sm" />
      <Text size="xs" c="dimmed">Finished includes failed or canceled jobs; this is not a pass percentage.</Text>
    </div>}
    {e.previousSource > 0 && <Text size="xs" c="orange">{e.previousSource} earlier-source attempts retained; current-source evidence shown here.{!e.total && " Retest the current source."}</Text>}
    <Text size="xs" mt="xs">Review: {e.review}. Review records findings; it does not pass tests.</Text>
    {e.savedReview && <div className="testing-review">
      <Text size="xs" fw={600}>{e.reviewComplete ? "Review completed for this view" : "Previous review"} · {e.savedReview.reviewedAt.slice(0, 10)}</Text>
      <Text size="xs" c="dimmed">Saved adapter-wide verdict; configuration results are listed separately above.</Text>
      <Text size="xs">{e.savedReview.verdict}</Text>
      <Text size="xs" mt={4}><strong>Next step:</strong> {e.savedReview.nextStep}</Text>
      {!e.reviewComplete && <Text size="xs" c="orange">New or changed evidence still needs review.</Text>}
      <Button size="compact-xs" variant="subtle" onClick={() => inspectRun(e.savedReview!.runId)}>Inspect saved review</Button>
    </div>}
    {e.issues.length > 0 && <div className="testing-issues">
      <Text size="xs" fw={600} c="orange">{e.issues.length} recorded issues · {e.reviewedIssues} reviewed · {e.issues.length - e.reviewedIssues} awaiting review</Text>
      <details>
        <summary>Failure reasons and evidence ({e.issues.length})</summary>
        <div className="testing-issue-list">
          {e.issues.map(issue => <div className="testing-issue" key={issue.id}>
            <Text size="xs" fw={600}>{issue.title}</Text>
            <Text size="xs" fw={600}>{issue.scope}</Text>
            <Text size="xs">{issue.reason}</Text>
            {issue.runId && <Button size="compact-xs" variant="subtle" onClick={() => inspectRun(issue.runId!)}>Inspect run {issue.runId.slice(0, 8)}</Button>}
            {issue.evaluationId && <Button size="compact-xs" variant="subtle" onClick={() => openEvaluation(issue.evaluationId!)}>Open evaluation {issue.evaluationId.slice(0, 8)}</Button>}
          </div>)}
        </div>
      </details>
    </div>}
    <div className="testing-best">
      <Group gap="xs" justify="space-between">
        <Tooltip label={viabilityExplanation} multiline w={350} withArrow><Text size="sm" fw={600}>Most viable recorded run</Text></Tooltip>
        {best && <Badge color={best.tier === 0 ? "red" : best.tier >= 2 ? "teal" : "gray"} size="xs">{best.run.input.dataset.symbol} · {best.run.input.timeframe}</Badge>}
      </Group>
      {best && m ? <>
        <Text size="xs" c={best.tier === 0 ? "red" : "dimmed"}>{best.label}</Text>
        <Text size="sm" fw={600}>{cash(m.net_pnl)} net · {pct(Math.abs(m.max_drawdown))} DD · {m.trades} trades</Text>
        <Text size="xs" c="dimmed">{best.run.input.start} to {best.run.input.end} · Return/DD {best.score?.toFixed(2) ?? "unranked (zero DD)"}</Text>
        <details>
          <summary>Ranking and run settings</summary>
          <Text size="xs">{viabilityExplanation}</Text>
          <Text size="xs" mt="xs">Capital {cash(best.run.input.capital)} · Fee {cash(best.run.input.fee)} per side · Slippage {best.run.input.slippage} ticks · {best.run.input.session}</Text>
          <Text size="xs" className="testing-parameters">{Object.entries(best.run.input.parameters).map(([k, v]) => `${k}: ${String(v)}`).join(" · ")}</Text>
        </details>
        <Button mt="xs" size="compact-xs" variant="light" onClick={() => inspectRun(best.run.id)}>Inspect most viable run</Button>
      </> : <Text size="xs" c="dimmed">No completed, positive, traded run for this source and market. Training-only and older-source results are excluded.</Text>}
    </div>
    {!compact && <Text size="xs" c="dimmed" mt="xs">Individual case passes do not complete evaluation. Robustness requires additional recorded checks. All milestones describe historical research.</Text>}
  </section>;
}
