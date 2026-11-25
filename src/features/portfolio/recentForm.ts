import { useMemo } from "react";
import { assessCondition } from "../../../shared/ts/strategyCondition.ts";
import type { CollectiveDashboardModel } from "./useCollectiveDashboardModel";

export type RecentForm = {
  tone: "watch" | "weak" | "ok" | "unknown";
  status: string;
  tradeSummary: string;
};

type Assessment = ReturnType<typeof assessCondition>;

export function recentFormStatus(a: Assessment): Pick<RecentForm, "tone" | "status"> {
  switch (a.condition) {
    case "Watch — recent losses":
      return { tone: "watch", status: "Watch · recent losses" };
    case "Unusual weakness":
      return { tone: "weak", status: a.condition };
    case "Recovery developing":
      return { tone: "ok", status: a.condition };
    case "Within reference range":
      return { tone: "ok", status: "Steady" };
    default:
      return { tone: "unknown", status: a.last20.count ? "Historical comparison unavailable" : "Daily history unavailable" };
  }
}

const tradeMoney = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", signDisplay: "exceptZero",
  minimumFractionDigits: 0, maximumFractionDigits: 2,
});

/** Recent form of each selected strategy, as of today. Describes the past. */
export function useRecentForm(model: CollectiveDashboardModel) {
  const { catalog, histories, selected } = model;
  const today = new Date().toISOString().slice(0, 10);
  return useMemo(() => {
    return Object.fromEntries(
      selected.map((item) => {
        const assessment = assessCondition(
          item,
          histories.find((series) => series.id === item.id),
          today,
          catalog?.condition_calibration,
          catalog?.market_data_through?.[item.symbol],
        );
        const { count, requested, pnl } = assessment.last10;
        const window = count === requested ? `Last ${count} trades` : `${count} confirmed ${count === 1 ? "trade" : "trades"}`;
        const tradeSummary = count ? `${window} · ${tradeMoney.format(pnl)}`
          : assessment.asOf ? "No confirmed trade exits" : "Trade history unavailable";
        return [item.id, { ...recentFormStatus(assessment), tradeSummary }];
      }),
    ) as Record<string, RecentForm>;
  }, [catalog, histories, selected, today]);
}

