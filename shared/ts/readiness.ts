import type { EvaluationView, RunSummary } from "./workbenchModels.ts";
import { lifecycleStatus, type StrategyStageStatus } from "./strategyLifecycle.ts";

export type ReadinessPhase = "robustness" | "forward-plan" | "forward-complete" | "practical";
export const readinessChecks = {
  robustness: [
    { id: "parameters", label: "Nearby parameters and selection sensitivity" },
    { id: "coverage", label: "Market/regime coverage and sample sufficiency" },
    { id: "execution", label: "Execution parity, fills, liquidity and realistic costs" },
    { id: "risk", label: "Risk limits, capital and overlapping exposure" },
  ],
  "forward-plan": [{ id: "plan", label: "Frozen paper-testing protocol and observation log" }],
  "forward-complete": [
    { id: "ledger", label: "Prospective paper-trade ledger" },
    { id: "reconciliation", label: "Signal/fill reconciliation and deviations from the frozen plan" },
  ],
  practical: [
    { id: "operating", label: "Operating plan and execution setup" },
    { id: "limits", label: "Capital, position limits and stop conditions" },
    { id: "monitoring", label: "Monitoring, incident response and rollback plan" },
  ],
} as const;
export type ForwardPlan = { start: string; minDays: number; minTrades: number; minReturn: number; maxDrawdown: number };
export type ForwardObservation = { end: string; trades: number; netReturn: number; maxDrawdown: number };
export type ReadinessReview = {
  version: 1; id: string; phase: ReadinessPhase; runId: string; configurationKey: string;
  recordedAt: string; reviewer: string; evidenceSnapshot: string; parentId?: string;
  references: Record<string, string>; plan?: ForwardPlan; observation?: ForwardObservation;
};

/** Exact comparison of evidence facts, excluding notes and readiness annotations.
 * Changes to a result, source, parameters, costs or a new attempt require review. */
export function readinessEvidenceSnapshot(runs: RunSummary[], evaluations: EvaluationView[]) {
  const ids = new Set(runs.map(run => run.id));
  return JSON.stringify([
    [...runs].sort((a, b) => a.id.localeCompare(b.id)).map(run => ({
      id: run.id, status: run.status, input: run.input, error: run.error || "",
      checksFailed: (run.tags || "").split(/[,\s]+/).includes("checks-failed"),
      metrics: run.result?.metrics, warnings: run.result?.warnings || [],
    })),
    evaluations.filter(e => e.folds.some(f => [...f.training, ...f.tests].some(id => ids.has(id))))
      .sort((a, b) => a.id.localeCompare(b.id)).map(e => ({
        id: e.id, status: e.status, folds: e.folds, scenarios: e.scenarios, error: e.error,
        criteria: [e.min_trades, e.min_test_trades, e.min_return, e.max_drawdown],
        results: e.result?.scenarios.map(s => ({ name: s.name, outcome: s.outcome, metrics: s.metrics })),
      })),
  ]);
}
const day = (text: string) => /^\d{4}-\d{2}-\d{2}$/.test(text) && Number.isFinite(Date.parse(text)) && new Date(text).toISOString().slice(0, 10) === text;
const finite = (value: unknown) => typeof value === "number" && Number.isFinite(value);
export function validReadinessReview(value: ReadinessReview) {
  if (!value || value.version !== 1 || !value.id || !value.runId || !value.configurationKey || !value.evidenceSnapshot
    || !finite(Date.parse(value.recordedAt)) || typeof value.reviewer !== "string" || !value.reviewer.trim()
    || !Object.hasOwn(readinessChecks, value.phase) || !value.references) return false;
  if (!readinessChecks[value.phase].every(check => typeof value.references[check.id] === "string" && value.references[check.id].trim().length >= 8)) return false;
  if (value.phase !== "robustness" && !value.parentId) return false;
  if (value.phase === "forward-plan") {
    const p = value.plan;
    if (!p || !day(p.start) || p.start <= value.recordedAt.slice(0, 10)
      || !Number.isInteger(p.minDays) || p.minDays < 1 || !Number.isInteger(p.minTrades) || p.minTrades < 1
      || !finite(p.minReturn) || !finite(p.maxDrawdown) || p.maxDrawdown <= 0 || p.maxDrawdown > 1) return false;
  }
  if (value.phase === "forward-complete") {
    const o = value.observation;
    if (!o || !day(o.end) || o.end > value.recordedAt.slice(0, 10) || !Number.isInteger(o.trades) || o.trades < 0
      || !finite(o.netReturn) || !finite(o.maxDrawdown) || o.maxDrawdown < 0 || o.maxDrawdown > 1) return false;
  }
  return true;
}
export function forwardFailures(plan: ForwardPlan, observation: ForwardObservation) {
  const days = (Date.parse(observation.end) - Date.parse(plan.start)) / 86400000 + 1;
  return [
    days < plan.minDays ? `${days} observed days; ${plan.minDays} required.` : "",
    observation.trades < plan.minTrades ? `${observation.trades} paper trades; ${plan.minTrades} required.` : "",
    observation.netReturn < plan.minReturn ? "Observed net return is below the frozen minimum." : "",
    observation.maxDrawdown > plan.maxDrawdown ? "Observed drawdown exceeds the frozen limit." : "",
  ].filter(Boolean);
}

