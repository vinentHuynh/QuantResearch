import {
  DEFAULT_PORTFOLIO_CAPITAL,
  defaultPolicy,
  type CollectiveCatalog,
  type CollectiveItem,
  type CollectiveSeries,
  type Dependence,
  type GatePolicy,
  type GateState,
  type Coverage,
} from "../../../shared/ts/portfolio.ts";
import { defaultSizing } from "../../../shared/ts/riskSizing.ts";
import { collectiveTestedWindow, selectedCollectiveItems, withLatestEsNq, type PortfolioResult } from "../../../shared/ts/collective.ts";

export const formatMoney = (value: number) =>
  value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });

export const formatCompactMoney = (value: number) =>
  value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  });

export const formatPercent = (value: number) => `${(value * 100).toFixed(2)}%`;
export const valueTone = (value: number) => (value < 0 ? "#b3412e" : "#16634f");
export const signedClass = (value: number) => (value < 0 ? "wb-loss" : "wb-gain");

export function strategyReturnAndDrawdownPercent(result: PortfolioResult, id: string) {
  const component = result.components.find((entry) => entry.id === id);
  if (!component) return null;
  let equity = result.capital;
  let peak = equity;
  let drawdownPercent = 0;
  for (const point of result.points) {
    equity += point.byStrategy[id] || 0;
    peak = Math.max(peak, equity);
    drawdownPercent = Math.max(drawdownPercent, 1 - equity / peak);
  }
  return {
    pnlPercent: component.pnl / result.capital,
    drawdownPercent,
  };
}

export const gateStateColor: Record<GateState, string> = {
  Paused: "orange",
  Active: "teal",
  Reduced: "yellow",
  Raised: "blue",
};

export const dependenceVerdicts: Record<Dependence["verdict"], [string, string]> = {
  cluster: ["Clustering detected in sample", "teal"],
  alternate: ["Alternation detected in sample", "red"],
  none: ["No clustering detected", "gray"],
  insufficient: ["Under 30 trades", "gray"],
};

export const dependenceVerdictCopy: Record<Dependence["verdict"], [string, string]> = {
  cluster: [
    "Losses cluster in this book",
    "This sample shows outcome persistence. It is a reason to investigate a pause rule, not proof that the rule improves future results. Compare the replay below.",
  ],
  alternate: [
    "Outcomes alternate in this sample",
    "The sample shows alternation, which can make loss-triggered pauses skip recoveries. Check the actual replay and its skipped trades below.",
  ],
  none: [
    "No loss clustering detected in this sample",
    "This test did not detect clustering. That does not prove independence or tell us whether a pause rule will work on future data.",
  ],
  insufficient: [
    "Too few trades to judge this book",
    "Fewer than 30 trades are available, so the runs test is not informative.",
  ],
};

export const collectiveViews = ["overview", "calendar", "contributions", "pause"] as const;
export type CollectiveViewName = (typeof collectiveViews)[number];

export type CollectiveSettings = {
  capital: number;
  copies: Record<string, number>;
  start: string;
  end: string;
  /** Undefined only while an older saved combination awaits migration. */
  followCommonStart?: boolean;
  /** Undefined only while an older saved combination awaits migration. */
  followLatest?: boolean;
  basis: "marked" | "closed";
  policy: GatePolicy;
};

export type PortfolioTrackingItem = {
  status: string;
  dataset_last?: string;
  target_end?: string;
  simulated_through?: string;
  error?: string;
  run_id?: string;
};

export type PortfolioTracking = {
  selection: string[];
  items: Record<string, PortfolioTrackingItem>;
};

const trackingStatusLabels: Record<string, string> = {
  "up-to-date": "Up to date",
  "waiting-for-data": "Waiting for complete data",
  queued: "Update queued",
  running: "Updating",
  publishing: "Verifying update",
  failed: "Update failed",
  "manual-update-required": "Manual update required",
};

