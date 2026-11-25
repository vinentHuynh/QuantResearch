import { useMemo } from "react";
import { Button, Text } from "@mantine/core";
import { assessCondition } from "../../../shared/ts/strategyCondition.ts";
import { strategyTitle } from "../../../shared/ts/formatting.ts";
import type { CollectiveDashboardModel } from "./useCollectiveDashboardModel";
import { formatMoney as money, signedClass as signed } from "./collectiveViewModel";

const dateFormat = new Intl.DateTimeFormat("en-US", {
  month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
});
const signedMoney = (n: number) => `${n < 0 ? "−" : "+"}${money(Math.abs(n))}`;

/** Plain-language recent form for each selected strategy: three windows and distance below peak. */
export function RecentFormCards({ model, onPause }: { model: CollectiveDashboardModel; onPause: (id: string) => void }) {
  const { catalog, histories, selected } = model;
  const today = new Date().toISOString().slice(0, 10);
  const rows = useMemo(
    () =>
      selected.map((item) => ({
        item,
        a: assessCondition(
          item,
          histories.find((series) => series.id === item.id),
          today,
          catalog?.condition_calibration,
          catalog?.market_data_through?.[item.symbol],
        ),
      })),
    [catalog, histories, selected, today],
  );
  if (!rows.length) return null;
  return (
    <section className="wb-card wb-recent-form" aria-label="Recent form" data-testid="recent-form">
      <Text size="xs" c="dimmed" mb="sm">
        Trade windows use confirmed strategy exits. Daily P&amp;L includes recorded days with no exits. All dates are UTC.
      </Text>
      {rows.map(({ item, a }) => {
        const tone = a.condition === "Unusual weakness" ? "weak" : a.condition.startsWith("Watch") ? "watch" : a.condition === "Insufficient evidence" ? "unknown" : "ok";
        const lead = tone === "weak" ? "Unusual weakness" : tone === "watch" ? "Watch · recent losses" : tone === "ok" ? "Steady" : "Not enough data";
        const windows = [
          { label: "Last 10 trade exits", w: a.last10 },
          { label: "Last 30 trade exits", w: a.last30 },
          { label: "Last 20 observed days", w: a.last20 },
        ];
        return (
          <article key={item.id} className="wb-recent-form-row" data-testid={`recent-form-${item.id}`}>
            <header>
              <h2>{strategyTitle(item.name || item.id)}<Text span c="dimmed"> · {item.symbol}</Text></h2>
              <span className={`wb-status-chip is-${tone === "ok" ? "ready" : tone === "unknown" ? "next" : tone === "weak" ? "failed" : "blocked"}`}>{lead}</span>
              <Button variant="default" size="xs" onClick={() => onPause(item.id)}>Pause this strategy</Button>
            </header>
            <div className="wb-recent-form-grid">
              {windows.map(({ label, w }) => (
                <div key={label}>
                  <Text size="xs" c="dimmed">
                    {label}{w.count > 0 && w.count < w.requested && ` (${w.count} available)`}
                  </Text>
                  <strong className={`mono ${w.count ? signed(w.pnl) : ""}`}>{w.count ? signedMoney(w.pnl) : "—"}</strong>
                  <Text size="xs" c="dimmed">
                    {w.start && w.end ? dateFormat.formatRange(new Date(w.start), new Date(w.end)) : "Not enough data"}
                  </Text>
                </div>
              ))}
            </div>
            <Text size="sm">
              Currently <strong>{money(a.drawdown)}</strong> below its peak
              {a.drawdown > 0 && <>, <strong>{a.underwaterDays} days</strong> since the last high</>}.
              {" "}Status as of {a.asOf ? dateFormat.format(new Date(a.asOf)) : "—"}. Describes the past; not a forecast.
            </Text>
          </article>
        );
      })}
    </section>
  );
}
