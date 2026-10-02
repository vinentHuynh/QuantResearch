import { runConfigurationKey } from "./evidence.ts";
import { readinessEvidenceSnapshot } from "./readiness.ts";
import { lifecycleStatus, type StrategyStageStatus } from "./strategyLifecycle.ts";
import type { EvaluationView, RunSummary } from "./workbenchModels.ts";

export type StageAssessment = {
  version: 1;
  id: string;
  runId: string;
  configurationKey: string;
  sourceHash: string;
  attemptedStage: 1 | 2 | 3 | 4 | 5;
  outcome: "passed" | "failed" | "blocked";
  criteria: string[];
  findings: string;
  evidence: string[];
  reviewer: string;
  evidenceSnapshot: string;
  recordedAt: string;
};

const sourceHash = (run: RunSummary) => run.input.execution_source_hash || run.input.source_hash || run.input.strategy.execution_source_hash || run.input.strategy.file_hash;
export const matchingConfiguration = (seed: RunSummary, runs: RunSummary[]) => runs.filter(run =>
  !run.input.portfolio_replay && run.input.strategy.id === seed.input.strategy.id && runConfigurationKey(run) === runConfigurationKey(seed));
const relatedEvaluations = (runs: RunSummary[], evaluations: EvaluationView[]) => {
  const ids = new Set(runs.map(run => run.id));
  return evaluations.filter(evaluation => evaluation.folds.some(fold => [...fold.training, ...fold.tests].some(id => ids.has(id))));
};

export function createStageAssessment(input: unknown, seed: RunSummary, status: StrategyStageStatus, runs: RunSummary[], evaluations: EvaluationView[], recordedAt: string, id: string): StageAssessment {
  const data = input as Partial<StageAssessment>;
  if (!data || ![1, 2, 3, 4, 5].includes(Number(data.attemptedStage)) || !["passed", "failed", "blocked"].includes(String(data.outcome))) throw new Error("Choose a valid stage and outcome");
  const attemptedStage = Number(data.attemptedStage) as StageAssessment["attemptedStage"];
  const criteria = Array.isArray(data.criteria) ? data.criteria.map(String).map(s => s.trim()).filter(Boolean) : [];
  const evidence = Array.isArray(data.evidence) ? data.evidence.map(String).map(s => s.trim()).filter(Boolean) : [];
  const findings = String(data.findings || "").trim();
  const reviewer = String(data.reviewer || "").trim();
  if (!reviewer || !findings || !criteria.length || !evidence.length || criteria.length > 30 || evidence.length > 50 || [findings, reviewer, ...criteria, ...evidence].some(s => s.length > 4000)) throw new Error("Provide reviewer, criteria, findings, and evidence references");
  if (attemptedStage > status.stage + 1) throw new Error("Complete preceding stages first");
  if (data.outcome === "passed" && status.stage < attemptedStage) throw new Error("A stage can pass only after its workbench prerequisite is recorded");
  const related = relatedEvaluations(runs, evaluations);
  const validIds = new Set([...runs.map(run => run.id), ...related.map(evaluation => evaluation.id)]);
  if (!evidence.some(ref => validIds.has(ref)) || evidence.some(ref => !validIds.has(ref) && !/^https?:\/\//.test(ref) && !/^[A-Za-z]:[\\/]/.test(ref))) throw new Error("Reference linked run or evaluation evidence; external evidence may use a URL or absolute path");
  return {
    version: 1, id, runId: seed.id, configurationKey: runConfigurationKey(seed), sourceHash: sourceHash(seed),
    attemptedStage, outcome: data.outcome!, criteria, findings, evidence, reviewer,
    evidenceSnapshot: readinessEvidenceSnapshot(runs, evaluations), recordedAt,
  };
}

export function applyStageAssessments(base: StrategyStageStatus, seed: RunSummary, runs: RunSummary[], evaluations: EvaluationView[]): StrategyStageStatus {
  const snapshot = readinessEvidenceSnapshot(runs, evaluations);
  const current = runs.flatMap(run => run.stage_assessments || [])
    .filter(record => record?.version === 1 && record.configurationKey === runConfigurationKey(seed) && record.sourceHash === sourceHash(seed) && record.evidenceSnapshot === snapshot)
    .sort((a, b) => b.recordedAt.localeCompare(a.recordedAt) || b.id.localeCompare(a.id))[0];
  if (!current || current.outcome === "passed" || base.kind === "retest-required") return base;
  // A later milestone supersedes an older judgment. For the same milestone,
  // the linked manual review can reject a coarse automatic evaluation pass
  // when a frozen per-fold or sample rule is stricter than its headline check.
  if (base.stage > current.attemptedStage) return base;
  const completedStage = Math.min(base.stage, current.attemptedStage - 1) as StrategyStageStatus["stage"];
  const result = lifecycleStatus(current.outcome === "failed" ? "failed-checks" : "needs-review", completedStage,
    current.findings, current.criteria, base.action);
  return { ...result, ...(current.outcome === "failed" ? { failedStage: current.attemptedStage } : { blockedStage: current.attemptedStage }), assessment: current };
}
