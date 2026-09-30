import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import type { Run, RunSummary } from "../../../shared/ts/workbenchModels.ts";
import { navGroups, useRoute, type Page } from "../../app/navigation";
import type { SearchResult } from "../../app/Shell";
import {
  WORKBENCH_API as API,
  workbenchRequest as request,
} from "../../shared/api/workbench";
import {
  initialNewRunInput as initial,
  NEW_RUN_DRAFT_KEY as DRAFT_KEY,
  parseSweep,
  readNewRunDraft as readDraft,
  type NewRunInput as Input,
} from "../new-run/model";
import {
  compareRunValues,
  latestRunsByConfiguration,
  runSortColumns,
} from "../runs/model";
import type {
  DeletionPreview,
  RunComparison,
  WarmupCheck,
  WorkbenchState,
} from "./workbenchModel";
import { shortId } from "./workbenchModel";

/** Owns the Workbench's route-aware state, polling, and commands.
 *
 * Presentation lives in the vertical feature modules. Keeping the controller
 * here makes the page shell small without changing the request cadence or the
 * persisted new-run draft.
 */
export function useWorkbenchController() {
  const [deletion, setDeletion] = useState<DeletionPreview | null>(null);
  const [state, setState] = useState<WorkbenchState | null>(null);
  const stateEtag = useRef("");
  const [route, go] = useRoute();
  const [researchSelection, setResearchSelection] = useState("");
  const [dashboardRefresh, setDashboardRefresh] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const draft = useMemo(readDraft, []);
  const [input, setInput] = useState<Input>(draft?.input || initial);
  const [sweepText, setSweepText] = useState(draft?.sweepText || "{}");
  const [preview, setPreview] = useState<number | null>(null);
  const [warmupChecks, setWarmupChecks] = useState<WarmupCheck[]>([]);
  const [step, setStep] = useState(draft?.step || 0);
  const [showAllAttempts, setShowAllAttempts] = useState(false);
  const [filter, setFilter] = useState("");
  const [testingMarket, setTestingMarket] = useState("");
  const [stage, setStage] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("created:desc");
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<RunComparison | null>(null);
  const [detail, setDetail] = useState<Run | null>(null);
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [reason, setReason] = useState("");
  const [presetName, setPresetName] = useState("");
  const [viewName, setViewName] = useState("");
  const [viewOpen, setViewOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(API + "/state?view=summary", {
        headers: stateEtag.current ? { "If-None-Match": stateEtag.current } : {},
      });
      if (response.status === 304) return;
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || response.statusText);
      stateEtag.current = response.headers.get("ETag") || "";
      setState(data as WorkbenchState);
    } catch (caught) {
      setError(String(caught));
    }
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!document.hidden) await refresh();
      if (!stopped) timer = setTimeout(() => void poll(), 10000);
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [refresh]);

  useEffect(() => {
    if (!detail || !["Queued", "Running"].includes(detail.status)) return;
    const timer = setInterval(() => {
      request<Run>(`/runs/${detail.id}`)
        .then(setDetail)
        .catch((caught) => setError(String(caught)));
    }, 1000);
    return () => clearInterval(timer);
  }, [detail]);

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [route.page]);

  useEffect(() => {
    try {
      localStorage.setItem(
        DRAFT_KEY,
        JSON.stringify({ input, sweepText, step, saved_at: new Date().toISOString() }),
      );
    } catch {
      // A draft is a convenience; the server remains the source of truth.
    }
  }, [input, sweepText, step]);

  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  function change<K extends keyof Input>(key: K, value: Input[K]) {
    setInput((current) => ({ ...current, [key]: value }));
    setPreview(null);
  }

  function chooseStrategy(id: string) {
    const selectedStrategy = state?.strategies.find((candidate) => candidate.id === id);
    if (!selectedStrategy) return;
    setInput((current) => ({
      ...current,
      strategy_id: id,
      warmup_days: Math.max(
        current.warmup_days,
        selectedStrategy.default_warmup_days || 0,
      ),
      session: selectedStrategy.default_session || current.session,
      timeframes: [],
      parameters: Object.fromEntries(
        Object.entries(selectedStrategy.parameters).map(([key, field]) => [
          key,
          field.default,
        ]),
      ),
      timeframe: selectedStrategy.timeframes.includes(current.timeframe)
        ? current.timeframe
        : selectedStrategy.timeframes[0],
    }));
    setPreview(null);
    setSweepText("{}");
  }

  function configure(id: string) {
    chooseStrategy(id);
    setStep(0);
    go("new-run");
  }

  function runInput() {
    return {
      ...input,
      dataset_ids: [...new Set([input.dataset_id, ...(input.dataset_ids || [])])],
      timeframes: [...new Set([input.timeframe, ...(input.timeframes || [])])],
      sweep: JSON.parse(sweepText),
    };
  }

  async function inspect(run: RunSummary) {
    const result = await request<Run>(`/runs/${run.id}`);
    setDetail(result);
    setNotes(result.notes || "");
    setTags(result.tags || "");
    setReason("");
  }

  function reuse(run: Run) {
    setInput({
      ...run.input,
      strategy_id: run.input.strategy.id,
      dataset_id: run.input.dataset.id,
      dataset_ids: [],
      timeframes: [],
      stage: run.input.stage === "Tracking" ? "Exploratory" : run.input.stage,
      sweep: {},
    });
    setSweepText("{}");
    setPreview(null);
    setDetail(null);
    setStep(0);
    go("new-run");
  }

  function updateSweep(key: string, values: unknown[]) {
    const current = parseSweep(sweepText);
    if (!current) return;
    const next = { ...current };
    if (values.length) next[key] = values;
    else delete next[key];
    setSweepText(JSON.stringify(next));
    setPreview(null);
  }

  const strategy = state?.strategies.find((candidate) => candidate.id === input.strategy_id);
  const dataset = state?.datasets.find((candidate) => candidate.id === input.dataset_id);
  const [sortKey, sortDirection] = sort.split(":");
  const sortColumn = runSortColumns.find((column) => column.key === sortKey)!;
  const now = Date.now();
  const latestHistory = useMemo(
    () => latestRunsByConfiguration(state?.runs || []),
    [state?.runs],
  );
  const latestRunIds = useMemo(
    () => new Set(latestHistory.map((run) => run.id)),
    [latestHistory],
  );
  const historyRuns = showAllAttempts
    ? state?.runs || []
    : (state?.runs || []).filter((run) => latestRunIds.has(run.id));
  const filtered = historyRuns
    .filter(
      (run) =>
        (!stage || run.input.stage === stage) &&
        (!status || run.status === status) &&
        `${run.input.strategy.name} ${run.input.dataset.symbol} ${run.id} ${run.tags || ""} ${run.input.hypothesis}`
          .toLowerCase()
          .includes(filter.toLowerCase()),
    )
    .sort((left, right) =>
      compareRunValues(
        sortColumn.value(left, now),
        sortColumn.value(right, now),
        sortDirection === "desc",
      ),
    );
  const compareRuns =
    comparison?.runs ||
    (comparison?.rows || [])
      .map((row) => state?.runs.find((run) => run.id === row.id))
      .filter((run): run is RunSummary => !!run);
  const counts = {
    total: historyRuns.length,
    active: historyRuns.filter((run) => ["Running", "Queued"].includes(run.status)).length,
    success: historyRuns.filter((run) => run.status === "Succeeded").length,
  };
  const compareBlocked =
    selected.length < 2 ||
    selected.length > 8 ||
    busy ||
    selected.some(
      (id) => state?.runs.find((run) => run.id === id)?.status !== "Succeeded",
    );
  const navCounts: Partial<Record<Page, number>> = state
    ? {
        workspace: latestHistory.length,
        runs: latestHistory.length,
        evaluations: (state.evaluations || []).length,
        watchlist: state.watchlist.length,
        scripts: state.strategies.length,
        datasets: state.datasets.length,
      }
    : {};
  const sweep = parseSweep(sweepText);
  const planDatasets = [
    ...new Set([input.dataset_id, ...(input.dataset_ids || [])].filter(Boolean)),
  ].length;
  const planTimeframes = [
    ...new Set([input.timeframe, ...(input.timeframes || [])].filter(Boolean)),
  ].length;
  const planCombos = sweep
    ? Object.values(sweep).reduce(
        (count, values) =>
          count * (Array.isArray(values) ? Math.max(1, values.length) : 1),
        1,
      )
    : null;
  const estimate =
    planCombos === null
      ? null
      : Math.max(1, planDatasets) * planTimeframes * planCombos;
  const planned = preview ?? estimate;
  const maxBatch = state?.limits.maxBatch || 24;

  const search = useMemo(
    () =>
      (query: string): SearchResult[] => {
        const normalized = query.trim().toLowerCase();
        const pages: SearchResult[] = [
          ...navGroups({}).flatMap((group) =>
            group.items.map((item) => ({
              group: "Pages",
              label: item.label,
              detail: group.label,
              run: () => go(item.page),
            })),
          ),
          {
            group: "Pages",
            label: "New run",
            detail: "Research",
            run: () => go("new-run"),
          },
        ].filter((page) => !normalized || page.label.toLowerCase().includes(normalized));
        if (!normalized || !state) return pages;
        const runs: SearchResult[] = state.runs
          .filter((run) =>
            `${run.input.strategy.name} ${run.input.dataset.symbol} ${run.id} ${run.tags || ""}`
              .toLowerCase()
              .includes(normalized),
          )
          .slice(0, 5)
          .map((run) => ({
            group: "Runs",
            label: `${strategyTitle(run.input.strategy.name)} · ${run.input.dataset.symbol} ${run.input.timeframe}`,
            detail: `${shortId(run.id)} · ${run.status} · ${run.input.start} → ${run.input.end}`,
            run: () => {
              go("runs");
              void action(() => inspect(run));
            },
          }));
        const strategies: SearchResult[] = state.strategies
          .filter((candidate) =>
            `${candidate.name} ${candidate.id}`.toLowerCase().includes(normalized),
          )
          .slice(0, 4)
          .map((candidate) => ({
            group: "Configure a run",
            label: strategyTitle(candidate.name),
            detail: candidate.timeframes.join(" · "),
            run: () => configure(candidate.id),
          }));
        const evaluations: SearchResult[] = (state.evaluations || [])
          .filter((evaluation) => evaluation.name.toLowerCase().includes(normalized))
          .slice(0, 4)
          .map((evaluation) => ({
            group: "Evaluations",
            label: evaluation.name,
            detail: evaluation.outcome || evaluation.status,
            run: () => {
              setResearchSelection(evaluation.id);
              go("evaluations");
            },
          }));
        return [...pages, ...runs, ...strategies, ...evaluations];
      },
    // The route callback is stable and the remaining commands deliberately use
    // the current state captured by this memo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state, go],
  );

  function refreshAll() {
    void refresh();
    setDashboardRefresh((value) => value + 1);
  }

  return {
    action,
    busy,
    change,
    chooseStrategy,
    compareBlocked,
    compareRuns,
    comparison,
    configure,
    counts,
    dashboardRefresh,
    dataset,
    deletion,
    detail,
    error,
    estimate,
    filter,
    filtered,
    go,
    historyRuns,
    input,
    inspect,
    latestHistory,
    maxBatch,
    navCounts,
    notes,
    notice,
    planned,
    planCombos,
    planDatasets,
    planTimeframes,
    presetName,
    preview,
    reason,
    refresh,
    refreshAll,
    researchSelection,
    reuse,
    route,
    runInput,
    search,
    selected,
    setComparison,
    setDeletion,
    setDetail,
    setError,
    setFilter,
    setInput,
    setNotes,
    setNotice,
    setPresetName,
    setPreview,
    setReason,
    setResearchSelection,
    setSelected,
    setShowAllAttempts,
    setSort,
    setStage,
    setStatus,
    setStep,
    setSweepText,
    setTags,
    setTestingMarket,
    setViewName,
    setViewOpen,
    setWarmupChecks,
    showAllAttempts,
    sort,
    sortColumn,
    sortDirection,
    stage,
    state,
    status,
    step,
    strategy,
    sweep,
    sweepText,
    tags,
    testingMarket,
    updateSweep,
    viewName,
    viewOpen,
    warmupChecks,
  };
}

export type WorkbenchController = ReturnType<typeof useWorkbenchController>;