/** Keep immutable research history distinct from a replay that merely needs
 * operator attention. A failed frozen configuration must not look as though
 * extending its dates could repair the research result. */
export function portfolioUpdatePresentation(
  item: CollectiveItem,
  update?: PortfolioTrackingItem,
) {
  if (!update) return { label: "Checking update", attention: false, title: undefined };
  if (update.status === "manual-update-required" && item.research_status?.kind === "failed-checks")
    return {
      label: "Failed checks · history retained",
      attention: true,
      title: item.research_status.finding || update.error,
    };
  if (update.status === "manual-update-required" &&
      (item.source === "Pinned workbench" || item.key.includes("__pinned__")))
    return {
      label: "Pinned history · not auto-updated",
      attention: true,
      title: "This exact saved history is immutable. Choose a current replayable configuration to extend it.",
    };
  return {
    label: trackingStatusLabels[update.status] || update.status,
    attention: update.status === "failed" || update.status === "manual-update-required",
    title: update.error,
  };
}

/** Explain an end-date coverage gap without changing a saved manual window. */
export function coverageEndExplanation(
  selected: CollectiveItem[],
  histories: CollectiveSeries[],
  settings: Pick<CollectiveSettings, "start" | "end" | "followLatest">,
  common: Coverage,
  tracking: PortfolioTracking | null,
): string | null {
  if (!selected.length || !common.start || !common.end ||
      settings.start < common.start || settings.start > common.end ||
      settings.end <= common.end) return null;

  const ends = selected.map((item) => {
    const coverage = histories.find((history) => history.id === item.id)?.coverage || item.coverage;
    return { item, end: coverage.map((span) => span.end).sort().at(-1) || "" };
  });
  const limiting = ends.filter(({ end }) => end === common.end);
  if (!limiting.length) return null;

  const names = limiting.slice(0, 2).map(({ item }) =>
    `${item.name} / ${item.symbol} / ${item.timeframe}`);
  const bookNames = names.join(" and ") +
    (limiting.length > 2 ? ` and ${limiting.length - 2} more` : "");
  const plural = limiting.length > 1;
  const dataDates = selected.map((item) => tracking?.items[item.id]?.dataset_last || "");
  const commonDataDay = dataDates.every(Boolean) ? dataDates.sort()[0] : "";
  const dataNote = commonDataDay && settings.end > commonDataDay
    ? ` The latest complete UTC data day shared by these books is ${commonDataDay}.`
    : "";
  const manual = limiting.every(({ item }) =>
    tracking?.items[item.id]?.status === "manual-update-required");
  const fixedHistory = manual && limiting.every(({ item }) =>
    item.research_status?.kind === "failed-checks" ||
      item.source === "Pinned workbench" || item.key.includes("__pinned__"));
  const manualNote = fixedHistory
    ? ` ${plural ? "These books are" : "This book is"} a fixed historical snapshot. Choose ${plural ? "current replayable configurations" : "a current replayable configuration"} to extend coverage.`
    : manual
    ? ` ${plural ? "These books require" : "This book requires"} a manual update to extend ${plural ? "their" : "its"} history.`
    : "";
  return `${settings.followLatest === false ? "Your manually set" : "The selected"} P&L end is ${settings.end}.` +
    dataNote + ` ${bookNames} ${plural ? "are" : "is"} simulated through ${common.end}, ` +
    `which limits the common tested window to ${common.end}.${manualNote} ` +
    "Apply the common tested window to see combined P&L now.";
}

export function followLatestForSavedSettings(settings: CollectiveSettings, commonEnd: string) {
  return typeof settings.followLatest === "boolean"
    ? settings.followLatest
    : Boolean(commonEnd) && settings.end === commonEnd;
}

export function followCommonStartForSavedSettings(settings: CollectiveSettings, common: Coverage) {
  if (typeof settings.followCommonStart === "boolean") return settings.followCommonStart;
  // An older saved start inside the tested window may have been chosen by hand.
  // A start outside it cannot produce combined P&L, so resume automatic alignment.
  return Boolean(common.start && common.end) &&
    (settings.start <= common.start || settings.start > common.end);
}

