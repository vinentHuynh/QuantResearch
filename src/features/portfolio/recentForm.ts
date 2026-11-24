import { useMemo } from "react";
import { assessCondition } from "../../../shared/ts/strategyCondition.ts";
import type { CollectiveDashboardModel } from "./useCollectiveDashboardModel";

export type RecentForm = {
  id: string;
  tone: "watch" | "weak" | "ok" | "unknown";
  label: string;
  last10: number | null;
};

/** Recent form of each selected strategy, as of today. Describes the past. */
export function useRecentForm(model: CollectiveDashboardModel) {
  const { catalog, histories, selected } = model;
  return useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return Object.fromEntries(
      selected.map((item) => {
        const assessment = assessCondition(
          item,
          histories.find((series) => series.id === item.id),
          today,
          catalog?.condition_calibration,
          catalog?.market_data_through?.[item.symbol],
        );
        const last10 = assessment.last10.count ? assessment.last10.pnl : null;
        const tone: RecentForm["tone"] = assessment.condition === "Unusual weakness" ? "weak"
          : assessment.condition.startsWith("Watch") ? "watch"
            : assessment.condition === "Insufficient evidence" ? "unknown" : "ok";
        const lead = tone === "weak" ? "Unusual weakness" : tone === "watch" ? "Watch" : tone === "ok" ? "Steady" : "Not enough data";
        const label = last10 === null ? lead : `${lead} · last 10 trades ${last10 < 0 ? "−" : "+"}$${Math.abs(Math.round(last10)).toLocaleString("en-US")}`;
        return [item.id, { id: item.id, tone, label, last10 } satisfies RecentForm];
      }),
    ) as Record<string, RecentForm>;
  }, [catalog, histories, selected]);
}

