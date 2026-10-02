import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import type { StrategyNextAction } from "../../../shared/ts/strategyLifecycle.ts";
import type { Run, RunSummary } from "../../../shared/ts/workbenchModels.ts";
import { archivedConfigurationForRun } from "../../../shared/ts/researchArchive.ts";
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
  runHistoryGroups,
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
  const [portfolioPickerOpen, setPortfolioPickerOpen] = useState(
    route.page === "portfolio" && route.sub === "strategies",
  );
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
      const next = data as WorkbenchState;
      const visibleRunIds = new Set(next.runs.map(run => run.id));
      setDetail(current => current && !visibleRunIds.has(current.id) ? null : current);
      setSelected(current => current.every(id => visibleRunIds.has(id)) ? current : current.filter(id => visibleRunIds.has(id)));
      setComparison(current => current && [...(current.runs || []), ...(current.rows || [])].some(run => !visibleRunIds.has(run.id)) ? null : current);
      setDeletion(current => current && current.ids.some(id => !visibleRunIds.has(id)) ? null : current);
      setState(next);
    } catch (caught) {
      setError(String(caught));
    }
  }, []);

  useEffect(() => {
    if (route.page === "portfolio" && !portfolioPickerOpen) return;
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
  }, [refresh, route.page, portfolioPickerOpen]);

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
    setSelected([]);
  }, [route.page, route.sub, filter, stage, status, showAllAttempts]);

  useEffect(() => {
    setComparison(null);
  }, [route.page, route.sub]);

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

  async function archiveRuns(ids: string[]) {
    if (!ids.length || busy) return;
    await action(async () => {
      await request("/runs/archive", { ids });
      setSelected([]);
      setComparison(null);
      setNotice(`${ids.length === 1 ? "Run" : `${ids.length} runs`} archived. Restore from the Archive tab.`);
    });
  }

  async function restoreRuns(ids: string[]) {
    if (!ids.length || busy) return;
    await action(async () => {
      await request("/runs/unarchive", { ids });
      setSelected([]);
      const configurationStillArchived = state?.runs.some(run => ids.includes(run.id) && archivedConfigurationForRun(run, state.research_archive));
      setNotice(`${ids.length === 1 ? "Run" : `${ids.length} runs`} restored.${configurationStillArchived ? " Runs with an archived configuration stay in Archive until that configuration is restored." : ""}`);
    });
  }

  async function restoreRunConfiguration(runId: string) {
    if (busy) return;
    await action(async () => {
      await request("/configurations/unarchive", { run_id: runId });
      setSelected([]);
      setNotice("Configuration restored. Individually archived runs remain in Archive.");
    });
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
  }

  const handledRunLink = useRef("");
  useEffect(() => {
    const runId = route.page === "runs" && route.sub.startsWith("inspect~")
      ? route.sub.slice("inspect~".length)
      : "";
    if (!runId) {
      handledRunLink.current = "";
      return;
    }
    if (!state || handledRunLink.current === runId) return;
    handledRunLink.current = runId;
    const run = state.runs.find(candidate => candidate.id === runId);
    if (run) void action(() => inspect(run));
    else setError(`Saved run ${runId} is no longer in the Workbench.`);
    go("runs");
  // The route and loaded run list drive this one-shot action.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.page, route.sub, state, go]);

  function addRunToPortfolio(runId: string) {
    setDetail(null);
    setPortfolioPickerOpen(true);
    go("portfolio", `add~${runId}`);
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
  const { activeRuns, archivedRuns, latestHistory } = useMemo(
    () => runHistoryGroups(state?.runs || [], state?.research_archive),
    [state?.runs, state?.research_archive],
  );
  const latestRunIds = useMemo(
    () => new Set(latestHistory.map((run) => run.id)),
    [latestHistory],
  );
  const archiveView = route.page === "runs" && route.sub === "archive";
  const historyRuns = archiveView
    ? archivedRuns
    : showAllAttempts ? activeRuns : activeRuns.filter((run) => latestRunIds.has(run.id));
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
    active: historyRuns.filter((run) => ["Running", "Queued", "Summarizing"].includes(run.status)).length,
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

  function stageAction(next: StrategyNextAction) {
    if (next.kind === "open-evaluation" && next.evaluationId) {
      setResearchSelection(next.evaluationId);
      go("evaluations");
    } else if (next.kind === "plan-evaluation" && next.runId) {
      go("evaluations", `plan~${next.runId}`);
    } else if (next.kind === "configure-run") {
      if (next.runId) void action(async () => reuse(await request<Run>(`/runs/${next.runId}`)));
      else if (next.strategyId) configure(next.strategyId);
    } else if (["inspect-run", "review-readiness"].includes(next.kind) && next.runId) {
      const run = state?.runs.find(candidate => candidate.id === next.runId);
      if (run) void action(() => inspect(run));
    } else if (next.kind === "open-portfolio") go("portfolio");
    else go("scripts", "library");
  }

  return {
    action,
    activeRuns,
    addRunToPortfolio,
    archiveRuns,
    archivedRuns,
    archiveView,
    stageAction,
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
    portfolioPickerOpen,
    planCombos,
    planDatasets,
    planTimeframes,
    presetName,
    preview,
    refresh,
    refreshAll,
    researchSelection,
    restoreRuns,
    restoreRunConfiguration,
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
    setPortfolioPickerOpen,
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
