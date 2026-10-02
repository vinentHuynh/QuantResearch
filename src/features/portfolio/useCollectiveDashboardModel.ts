import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  DEFAULT_PORTFOLIO_CAPITAL,
  defaultPolicy,
  type CollectiveCatalog,
  type GatePolicy,
} from "../../../shared/ts/portfolio.ts";
import { defaultSizing } from "../../../shared/ts/riskSizing.ts";
import {
  portfolioPeriodComponents,
  portfolioPeriodMetrics,
  portfolioPeriodPoints,
  portfolioPeriodStart,
  type PortfolioPnlPeriod,
} from "../../../shared/ts/portfolioPeriods.ts";
import { href } from "../../app/navigation";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import {
  COMBINATIONS_KEY,
  alignCommonStart,
  downloadFile as download,
  firstAvailableSavedCombination,
  followCommonStartForSavedSettings,
  followLatestForSavedSettings,
  initializeCollectiveSettings,
  readCollectiveSettings as saved,
  readSavedCombinations as savedCombinations,
  SETTINGS_KEY,
  type CollectiveSettings as Settings,
  type PortfolioTracking,
  type SavedCombination,
} from "./collectiveViewModel";
import {
  calculateCollectiveResult,
  collectiveTestedWindow,
  hasLatestEsNqWindow,
  itemsForLoadedSeries,
  latestEsNqItems,
  selectedCollectiveItems,
  summarizeCollectiveResult,
} from "../../../shared/ts/collective.ts";
import { useCollectiveSeries } from "./useCollectiveSeries";
import type { WorkbenchState } from "../workspace/workbenchModel";
import { portfolioStageStatus, strategyStageStatuses } from "../../../shared/ts/stageStatus.ts";
import { exactPortfolioItemForRun, isPortfolioBaselineRun, selectPortfolioHistory } from "../../../shared/ts/portfolioScriptCandidates.ts";

const defaultSettings = (): Settings => ({
  capital: DEFAULT_PORTFOLIO_CAPITAL,
  copies: {},
  start: "2024-01-01",
  end: "2026-08-31",
  basis: "marked",
  policy: {
    ...defaultPolicy,
    mode: "fixed",
    volCap: 1,
    sizing: { ...defaultSizing },
  },
});

export type ExactImportState = {
  runId?: string;
  phase: "idle" | "importing" | "verifying" | "error";
  error?: string;
};

// React StrictMode remounts effects in development. Share only requests that
// are still running so the initial portfolio catalog is fetched once.
const catalogRequests = new Map<string, Promise<CollectiveCatalog>>();

function loadCatalog(key: string): Promise<CollectiveCatalog> {
  const existing = catalogRequests.get(key);
  if (existing) return existing;
  const pending = fetch("/api/workbench/collective")
    .then(async (response) => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      return data as CollectiveCatalog;
    });
  catalogRequests.set(key, pending);
  void pending.then(
    () => { if (catalogRequests.get(key) === pending) catalogRequests.delete(key); },
    () => { if (catalogRequests.get(key) === pending) catalogRequests.delete(key); },
  );
  return pending;
}