export function applyReadiness(base: StrategyStageStatus, runs: RunSummary[], evaluations: EvaluationView[], key: string, seedId: string): StrategyStageStatus {
  if (base.kind !== "evaluation-passed") return base;
  const snapshot = readinessEvidenceSnapshot(runs, evaluations);
  const reviews = runs.flatMap(run => (Array.isArray(run.readiness_reviews) ? run.readiness_reviews : []).filter(r => validReadinessReview(r) && r.runId === run.id))
    .filter(r => r.configurationKey === key && r.evidenceSnapshot === snapshot)
    .sort((a, b) => b.recordedAt.localeCompare(a.recordedAt) || b.id.localeCompare(a.id));
  const robustness = reviews.find(r => r.phase === "robustness");
  const action = (label: string) => ({ kind: "review-readiness" as const, runId: seedId, label });
  if (!robustness) return { ...base,
    finding: "Declared historical evaluation checks passed. Robustness, prospective testing and practical readiness remain unestablished.",
    checks: readinessChecks.robustness.map(c => c.label), action: action("Validate robustness & execution") };
  const plan = reviews.find(r => r.phase === "forward-plan" && r.parentId === robustness.id && r.recordedAt >= robustness.recordedAt);
  const complete = plan && reviews.find(r => r.phase === "forward-complete" && r.parentId === plan.id && r.recordedAt >= plan.recordedAt && r.observation!.end >= plan.plan!.start);
  const failure = complete && forwardFailures(plan!.plan!, complete.observation!);
  const practical = complete && reviews.find(r => r.phase === "practical" && r.parentId === complete.id && r.recordedAt >= complete.recordedAt);
  let status: StrategyStageStatus;
  if (failure?.length) status = { ...lifecycleStatus("failed-checks", 3, "The recorded prospective paper test did not meet its frozen criteria.", failure, action("Review forward test & revise plan")), failedStage: 4 };
  else if (practical) status = lifecycleStatus("practical-ready", 5, `Practical readiness accepted by ${practical.reviewer} on ${practical.recordedAt.slice(0, 10)}, based on the recorded evidence and operating scope.`, [], { kind: "open-portfolio", label: "Open portfolio · refresh histories to import" });
  else if (complete) status = lifecycleStatus("forward-tested", 4, "Recorded paper observations met the frozen criteria. The practical operating checklist still needs acceptance.", readinessChecks.practical.map(c => c.label), action("Review practical readiness"));
  else if (plan) status = lifecycleStatus("forward-testing", 4, `Prospective paper-testing plan frozen by ${plan.reviewer}; observations start ${plan.plan!.start}.`, ["Record prospective paper observations and reconcile the ledger against the frozen criteria."], action("Record forward test results"));
  else status = lifecycleStatus("robustness-validated", 3, `Robustness and execution evidence reviewed by ${robustness.reviewer}. Prospective paper testing is the next stage.`, ["Freeze a prospective test window and its success criteria before collecting observations."], action("Plan forward testing"));
  return { ...status, readiness: practical || complete || plan || robustness };
}

/** Called by the server with fresh evidence and a server-assigned time/ID. */
export function createReadinessReview(input: unknown, seed: RunSummary, status: StrategyStageStatus, runs: RunSummary[], evaluations: EvaluationView[], key: string, recordedAt: string, id: string): ReadinessReview {
  const data = input as Partial<ReadinessReview>;
  if (!data || !Object.hasOwn(readinessChecks, data.phase || "")) throw new Error("Select a supported readiness review");
  const phase = data.phase!;
  const eligible = phase === "robustness" ? ["evaluation-passed", "robustness-validated", "forward-testing", "forward-tested", "practical-ready"].includes(status.kind)
    : phase === "forward-plan" ? ["robustness-validated", "forward-testing", "forward-tested", "practical-ready"].includes(status.kind) || status.stage === 3 && status.kind === "failed-checks" && status.readiness?.phase === "forward-complete"
    : phase === "forward-complete" ? status.kind === "forward-testing" : status.kind === "forward-tested";
  if (!eligible) throw new Error("Complete the preceding stage on the current evidence before recording this review");
  const current = status.readiness;
  // A replacement prospective plan must chain to the accepted robustness review.
  const saved = runs.flatMap(r => Array.isArray(r.readiness_reviews) ? r.readiness_reviews : []).filter(validReadinessReview);
  let robustness = current;
  const visited = new Set<string>();
  while (robustness && robustness.phase !== "robustness" && !visited.has(robustness.id)) {
    visited.add(robustness.id);
    robustness = saved.find(r => r.id === robustness!.parentId);
  }
  const parentId = phase === "robustness" ? undefined : phase === "forward-plan" ? robustness?.id : current?.id;
  const references = Object.fromEntries(readinessChecks[phase].map(check => [check.id, String(data.references?.[check.id] || "").trim().slice(0, 4000)]));
  const record: ReadinessReview = { version: 1, id, phase, runId: seed.id, configurationKey: key,
    recordedAt, reviewer: String(data.reviewer || "").trim().slice(0, 120), evidenceSnapshot: readinessEvidenceSnapshot(runs, evaluations),
    parentId, references, ...(phase === "forward-plan" ? { plan: data.plan } : {}), ...(phase === "forward-complete" ? { observation: data.observation } : {}) };
  if (!validReadinessReview(record)) throw new Error("Provide a reviewer, evidence for every check, and valid prospective dates and criteria");
  if (record.plan && runs.some(run => run.input.end >= record.plan!.start)) throw new Error("Forward observations must start after every inspected historical test window");
  if (record.observation && record.observation.end < current!.plan!.start) throw new Error("Forward observations must end on or after the frozen start");
  return record;
}
