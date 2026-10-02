import type { EvaluationView, RunSummary } from "./workbenchModels.ts";
import { readTestingReviews, reviewIssueKey } from "./testingReview.ts";
import { stageLabel, stageColor, type ResearchStage } from "./progress.ts";
import { lifecycleStatus } from "./strategyLifecycle.ts";
import { applyReadiness } from "./readiness.ts";
import { applyStageAssessments } from "./stageAssessments.ts";

export type TestingIssue = { id: string; title: string; reason: string; runId?: string; evaluationId?: string; scope?: string };
export type TestingEvidence = ReturnType<typeof testingEvidence>;
export function comparePromising(a?: TestingEvidence, b?: TestingEvidence) {
  const left = a?.best, right = b?.best;
  return (right?.tier ?? -1) - (left?.tier ?? -1)
    || (right?.score ?? -Infinity) - (left?.score ?? -Infinity)
    || (right?.run.result?.metrics.trades ?? 0) - (left?.run.result?.metrics.trades ?? 0);
}
const active = (status: string) => ["Queued", "Running", "Summarizing"].includes(status);
const tags = (r: RunSummary) => (r.tags || "").toLowerCase().split(/[,\s]+/);
const flagged = (r: RunSummary) => tags(r).includes("checks-failed");
const percent = (n: number) => `${(n * 100).toFixed(2)}%`;
const newest = (a: { created_at: string }, b: { created_at: string }) => b.created_at.localeCompare(a.created_at);
const v2ExecutionHash = (r: RunSummary) => r.input.execution_source_hash || r.input.source_hash || r.input.strategy.execution_source_hash || r.input.strategy.file_hash;
const strategyExecutionHash = (strategy: { file_hash: string; execution_source_hash?: string }) => strategy.execution_source_hash || strategy.file_hash;
const currentRun = (r: RunSummary, strategy: { file_hash: string; execution_source_hash?: string }) => r.input.protocol === 2
  ? v2ExecutionHash(r) === strategyExecutionHash(strategy)
  : r.input.strategy.file_hash === strategy.file_hash;
// Protocol v1 historically grouped configurations by source_hash but decided
// current-source eligibility by adapter hash. Preserve both behaviors exactly.
const configurationSourceHash = (r: RunSummary) => r.input.protocol === 2
  ? v2ExecutionHash(r)
  : r.input.source_hash || r.input.strategy.file_hash;
export const runConfigurationKey = (r: RunSummary) => JSON.stringify([configurationSourceHash(r), r.input.dataset.symbol, r.input.timeframe, r.input.session,
  Object.entries(r.input.parameters).sort(([a], [b]) => a.localeCompare(b))]);
const configuration = runConfigurationKey;
export const viabilityExplanation = "Current execution source and positive traded runs only. Passing evaluation baselines rank first, then recorded passing cases, then exploratory runs, then failed-check candidates. Failures follow matching parameters, market, timeframe and session across dates and costs. Within each group: net return / maximum drawdown, then trade count and recency. Zero-drawdown samples rank last within their group. Dates, markets and assumptions can differ; this is a research comparison, not a status promotion.";