export function useCollectiveDashboardModel({
  researchState,
  refreshKey,
  view,
  pickerOpen,
  setPickerOpen,
}: {
  researchState?: WorkbenchState | null;
  refreshKey: number;
  view: string;
  pickerOpen: boolean;
  setPickerOpen: Dispatch<SetStateAction<boolean>>;
}) {
  const [initial] = useState(saved);
  const initialized = useRef(false);
  const [selectionReady, setSelectionReady] = useState(false);
  const [trackingLoaded, setTrackingLoaded] = useState(false);
  const [tracking, setTracking] = useState<PortfolioTracking | null>(null);
  const serverSelection = useRef<string | null>(null);
  const desiredSelection = useRef<string[]>([]);
  const selectionSyncBusy = useRef(false);
  const catalogRef = useRef<CollectiveCatalog | null>(null);
  const pendingCatalogRefresh = useRef("");
  const [savedBooks, setSavedBooks] = useState<SavedCombination[]>(savedCombinations);
  const [savedBookName, setSavedBookName] = useState("");
  const [selectedSavedBookId, setSelectedSavedBookId] = useState<string | null>(null);
  const [baseCatalog, setCatalog] = useState<CollectiveCatalog | null>(null);
  const catalog = useMemo(() => {
    if (!baseCatalog || !researchState) return baseCatalog;
    const statuses = strategyStageStatuses(researchState.strategies, researchState.runs, researchState.evaluations || []);
    return { ...baseCatalog, items: baseCatalog.items.map(item => ({ ...item, research_status: portfolioStageStatus(item, researchState.runs, statuses) })) };
  }, [baseCatalog, researchState]);
  catalogRef.current = baseCatalog;
  const [error, setError] = useState("");
  const [settings, setSettings] = useState<Settings>(initial || defaultSettings);
  const initialSettings = useRef(settings);
  const [refreshing, setRefreshing] = useState(false);
  const [importState, setImportState] = useState<ExactImportState>({ phase: "idle" });
  const [manualBook, setManualBook] = useState<string | null>(null);
  const [manualTime, setManualTime] = useState("");
  const [manualAction, setManualAction] = useState("pause");
  const [manualReason, setManualReason] = useState("");
  const [manualError, setManualError] = useState("");
  const [markets, setMarkets] = useState<string[]>([]);
  const [timeframe, setTimeframe] = useState("all");
  const [search, setSearch] = useState("");
  const [focusRunId, setFocusRunId] = useState<string | undefined>();
  const pendingExactRun = useRef<{ runId: string; strategyId: string } | null>(null);
  const handledRunRoute = useRef<string | null>(null);
  const runsRef = useRef(researchState?.runs || []);
  runsRef.current = researchState?.runs || [];
  const [month, setMonth] = useState(settings.end.slice(0, 7));
  const [day, setDay] = useState("");
  const [chartMode, setChartMode] = useState("cumulative");
  const [pnlPeriod, setPnlPeriod] = useState<PortfolioPnlPeriod>("all");
  const [reload, setReload] = useState(0);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState<boolean | null>(null);

  const applyTracking = useCallback((data: PortfolioTracking) => {
    serverSelection.current = [...data.selection].sort().join(",");
    setTracking(data);
    const currentCatalog = catalogRef.current;
    if (!currentCatalog) return;
    const completed = Object.entries(data.items)
      .filter(([id, state]) =>
        state.status === "up-to-date" &&
        Boolean(state.simulated_through) &&
        state.simulated_through! > (currentCatalog.items.find((item) => item.id === id)?.end || ""),
      )
      .map(([id, state]) => `${id}:${state.simulated_through}`)
      .sort()
      .join(",");
    if (completed && completed !== pendingCatalogRefresh.current) {
      pendingCatalogRefresh.current = completed;
      setReload((current) => current + 1);
    } else if (!completed) {
      pendingCatalogRefresh.current = "";
    }
  }, []);

  const pollTracking = useCallback(async (signal?: AbortSignal) => {
    const response = await fetch("/api/workbench/collective/tracking", { signal, cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load portfolio tracking");
    if (!signal?.aborted) applyTracking(data as PortfolioTracking);
  }, [applyTracking]);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const poll = async () => {
      try {
        await pollTracking(controller.signal);
        if (active) setTrackingLoaded(true);
      } catch (trackingError) {
        if (active && !(trackingError instanceof DOMException && trackingError.name === "AbortError"))
          setError(String(trackingError));
      }
    };
    void poll();
    const interval = window.setInterval(() => void poll(), 5000);
    return () => { active = false; controller.abort(); window.clearInterval(interval); };
  }, [pollTracking]);

  const ids = useMemo(
    () =>
      Object.entries(settings.copies)
        .filter(([id, copies]) => copies > 0 && catalog?.items.some(item => item.id === id))
        .map(([id]) => id)
        .sort()
        .join(","),
    [settings.copies, catalog],
  );
  const { histories, seriesCatalog, loading, setLoading } = useCollectiveSeries(
    baseCatalog,
    ids,
    setError,
  );

  useEffect(() => {
    // The legacy #collective-strategies link opens the picker.
    if (view === "strategies") {
      setPickerOpen(true);
      window.history.replaceState(null, "", href("portfolio"));
    }
  }, [view, setPickerOpen]);

  useEffect(() => {
    let active = true;
    loadCatalog(`${refreshKey}:${reload}`)
      .then((data) => {
        if (!active) return;
        const pending = pendingExactRun.current;
        const pendingRun = pending && runsRef.current.find(run => run.id === pending.runId);
        const exact = pendingRun ? exactPortfolioItemForRun(data, pendingRun) : undefined;
        if (pending) pendingExactRun.current = null;
        setCatalog({
          ...data,
          items: data.items.map((item) => ({
            ...item,
            name: strategyTitle(item.name),
          })),
        });
        const importError = pending && !exact
          ? "The exact verified history is unavailable after import. No other run was selected."
          : "";
        setError(importError || data.evidence_error || "");
        if (pending) setImportState(importError
          ? { runId: pending.runId, phase: "error", error: importError }
          : { phase: "idle" });
        if (pending && exact && pendingRun) {
          setSettings((current) => ({
            ...current,
            copies: selectPortfolioHistory(current.copies, data, runsRef.current, exact, pending.strategyId),
          }));
        }
      })
      .catch((fetchError) => {
        if (!active) return;
        const message = fetchError instanceof Error ? fetchError.message : String(fetchError);
        setError(message);
        const pending = pendingExactRun.current;
        if (pending) {
          pendingExactRun.current = null;
          setImportState({ runId: pending.runId, phase: "error", error: message });
        }
      });
    return () => { active = false; };
  }, [refreshKey, reload]);

  useEffect(() => {
    if (!baseCatalog || !trackingLoaded || initialized.current) return;
    initialized.current = true;
    const savedDefault = settings === initialSettings.current
      ? firstAvailableSavedCombination(savedBooks, baseCatalog)
      : undefined;
    setSelectedSavedBookId(savedDefault?.id ?? null);
    setSettings((current) => {
      // A direct Add action can select a run while tracking is still loading.
      const defaultForCurrent = current === initialSettings.current ? savedDefault : undefined;
      return initializeCollectiveSettings(
        defaultForCurrent?.settings || current,
        baseCatalog,
        Boolean(defaultForCurrent || initial) || Object.keys(current.copies).length > 0,
        tracking?.selection || null,
      );
    });
    setSelectionReady(true);
  }, [baseCatalog, initial, savedBooks, settings, tracking, trackingLoaded]);

  const syncSelection = useCallback(async () => {
    if (selectionSyncBusy.current) return;
    selectionSyncBusy.current = true;
    try {
      while (desiredSelection.current.join(",") !== serverSelection.current) {
        const ids = [...desiredSelection.current];
        const response = await fetch("/api/workbench/collective/tracking", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Could not save active portfolio selection");
        if (!Array.isArray(data.selection) || [...data.selection].sort().join(",") !== ids.join(","))
          throw new Error("The server did not retain the active portfolio selection");
        applyTracking(data as PortfolioTracking);
      }
    } catch (syncError) {
      setError(String(syncError));
    } finally {
      selectionSyncBusy.current = false;
    }
  }, [applyTracking]);

  useEffect(() => {
    if (!selectionReady) return;
    desiredSelection.current = ids ? ids.split(",") : [];
    void syncSelection();
  }, [ids, selectionReady, syncSelection]);

  useEffect(() => {
    // Persist only after the catalog has seeded or reconciled the selection.
    if (!selectionReady) return;
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch {
      /* Storage may be unavailable; the current combination still works. */
    }
  }, [selectionReady, settings]);

  useEffect(() => {
    setMonth(settings.end.slice(0, 7));
  }, [settings.end]);

  useEffect(() => {
    try {
      localStorage.setItem(COMBINATIONS_KEY, JSON.stringify(savedBooks));
    } catch {
      /* Saved combinations are optional convenience state. */
    }
  }, [savedBooks]);

  const selected = useMemo(
    () => selectedCollectiveItems(catalog, settings.copies),
    [catalog, settings.copies],
  );
  const calculationSelected = useMemo(
    () => itemsForLoadedSeries(selected, seriesCatalog),
    [selected, seriesCatalog],
  );
  const latestEsNq = useMemo(() => latestEsNqItems(catalog), [catalog]);
  const latestEsNqState = useMemo(
    () => hasLatestEsNqWindow(latestEsNq),
    [latestEsNq],
  );
  const latestEsNqWindow = latestEsNqState.window;
  const latestEsNqAvailable = latestEsNqState.available;
  const showingLatestEsNq =
    latestEsNqAvailable &&
    selected.length === latestEsNq.length &&
    latestEsNq.every((item) => settings.copies[item.id] > 0) &&
    settings.end === latestEsNqWindow.end;
  const computed = useMemo(
    () => calculateCollectiveResult(calculationSelected, histories, settings),
    [calculationSelected, histories, settings],
  );
  const result = computed.value;
  const periodStart = portfolioPeriodStart(pnlPeriod, settings.start, settings.end);
  const periodPoints = useMemo(
    () => portfolioPeriodPoints(result?.points || [], pnlPeriod, settings.start, settings.end),
    [result, pnlPeriod, settings.start, settings.end],
  );
  const periodPnl = useMemo(
    () => periodPoints.reduce((total, point) => total + point.pnl, 0),
    [periodPoints],
  );
  const periodMetrics = useMemo(
    () => result ? portfolioPeriodMetrics(result, periodPoints) : null,
    [result, periodPoints],
  );
  const periodComponents = useMemo(
    () => result ? portfolioPeriodComponents(result, periodPoints) : [],
    [result, periodPoints],
  );
  const testedWindow = useMemo(
    () => collectiveTestedWindow(selected, histories),
    [selected, histories],
  );
  const verifiedWindow = useMemo(
    () => selected.length && selected.every((item) => histories.some((history) => history.id === item.id))
      ? collectiveTestedWindow(selected, histories)
      : { start: "", end: "" },
    [selected, histories],
  );
  const followLatestEnd = verifiedWindow.end;
  useEffect(() => {
    if (!selectionReady || !settings.followCommonStart || !verifiedWindow.start ||
        settings.start === verifiedWindow.start) return;
    setSettings((current) => alignCommonStart(current, verifiedWindow));
  }, [selectionReady, settings.followCommonStart, settings.start, verifiedWindow]);
  useEffect(() => {
    if (!selectionReady || !settings.followLatest || !followLatestEnd || settings.end === followLatestEnd) return;
    // Use series coverage here: catalog metadata may be newer while the
    // verified series request is still in flight.
    setSettings((current) => current.followLatest && current.end !== followLatestEnd
      ? { ...current, end: followLatestEnd }
      : current);
  }, [followLatestEnd, selectionReady, settings.end, settings.followLatest]);
  const { totals, annual } = useMemo(
    () => summarizeCollectiveResult(result ? { ...result, points: periodPoints } : null),
    [result, periodPoints],
  );
  const selectedDay = result?.points.find((point) => point.date === day);
  const marketCount = new Set(selected.map((item) => item.symbol)).size;
  const accountingLabel =
    settings.basis === "marked" ? "daily marked P&L" : "closed-trade P&L";
  const volatility = ["volatility", "portfolio", "fixed"].includes(
    settings.policy.mode,
  );

  const choose = useCallback(
    (copies: Record<string, number>) => {
      setLoading(true);
      setSettings((current) => ({ ...current, copies }));
    },
    [setLoading],
  );

  const policy = useCallback((next: Partial<GatePolicy>) => {
    setSettings((current) => ({
      ...current,
      basis: next.enabled ? "closed" : current.basis,
      policy: { ...current.policy, ...next },
    }));
  }, []);

  const refreshEvidence = useCallback(async (runId?: string) => {
    setRefreshing(true);
    setError("");
    if (runId) setImportState({ runId, phase: "importing" });
    try {
      let exactRequest: { runId: string; strategyId: string } | null = null;
      if (runId) {
        const run = runsRef.current.find(candidate => candidate.id === runId);
        if (!run || run.status !== "Succeeded" || !run.result || !isPortfolioBaselineRun(run))
          throw new Error("Choose a completed baseline run to import into the portfolio.");
        exactRequest = { runId, strategyId: run.input.strategy.id };
      }
      const response = await fetch(runId ? "/api/workbench/collective/import" : "/api/workbench/collective/refresh", {
        method: "POST",
        ...(runId ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ runId }) } : {}),
      });
      let status = await response.json().catch(() => ({}));
      if (!response.ok || status.error || status.evidence_error)
        throw new Error(status.error || status.evidence_error || "Could not start evidence refresh");
      while (status.running) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const poll = await fetch("/api/workbench/collective/status");
        status = await poll.json().catch(() => ({}));
        if (!poll.ok || status.error || status.evidence_error)
          throw new Error(status.error || status.evidence_error || "Could not check evidence import");
      }
      pendingExactRun.current = exactRequest;
      if (runId) setImportState({ runId, phase: "verifying" });
      setReload((current) => current + 1);
    } catch (refreshError) {
      if (runId && pendingExactRun.current?.runId === runId) pendingExactRun.current = null;
      const message = refreshError instanceof Error ? refreshError.message : String(refreshError);
      setError(message);
      if (runId) setImportState({ runId, phase: "error", error: message });
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!view.startsWith("add~") || !baseCatalog || !researchState) return;
    const runId = view.slice(4);
    if (handledRunRoute.current === runId) return;
    handledRunRoute.current = runId;
    window.history.replaceState(null, "", href("portfolio"));
    setPickerOpen(true);
    setMarkets([]);
    setTimeframe("all");
    setSearch(runId);
    setFocusRunId(runId);
    const run = researchState.runs.find(candidate => candidate.id === runId);
    if (!run || run.status !== "Succeeded" || !run.result || !isPortfolioBaselineRun(run)) {
      const message = "The requested saved run is unavailable or is not a completed baseline.";
      setError(message);
      setImportState({ runId, phase: "error", error: message });
      return;
    }
    const exact = exactPortfolioItemForRun(baseCatalog, run);
    if (exact) {
      setImportState({ phase: "idle" });
      setError("");
      setSettings(current => ({ ...current,
        copies: selectPortfolioHistory(current.copies, baseCatalog, researchState.runs, exact, run.input.strategy.id),
      }));
    } else {
      void refreshEvidence(runId);
    }
  }, [view, baseCatalog, researchState, refreshEvidence, setPickerOpen]);

  const saveCombination = useCallback(() => {
    const selectedRecord = savedBooks.find((item) => item.id === selectedSavedBookId);
    const name = selectedRecord?.name || savedBookName.trim() || `Combination ${savedBooks.length + 1}`;
    const record: SavedCombination = {
      id: selectedRecord?.id || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name,
      saved_at: new Date().toISOString(),
      settings,
    };
    setSavedBooks((current) =>
      [record, ...current.filter((item) => item.id !== record.id && item.name !== name)].slice(0, 12),
    );
    setSelectedSavedBookId(record.id);
    setSavedBookName("");
  }, [savedBookName, savedBooks, selectedSavedBookId, settings]);

  const deleteCombination = useCallback(() => {
    if (!selectedSavedBookId) return;
    setSavedBooks((current) => current.filter((item) => item.id !== selectedSavedBookId));
    setSelectedSavedBookId(null);
    setSavedBookName("");
  }, [selectedSavedBookId]);

  const loadCombination = useCallback(
    (id: string | null) => {
      if (id === null) {
        setSelectedSavedBookId(null);
        setSavedBookName("");
        return;
      }
      const record = savedBooks.find((item) => item.id === id);
      if (!record) return;
      const common = collectiveTestedWindow(
        selectedCollectiveItems(catalog, record.settings.copies),
        histories,
      );
      const followLatest = followLatestForSavedSettings(record.settings, common.end);
      const followCommonStart = followCommonStartForSavedSettings(record.settings, common);
      const next = alignCommonStart({
        ...record.settings,
        followLatest,
        followCommonStart,
        end: followLatest && common.end ? common.end : record.settings.end,
      }, common);
      setSelectedSavedBookId(record.id);
      setSavedBookName("");
      setLoading(true);
      setSettings(next);
      setMonth(next.end.slice(0, 7));
      setDay("");
    },
    [catalog, histories, savedBooks, setLoading],
  );

  const retryTracking = useCallback(async (id: string) => {
    try {
      const response = await fetch(`/api/workbench/collective/tracking/${encodeURIComponent(id)}/retry`, {
        method: "POST",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Could not retry portfolio update");
      await pollTracking();
    } catch (retryError) {
      setError(String(retryError));
    }
  }, [pollTracking]);

  const useCommon = useCallback(() => {
    if (testedWindow.start && testedWindow.end && testedWindow.start <= testedWindow.end) {
      setSettings((current) => ({ ...current, ...testedWindow }));
      setMonth(testedWindow.end.slice(0, 7));
    }
  }, [testedWindow]);

  const exportDaily = useCallback(() => {
    if (!result) return;
    download(
      "combined-daily-pnl.csv",
      [
        "date,pnl,always_on_pnl,cumulative_pnl,always_on_cumulative_pnl,equity,drawdown,closed_trades,starting_capital",
        ...result.points.map((point) =>
          [
            point.date,
            point.pnl,
            point.baseline,
            point.cumulative,
            point.baselineCumulative,
            point.equity,
            point.drawdown,
            point.trades,
            result.capital,
          ].join(","),
        ),
      ].join("\n"),
    );
  }, [result]);

  const exportCombination = useCallback(() => {
    download(
      "strategy-combination.json",
      JSON.stringify(
        {
          version: 2,
          capital_model: "shared",
          catalog_at: catalog?.generated_at,
          replay_version: 4,
          ...settings,
          capital: settings.capital,
          selected: selected.map((item) => ({
            id: item.id,
            name: item.name,
            key: item.key,
            source: item.source,
            checksum: item.checksum,
          })),
          results: result
            ? {
                pnl: result.net,
                max_drawdown: result.maxDrawdown,
                capital: result.capital,
                benchmarks: result.benchmarks,
                execution: result.execution,
                correlations: result.correlations,
              }
            : null,
        },
        null,
        2,
      ),
      "application/json",
    );
  }, [catalog?.generated_at, result, selected, settings]);

  return {
    accountingLabel,
    annual,
    catalog,
    chartMode,
    pnlPeriod,
    periodStart,
    periodPoints,
    periodPnl,
    periodMetrics,
    periodComponents,
    choose,
    computed,
    day,
    deleteCombination,
    error,
    exportCombination,
    exportDaily,
    focusRunId,
    followLatestEnd,
    histories,
    importState,
    latestEsNq,
    latestEsNqAvailable,
    latestEsNqWindow,
    loadCombination,
    loading,
    manualAction,
    manualBook,
    manualError,
    manualReason,
    manualTime,
    marketCount,
    markets,
    month,
    pickerOpen,
    policy,
    railCollapsed,
    refreshEvidence,
    refreshing,
    retryTracking,
    result,
    saveCombination,
    savedBookName,
    savedBooks,
    selectedSavedBookId,
    search,
    selected,
    selectedDay,
    setChartMode,
    setPnlPeriod,
    setDay,
    setManualAction,
    setManualBook,
    setManualError,
    setManualReason,
    setManualTime,
    setMarkets,
    setMonth,
    setPickerOpen,
    setRailCollapsed,
    setSavedBookName,
    setSearch,
    setSettings,
    setSheetOpen,
    setTimeframe,
    settings,
    sheetOpen,
    showingLatestEsNq,
    testedWindow,
    tracking,
    timeframe,
    totals,
    useCommon,
    volatility,
  };
}

export type CollectiveDashboardModel = ReturnType<
  typeof useCollectiveDashboardModel
>;
