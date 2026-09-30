import {
  DEFAULT_PORTFOLIO_CAPITAL,
  defaultPolicy,
  type Dependence,
  type GatePolicy,
  type GateState,
} from "../../../shared/ts/portfolio.ts";
import { defaultSizing } from "../../../shared/ts/riskSizing.ts";

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
  basis: "marked" | "closed";
  policy: GatePolicy;
};

export type SavedCombination = {
  id: string;
  name: string;
  saved_at: string;
  settings: CollectiveSettings;
};

export const SETTINGS_KEY = "quant-collective-v1";
export const PREVIOUS_SETTINGS_KEY = "quant-collective-previous-v1";
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