export function testingEvidence(
  strategy: { id: string; file_hash: string; execution_source_hash?: string },
  allRuns: RunSummary[],
  allEvaluations: EvaluationView[],
  symbol = "",
) {
  const history = allRuns.filter(r => r.input.strategy.id === strategy.id && !r.input.portfolio_replay && (!symbol || r.input.dataset.symbol === symbol));
  const runs = history.filter(r => currentRun(r, strategy)).sort(newest);
  const runIds = new Set(runs.map(r => r.id));
  const byId = new Map(allRuns.map(r => [r.id, r]));
  const evaluations = allEvaluations.filter(e => e.folds.some(f => [...f.training, ...f.tests].some(id => runIds.has(id)))).sort(newest);
  const evaluationFacts = evaluations.map(e => {
    const scenarios = e.result?.scenarios || [];
    const required = e.scenarios || ["Baseline", "Higher costs", "Delayed execution"];
    const children = e.folds.flatMap(f => [...f.training, ...f.tests]);
    const complete = children.length > 0 && children.every(id => byId.get(id)?.status === "Succeeded" && runIds.has(id));
    const pass = e.status === "Succeeded" && complete && required.length > 0 && required.every(name => scenarios.some(s => s.name === name && s.outcome === "Meets criteria" && s.metrics.net_pnl > 0));
    const bad = scenarios.filter(s => s.outcome !== "Meets criteria" || s.metrics.net_pnl <= 0);
    return { evaluation: e, children, pass, bad };
  });
  // A completed, passing replay may supersede an older execution interruption
  // for the same source and settings. It does not erase the older record or any
  // scenario that actually breached an economic criterion.
  const latestPassByConfiguration = new Map<string, string>();
  for (const { evaluation, pass } of evaluationFacts) {
    if (!pass) continue;
    for (const id of evaluation.folds.flatMap(f => f.tests)) {
      const run = byId.get(id);
      if (!run || !runIds.has(id)) continue;
      const key = configuration(run);
      const previous = latestPassByConfiguration.get(key);
      if (!previous || evaluation.created_at > previous) latestPassByConfiguration.set(key, evaluation.created_at);
    }
  }
  const supersededTechnicalEvaluationKeys = new Map<string, Set<string>>();
  const supersededTechnicalRunIds = new Set<string>();
  for (const { evaluation, children, bad } of evaluationFacts) {
    if (active(evaluation.status) || evaluation.status === "Succeeded" || bad.length) continue;
    const childRuns = children.map(id => byId.get(id)).filter((run): run is RunSummary => !!run && runIds.has(run.id));
    if (!childRuns.some(run => !active(run.status) && run.status !== "Succeeded")) continue;
    const keys = new Set(childRuns.map(configuration).filter(key => (latestPassByConfiguration.get(key) || "") > evaluation.created_at));
    if (!keys.size) continue;
    supersededTechnicalEvaluationKeys.set(evaluation.id, keys);
    for (const run of childRuns) {
      if (keys.has(configuration(run)) && !active(run.status) && run.status !== "Succeeded"
        && (latestPassByConfiguration.get(configuration(run)) || "") > run.created_at)
        supersededTechnicalRunIds.add(run.id);
    }
  }
  const issues: TestingIssue[] = [];
  const evaluatedPass = new Set<string>();
  const evaluatedFail = new Set<string>();
  const incompleteTests = new Set<string>();
  for (const { evaluation: e, pass, bad } of evaluationFacts) {
    if (pass) {
      e.folds.flatMap(f => f.tests).forEach(id => evaluatedPass.add(id));
    } else if (!active(e.status)) {
      e.folds.flatMap(f => f.tests).forEach(id => {
        if (bad.length) evaluatedFail.add(id);
        else {
          const run = byId.get(id);
          if (!run || !supersededTechnicalEvaluationKeys.get(e.id)?.has(configuration(run))) incompleteTests.add(id);
        }
      });
      for (const s of bad) {
        const reasons: string[] = [];
        if (e.max_drawdown != null && Math.abs(s.metrics.max_drawdown) > e.max_drawdown)
          reasons.push(`Drawdown ${percent(Math.abs(s.metrics.max_drawdown))} exceeds ${percent(e.max_drawdown)} limit`);
        if (e.min_return != null && s.metrics.net_return < e.min_return)
          reasons.push(`Return ${percent(s.metrics.net_return)} is below ${percent(e.min_return)} required`);
        if (e.min_test_trades != null && s.metrics.trades < e.min_test_trades)
          reasons.push(`${s.metrics.trades} trades; ${e.min_test_trades} required`);
        if (s.metrics.net_pnl <= 0) reasons.push("Net profit is not positive");
        issues.push({ id: `${e.id}-${s.name}`, title: `${s.name}: ${s.outcome}`, reason: reasons.join(". ") || "Recorded evaluation criterion was not met.", evaluationId: e.id });
      }
      if (!bad.length) issues.push({ id: e.id, title: `Evaluation ${e.status === "Succeeded" ? "incomplete" : e.status.toLowerCase()}`, reason: e.error || "A complete set of passing declared scenarios and current-source child runs is unavailable.", evaluationId: e.id });
    }
  }
  for (const r of runs) {
    if (!active(r.status) && r.status !== "Succeeded")
      issues.push({ id: r.id, title: `Run ${r.status.toLowerCase()}`, reason: r.error || `Execution ${r.status.toLowerCase()}; no completed result was produced.`, runId: r.id });
    else if (flagged(r)) {
      const m = r.result?.metrics;
      issues.push({ id: r.id, title: "Recorded checks failed", reason: `${m ? `Drawdown ${percent(Math.abs(m.max_drawdown))}; net P&L $${m.net_pnl.toLocaleString()}; ${m.trades ?? "unknown"} trades. ` : ""}${r.input.criteria ? `Recorded criteria: ${r.input.criteria}` : r.notes || "This run carries a checks-failed review flag; inspect its saved notes."}`, runId: r.id });
    } else if (r.status === "Succeeded" && r.result?.metrics.trades === 0)
      issues.push({ id: r.id, title: "No trades", reason: "Execution succeeded, but a zero-trade result provides no trading-performance evidence.", runId: r.id });
  }
  const successful = runs.filter(r => r.status === "Succeeded");
  const queued = runs.filter(r => r.status === "Queued").length;
  const running = runs.filter(r => r.status === "Running").length;
  const summarizing = runs.filter(r => r.status === "Summarizing").length;
  const terminal = runs.filter(r => !active(r.status)).length;
  const currentEvaluation = evaluations.find(e => active(e.status));
  const evaluationIds = currentEvaluation?.folds.flatMap(f => [...f.training, ...f.tests]) || [];
  const progress = currentEvaluation
    ? { label: "Evaluation jobs finished", done: evaluationIds.filter(id => { const r = byId.get(id); return r && !active(r.status); }).length, total: Math.max(currentEvaluation.jobs, evaluationIds.length) }
    : { label: "Recorded runs finished", done: terminal, total: runs.length };
  const failedConfigurations = new Set(runs.filter(r => flagged(r) || evaluatedFail.has(r.id)).map(configuration));
  const incompleteConfigurations = new Set(runs.filter(r => incompleteTests.has(r.id)).map(configuration));
  const candidates = successful.filter(r => {
    const m = r.result?.metrics;
    return m && Number.isFinite(m.net_pnl) && m.net_pnl > 0 && Number.isFinite(m.net_return) && m.net_return > 0 && Number.isFinite(m.max_drawdown) && (m.trades ?? 0) > 0 && r.input.research?.role !== "Training";
  }).map(run => {
    const failed = failedConfigurations.has(configuration(run));
    const incomplete = incompleteConfigurations.has(configuration(run));
    const isBaseline = run.input.research?.scenario === "Baseline";
    const tier = failed || incomplete ? 0 : evaluatedPass.has(run.id) && isBaseline ? 3 : tags(run).includes("case-passed") ? 2 : 1;
    const m = run.result!.metrics;
    const score = Math.abs(m.max_drawdown) > 0 ? m.net_return / Math.abs(m.max_drawdown) : null;
    return { run, tier, score, label: incomplete && !failed ? "Matching evaluation incomplete — validation pending" : ["Matching checks failed — research lead only", "Exploratory — validation pending", "Individual case passed — full validation pending", "Baseline from a passing evaluation"][tier] };
  }).sort((a, b) => b.tier - a.tier || (b.score ?? -Infinity) - (a.score ?? -Infinity) || (b.run.result!.metrics.trades ?? 0) - (a.run.result!.metrics.trades ?? 0) || newest(a.run, b.run));
  const inProgress = !!currentEvaluation || queued + running + summarizing > 0;
  const groups = new Map<string, RunSummary[]>();
  for (const run of runs) {
    const key = configuration(run);
    groups.set(key, [...(groups.get(key) || []), run]);
  }
  const configurations = [...groups].map(([key, attempts]) => {
    const sample = attempts[0];
    const completed = attempts.filter(r => r.status === "Succeeded");
    const failed = failedConfigurations.has(key);
    const incomplete = incompleteConfigurations.has(key);
    const passed = !failed && !incomplete && attempts.some(r => evaluatedPass.has(r.id) && r.input.research?.scenario === "Baseline");
    let stage: ResearchStage = passed ? 2 : completed.length ? 1 : 0;
    const matchingEvaluations = evaluations.filter(e => e.folds.some(f => [...f.training, ...f.tests].some(id => attempts.some(r => r.id === id))));
    const activeEvaluation = matchingEvaluations.find(e => active(e.status));
    const busy = !!activeEvaluation || attempts.some(r => active(r.status));
    const executionIssues = attempts.filter(r => !active(r.status) && r.status !== "Succeeded" && !supersededTechnicalRunIds.has(r.id)).length;
    const noTrades = completed.length > 0 && completed.every(r => !r.result?.metrics.trades);
    const outcome = failed ? "Criteria not met" : incomplete ? "Evaluation incomplete" : noTrades ? "No trades" : executionIssues ? "Execution issues recorded" : activeEvaluation ? "Evaluation in progress" : passed ? "Declared checks passed" : "Validation pending";
    const runId = (candidates.find(c => configuration(c.run) === key)?.run || completed.find(r => r.input.research?.role !== "Training") || sample).id;
    const evaluationId = (activeEvaluation || matchingEvaluations[0])?.id;
    const relevantIssues = issues.filter(issue =>
      issue.runId ? attempts.some(r => r.id === issue.runId) && !supersededTechnicalRunIds.has(issue.runId)
        : matchingEvaluations.some(e => e.id === issue.evaluationId) && !supersededTechnicalEvaluationKeys.get(issue.evaluationId || "")?.has(key));
    const kind = strategy.id === "buy-hold" ? "benchmark" : failed ? "failed-checks" : noTrades || executionIssues ? "needs-review" : activeEvaluation ? "evaluation-running" : busy ? "backtest-running" : passed ? "evaluation-passed" : completed.length ? "validation-pending" : "not-tested";
    const checks = relevantIssues.length ? relevantIssues.map(issue => `${issue.title}: ${issue.reason}`)
      : passed ? [] : completed.length ? ["Complete a declared later-period evaluation with every required baseline and stress scenario."] : ["Complete a backtest with valid results."];
    const historicalLifecycle = lifecycleStatus(kind, stage, busy ? `${outcome} · Testing in progress` : outcome, checks,
      strategy.id === "buy-hold" ? undefined : passed && !activeEvaluation ? { kind: "open-portfolio", label: "Open portfolio · refresh histories to import this result" }
      : evaluationId ? { kind: "open-evaluation", label: busy ? "View evaluation progress" : failed ? "Review failed checks" : "Complete evaluation", evaluationId }
      : noTrades || executionIssues || failed || busy ? { kind: "inspect-run", label: "Inspect run & findings", runId }
      : completed.length ? { kind: "plan-evaluation", label: "Plan evaluation", runId }
      : { kind: "configure-run", label: "Configure backtest", runId, strategyId: strategy.id });
    if (failed) historicalLifecycle.failedStage = 2;
    const readinessLifecycle = applyReadiness(historicalLifecycle, attempts, evaluations, key, runId);
    const lifecycle = applyStageAssessments(readinessLifecycle, sample, attempts, evaluations);
    stage = lifecycle.stage;
    return { key, sourceHash: configurationSourceHash(sample), symbol: sample.input.dataset.symbol, timeframe: sample.input.timeframe, session: sample.input.session,
      parameters: sample.input.parameters, stage, outcome, busy, executionIssues, failed,
      total: attempts.length, completed: completed.length,
      next: failed ? "Inspect matching failures and revise or retest this configuration."
        : activeEvaluation ? "Follow the evaluation progress, then review every declared scenario."
        : passed ? lifecycle.action?.label || "Review the next development stage."
        : noTrades ? "Check signal activity and data coverage before evaluating."
        : executionIssues ? "Inspect execution errors and rerun the affected attempts."
        : completed.length ? "Run a later-period baseline with declared stress checks." : "Complete a backtest.",
      runId, evaluationId, lifecycle,
    };
  }).sort((a, b) => b.stage - a.stage || a.symbol.localeCompare(b.symbol) || a.key.localeCompare(b.key));
  const stage = configurations.reduce<ResearchStage>((highest, c) => Math.max(highest, c.stage) as ResearchStage, 0);
  const passingConfigurations = configurations.filter(c => c.stage >= 2).length;
  const failingConfigurations = configurations.filter(c => c.failed).length;
  for (const issue of issues) {
    const related = issue.runId ? runs.filter(r => r.id === issue.runId)
      : runs.filter(r => evaluations.find(e => e.id === issue.evaluationId)?.folds.some(f => f.tests.includes(r.id)));
    issue.scope = [...new Set(related.map(r => `${r.input.dataset.symbol} · ${r.input.timeframe || "unspecified timeframe"} · ${r.input.session || "unspecified session"}`))].join("; ");
  }
  // Reviews cover an explicit snapshot. Search across markets because an adapter
  // review may be attached to its best run in a different market.
  const savedReview = allRuns.filter(r => r.input.strategy.id === strategy.id && currentRun(r, strategy))
    .flatMap(r => readTestingReviews(r.notes)
      .filter(review => review.sourceHash === (r.input.protocol === 2 ? strategyExecutionHash(strategy) : strategy.file_hash))
      .map(review => ({ ...review, runId: r.id })))
    .sort((a, b) => b.reviewedAt.localeCompare(a.reviewedAt))[0];
  const reviewedIssues = issues.filter(i => savedReview?.issueKeys.includes(reviewIssueKey(i))).length;
  const newEvidence = !!savedReview && runs.some(r => !savedReview.runIds.includes(r.id)
    || Date.parse(r.ended_at || r.created_at) > Date.parse(savedReview.reviewedAt));
  const reviewComplete = !!savedReview && runs.length > 0 && !inProgress && !newEvidence && reviewedIssues === issues.length;
  const status = stageLabel(stage);
  const review = reviewComplete ? "Complete" : inProgress || newEvidence ? "New evidence pending" : "Pending";
  return {
    strategyId: strategy.id,
    status, tone: stageColor(stage), stage, configurations, passingConfigurations, failingConfigurations,
    scope: symbol || "All tested markets", inProgress, review,
    total: runs.length, terminal, queued, running, summarizing, succeeded: successful.length,
    executionFailed: runs.filter(r => ["Failed", "Interrupted", "Timed out"].includes(r.status)).length,
    previousSource: history.length - runs.length, issues, progress,
    savedReview: runs.length ? savedReview : undefined, reviewedIssues, reviewComplete,
    best: candidates[0] || null,
    latestEvaluation: evaluations[0],
  };
}
