import { useState } from "react";
import type {
  EvaluationFold as Fold,
  EvaluationView,
  RunSummary,
} from "../../../shared/ts/workbenchModels.ts";
import { detailTabs, filterEvaluations, type ResearchDetailTab } from "./researchModel";

export function useResearchController({
  evaluations,
  refresh,
  runs,
  selectedId,
  initialRunId,
}: {
  evaluations: EvaluationView[];
  refresh: () => Promise<void>;
  runs: RunSummary[];
  selectedId?: string;
  initialRunId?: string;
}) {
  const initialRun = runs.find(run => run.id === initialRunId && run.status === "Succeeded");
  const [planOpen, setPlanOpen] = useState(!!initialRun);
  const [seedId, setSeedId] = useState(initialRun?.id || "");
  const [name, setName] = useState(initialRun ? `${initialRun.input.strategy.name} evaluation` : "Rolling trend evaluation");
  const [start, setStart] = useState(initialRun?.input.start || "");
  const [end, setEnd] = useState(initialRun?.input.end || "");
  const [train, setTrain] = useState(60);
  const [test, setTest] = useState(30);
  const [folds, setFolds] = useState(3);
  const [metric, setMetric] = useState("net_pnl");
  const [minTrades, setMinTrades] = useState(1);
  const [minTest, setMinTest] = useState(10);
  const [minReturn, setMinReturn] = useState(0);
  const [maxDrawdown, setMaxDrawdown] = useState(20);
  const [cost, setCost] = useState(2);
  const [delay, setDelay] = useState(1);
  const [sweep, setSweep] = useState(initialRun ? "{}" : '{"lookback": [10, 20, 40]}');
  const [hypothesis, setHypothesis] = useState("");
  const [preview, setPreview] = useState<{ jobs: number; folds: Fold[] } | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feature, setFeature] = useState("volatility");
  const [window, setWindow] = useState(20);
  const [quantile, setQuantile] = useState(0.5);
  const [outcomeFilter, setOutcomeFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<ResearchDetailTab>(detailTabs[0]);
  const seed = runs.find((run) => run.id === seedId);
  const current = evaluations.find((evaluation) => evaluation.id === selectedId) || evaluations[0];
  const key = JSON.stringify([
    seedId,
    start,
    end,
    name,
    train,
    test,
    folds,
    metric,
    minTrades,
    minTest,
    minReturn,
    maxDrawdown,
    cost,
    delay,
    sweep,
    hypothesis,
  ]);
  const validPreview = key === previewKey ? preview : null;

  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  function payload() {
    if (!seed) throw new Error("Choose a successful run as the starting configuration");
    return {
      name,
      base: {
        ...seed.input,
        strategy_id: seed.input.strategy.id,
        dataset_id: seed.input.dataset.id,
        start,
        end,
      },
      sweep: JSON.parse(sweep),
      train_days: train,
      test_days: test,
      folds,
      metric,
      min_trades: minTrades,
      min_test_trades: minTest,
      min_return: minReturn / 100,
      max_drawdown: maxDrawdown / 100,
      stress_multiple: cost,
      delay_bars: seed.input.strategy.execution_model === "event-v1" ? 0 : delay,
      hypothesis,
    };
  }

  function chooseSeed(id: string | null) {
    const run = runs.find((candidate) => candidate.id === id);
    if (!run) return;
    setSeedId(run.id);
    setEnd(run.input.end);
    const suggested = new Date(
      Date.parse(run.input.end) - (train + test * folds - 1) * 86400000,
    ).toISOString().slice(0, 10);
    setStart(
      suggested < run.input.dataset.first.slice(0, 10)
        ? run.input.dataset.first.slice(0, 10)
        : suggested,
    );
    const field = Object.keys(run.input.parameters).find((key) => key === "lookback");
    setSweep(field ? '{"lookback": [10, 20, 40]}' : "{}");
    setPreview(null);
  }

  const filtered = filterEvaluations(evaluations, outcomeFilter, query);
  return {
    act,
    busy,
    chooseSeed,
    cost,
    current,
    delay,
    end,
    error,
    feature,
    folds,
    hypothesis,
    key,
    maxDrawdown,
    metric,
    minReturn,
    minTest,
    minTrades,
    name,
    outcomeFilter,
    payload,
    planOpen,
    preview,
    query,
    quantile,
    seed,
    seedId,
    setCost,
    setDelay,
    setEnd,
    setError,
    setFeature,
    setFolds,
    setHypothesis,
    setMaxDrawdown,
    setMetric,
    setMinReturn,
    setMinTest,
    setMinTrades,
    setName,
    setOutcomeFilter,
    setPlanOpen,
    setPreview,
    setPreviewKey,
    setQuery,
    setQuantile,
    setSeedId,
    setStart,
    setSweep,
    setTab,
    setTest,
    setTrain,
    setWindow,
    start,
    sweep,
    tab,
    test,
    train,
    validPreview,
    window,
    ...filtered,
  };
}

export type ResearchController = ReturnType<typeof useResearchController>;