export function alignCommonStart(settings: CollectiveSettings, common: Coverage): CollectiveSettings {
  if (!settings.followCommonStart || !common.start || !common.end || common.start > common.end ||
      settings.start === common.start) return settings;
  return { ...settings, start: common.start };
}

export function initializeCollectiveSettings(
  current: CollectiveSettings,
  catalog: CollectiveCatalog,
  hasBrowserSettings: boolean,
  serverIds: string[] | null,
): CollectiveSettings {
  const validIds = new Set(catalog.items.map((item) => item.id));
  const latest = !hasBrowserSettings && serverIds === null ? withLatestEsNq(current, catalog) : null;
  const copies = hasBrowserSettings
    ? Object.fromEntries(Object.entries(current.copies).filter(([id]) => validIds.has(id)))
    : serverIds !== null
      ? Object.fromEntries(serverIds.filter((id) => validIds.has(id)).map((id) => [id, 1]))
      : latest?.copies || Object.fromEntries(catalog.items.filter((item) => item.working).map((item) => [item.id, 1]));
  const common = collectiveTestedWindow(selectedCollectiveItems(catalog, copies), []);
  const followLatest = hasBrowserSettings
    ? followLatestForSavedSettings(current, common.end)
    : true;
  const followCommonStart = hasBrowserSettings
    ? followCommonStartForSavedSettings(current, common)
    : true;
  return alignCommonStart({
    ...current,
    copies,
    followLatest,
    followCommonStart,
    start: latest?.start || current.start,
    end: followLatest && common.end ? common.end : current.end,
  }, common);
}

export type SavedCombination = {
  id: string;
  name: string;
  saved_at: string;
  settings: CollectiveSettings;
};

export function firstAvailableSavedCombination(
  savedBooks: SavedCombination[],
  catalog: CollectiveCatalog,
): SavedCombination | undefined {
  const availableIds = new Set(catalog.items.map((item) => item.id));
  return savedBooks.find((book) => {
    const selectedIds = Object.entries(book.settings.copies)
      .filter(([, copies]) => typeof copies === "number" && Number.isFinite(copies) && copies > 0)
      .map(([id]) => id);
    return selectedIds.length > 0 && selectedIds.every((id) => availableIds.has(id));
  });
}

export const SETTINGS_KEY = "quant-collective-v1";
export const COMBINATIONS_KEY = "quant-collective-combinations-v1";

export function readCollectiveSettings(key = SETTINGS_KEY): CollectiveSettings | null {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    if (!value || typeof value.copies !== "object" || !value.start || !value.end) return null;
    return {
      ...value,
      capital:
        typeof value.capital === "number" && Number.isFinite(value.capital) && value.capital > 0
          ? value.capital
          : DEFAULT_PORTFOLIO_CAPITAL,
      basis: value.basis === "closed" ? "closed" : "marked",
      policy: {
        ...defaultPolicy,
        ...value.policy,
        ...(value.policy?.mode === "volatility" && !value.policy?.sizing
          ? { sizing: { ...defaultSizing, estimator: "legacy" } }
          : {}),
      },
    };
  } catch {
    return null;
  }
}

export function readSavedCombinations(): SavedCombination[] {
  try {
    const value = JSON.parse(localStorage.getItem(COMBINATIONS_KEY) || "[]");
    if (!Array.isArray(value)) return [];
    return value.filter(
      (item) =>
        item &&
        typeof item.id === "string" &&
        typeof item.name === "string" &&
        item.settings?.copies,
    );
  } catch {
    return [];
  }
}

export function downloadFile(filename: string, content: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export const csvCell = (value: unknown) => `"${String(value).replaceAll('"', '""')}"`;

export const weekday = (date: string) =>
  new Date(date + "T00:00:00Z").toLocaleDateString("en-US", {
    weekday: "long",
    timeZone: "UTC",
  });
