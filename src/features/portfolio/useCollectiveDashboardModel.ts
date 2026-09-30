import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  DEFAULT_PORTFOLIO_CAPITAL,
  defaultPolicy,
  type CollectiveCatalog,
  type GatePolicy,
} from "../../../shared/ts/portfolio.ts";
import { defaultSizing } from "../../../shared/ts/riskSizing.ts";
import { href } from "../../app/navigation";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import {
  COMBINATIONS_KEY,
  downloadFile as download,
  PREVIOUS_SETTINGS_KEY,
  readCollectiveSettings as saved,
  readSavedCombinations as savedCombinations,
  SETTINGS_KEY,
  type CollectiveSettings as Settings,
  type SavedCombination,
} from "./collectiveViewModel";
import {
  calculateCollectiveResult,
  collectiveTestedWindow,
  filterCollectiveItems,
  hasLatestEsNqWindow,
  latestEsNqItems,
  selectedCollectiveItems,
  summarizeCollectiveResult,
} from "../../../shared/ts/collective.ts";
import { useCollectiveSeries } from "./useCollectiveSeries";

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

export function useCollectiveDashboardModel({
  refreshKey,
  view,
}: {
  refreshKey: number;
  view: string;
}) {
  const [initial] = useState(saved);
  const initialized = useRef(Boolean(initial));
  const latestLinkApplied = useRef(false);
  const [previousSettings, setPreviousSettings] = useState(() =>
    saved(PREVIOUS_SETTINGS_KEY),
  );
  const [savedBooks, setSavedBooks] = useState<SavedCombination[]>(savedCombinations);
  const [savedBookName, setSavedBookName] = useState("");
  const [catalog, setCatalog] = useState<CollectiveCatalog | null>(null);
  const [error, setError] = useState("");
  const [settings, setSettings] = useState<Settings>(initial || defaultSettings);
  const [refreshing, setRefreshing] = useState(false);
  const [manualBook, setManualBook] = useState<string | null>(null);
  const [manualTime, setManualTime] = useState("");
  const [manualAction, setManualAction] = useState("pause");
  const [manualReason, setManualReason] = useState("");
  const [manualError, setManualError] = useState("");
  const [filter, setFilter] = useState("working");
  const [markets, setMarkets] = useState<string[]>([]);
  const [timeframe, setTimeframe] = useState("all");
  const [search, setSearch] = useState("");
  const [month, setMonth] = useState(settings.end.slice(0, 7));
  const [day, setDay] = useState("");
  const [chartMode, setChartMode] = useState("cumulative");
  const [reload, setReload] = useState(0);
  const [pickerOpen, setPickerOpen] = useState(view === "strategies");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState<boolean | null>(null);

  const ids = useMemo(
    () =>
      Object.entries(settings.copies)
        .filter(([, copies]) => copies > 0)
        .map(([id]) => id)
        .sort()
        .join(","),
    [settings.copies],
  );
  const { histories, setHistories, loading, setLoading } = useCollectiveSeries(
    catalog,
    ids,
    setError,
  );

  useEffect(() => {
    // The legacy #collective-strategies link opens the picker.
    if (view === "strategies") {
      setPickerOpen(true);
      window.history.replaceState(null, "", href("portfolio"));
    }
  }, [view]);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/workbench/collective", { signal: controller.signal })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        return data as CollectiveCatalog;
      })
      .then((data) => {
        setCatalog({
          ...data,
          items: data.items.map((item) => ({
            ...item,
            name: strategyTitle(item.name),
          })),
        });
        setError(data.evidence_error || "");
        setHistories([]);
        const seedDefaults = !initialized.current;
        initialized.current = true;
        setSettings((current) => ({
          ...current,
          copies: Object.keys(current.copies).length
            ? Object.fromEntries(
                Object.entries(current.copies).filter(([id]) =>
                  data.items.some((item) => item.id === id),
                ),
              )
            : seedDefaults
              ? Object.fromEntries(
                  data.items
                    .filter((item) => item.working)
                    .map((item) => [item.id, 1]),
                )
              : current.copies,
        }));
      })
      .catch((fetchError) => {
        if (fetchError.name !== "AbortError") setError(String(fetchError));
      });
    return () => controller.abort();
  }, [refreshKey, reload, initial, setHistories]);

  useEffect(() => {
    // Persist only after the catalog has seeded or reconciled the selection.
    if (!initialized.current) return;
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch {
      /* Storage may be unavailable; the current combination still works. */
    }
  }, [settings]);

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
  const visible = useMemo(
    () =>
      filterCollectiveItems(catalog, {
        milestone: filter,
        markets,
        timeframe,
        search,
      }),
    [catalog, filter, markets, timeframe, search],
  );
  const hidden = useMemo(
    () => selected.filter((item) => !visible.some((candidate) => candidate.id === item.id)),
    [selected, visible],
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
    () => calculateCollectiveResult(selected, histories, settings),
    [selected, histories, settings],
  );
  const result = computed.value;
  const testedWindow = useMemo(
    () => collectiveTestedWindow(selected, histories),
    [selected, histories],
  );
  const { totals, annual } = useMemo(
    () => summarizeCollectiveResult(result),
    [result],
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

  const refreshEvidence = useCallback(async () => {
    setRefreshing(true);
    setError("");
    try {
      const response = await fetch("/api/workbench/collective/refresh", {
        method: "POST",
      });
      if (!response.ok) throw new Error("Could not start evidence refresh");
      let done = false;
      while (!done) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const status = await (
          await fetch("/api/workbench/collective/status")
        ).json();
        if (!status.running) {
          done = true;
          if (status.error || status.evidence_error) {
            throw new Error(status.error || status.evidence_error);
          }
        }
      }
      setReload((current) => current + 1);
    } catch (refreshError) {
      setError(String(refreshError));
    } finally {
      setRefreshing(false);
    }
  }, []);

  const saveCombination = useCallback(() => {
    const name = savedBookName.trim() || `Combination ${savedBooks.length + 1}`;
    const record: SavedCombination = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name,
      saved_at: new Date().toISOString(),
      settings,
    };
    setSavedBooks((current) =>
      [record, ...current.filter((item) => item.name !== name)].slice(0, 12),
    );
    setSavedBookName("");
  }, [savedBookName, savedBooks.length, settings]);

  const loadCombination = useCallback(
    (id: string | null) => {
      const record = savedBooks.find((item) => item.id === id);
      if (!record) return;
      setLoading(true);
      setSettings(record.settings);
      setMonth(record.settings.end.slice(0, 7));
      setDay("");
    },
    [savedBooks, setLoading],
  );

  const viewLatestEsNq = useCallback(() => {
    if (!latestEsNqAvailable) return;
    if (!previousSettings) {
      setPreviousSettings(settings);
      try {
        localStorage.setItem(PREVIOUS_SETTINGS_KEY, JSON.stringify(settings));
      } catch {
        /* The restore action still works in this session. */
      }
    }
    const start =
      settings.start >= latestEsNqWindow.start &&
      settings.start <= latestEsNqWindow.end
        ? settings.start
        : latestEsNqWindow.start;
    setLoading(true);
    setSettings((current) => ({
      ...current,
      copies: Object.fromEntries(latestEsNq.map((item) => [item.id, 1])),
      start,
      end: latestEsNqWindow.end,
    }));
    setMonth(latestEsNqWindow.end.slice(0, 7));
    setDay("");
  }, [
    latestEsNq,
    latestEsNqAvailable,
    latestEsNqWindow.end,
    latestEsNqWindow.start,
    previousSettings,
    settings,
    setLoading,
  ]);

  const restorePreviousCombination = useCallback(() => {
    if (!previousSettings) return;
    setLoading(true);
    setSettings(previousSettings);
    setMonth(previousSettings.end.slice(0, 7));
    setDay("");
    setPreviousSettings(null);
    try {
      localStorage.removeItem(PREVIOUS_SETTINGS_KEY);
    } catch {
      /* The restored settings still work in this session. */
    }
  }, [previousSettings, setLoading]);

  useEffect(() => {
    if (!catalog || latestLinkApplied.current) return;
    if (
      new URLSearchParams(window.location.search).get("portfolio") !==
      "latest-es-nq"
    ) {
      return;
    }
    if (!latestEsNqAvailable) return;
    latestLinkApplied.current = true;
    viewLatestEsNq();
    const url = new URL(window.location.href);
    url.searchParams.delete("portfolio");
    window.history.replaceState(
      window.history.state,
      "",
      url.pathname + url.search + url.hash,
    );
  }, [catalog, latestEsNqAvailable, viewLatestEsNq]);

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
    choose,
    computed,
    day,
    error,
    exportCombination,
    exportDaily,
    filter,
    hidden,
    histories,
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
    previousSettings,
    railCollapsed,
    refreshEvidence,
    refreshing,
    restorePreviousCombination,
    result,
    saveCombination,
    savedBookName,
    savedBooks,
    search,
    selected,
    selectedDay,
    setChartMode,
    setDay,
    setFilter,
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
    timeframe,
    totals,
    useCommon,
    viewLatestEsNq,
    visible,
    volatility,
  };
}

export type CollectiveDashboardModel = ReturnType<
  typeof useCollectiveDashboardModel
>;
