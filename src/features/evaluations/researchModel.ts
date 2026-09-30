import type { EvaluationView } from "../../../shared/ts/workbenchModels.ts";

export const detailTabs = [
  "Summary",
  "Fold selection & sensitivity",
  "Joined test path",
  "Regime study",
] as const;

export type ResearchDetailTab = (typeof detailTabs)[number];

export const formatPercent = (value: number | null | undefined) =>
  value == null ? "—" : `${(value * 100).toFixed(2)}%`;

export const formatNumber = (value: number | null | undefined) =>
  value == null
    ? "—"
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });

export const evaluationStatusColor = (status: string) =>
  status === "Succeeded"
    ? "teal"
    : ["Failed", "Interrupted"].includes(status)
      ? "red"
      : "blue";

export const evaluationOutcomeColor = (outcome?: string) =>
  outcome === "Meets criteria"
    ? "teal"
    : outcome === "Does not meet criteria"
      ? "red"
      : "gray";

export function filterEvaluations(
  evaluations: EvaluationView[],
  outcomeFilter: string,
  query: string,
) {
  const meets = evaluations.filter(
    (evaluation) => evaluation.outcome === "Meets criteria",
  );
  const fails = evaluations.filter(
    (evaluation) => evaluation.outcome === "Does not meet criteria",
  );
  const candidates =
    outcomeFilter === "meets"
      ? meets
      : outcomeFilter === "fails"
        ? fails
        : evaluations;
  const normalized = query.toLowerCase();
  return {
    meets,
    fails,
    listed: candidates.filter((evaluation) =>
      evaluation.name.toLowerCase().includes(normalized),
    ),
  };
}
