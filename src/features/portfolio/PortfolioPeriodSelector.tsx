import type { PortfolioPnlPeriod } from "../../../shared/ts/portfolioPeriods.ts";

const OPTIONS: { value: PortfolioPnlPeriod; shortLabel: string; label: string }[] = [
  { value: "all", shortLabel: "All", label: "All time" },
  { value: "1y", shortLabel: "1Y", label: "1 year" },
  { value: "ytd", shortLabel: "YTD", label: "YTD" },
  { value: "6m", shortLabel: "6M", label: "6 months" },
  { value: "1m", shortLabel: "1M", label: "1 month" },
];

export function PortfolioPeriodSelector({ value, onChange }: {
  value: PortfolioPnlPeriod;
  onChange: (period: PortfolioPnlPeriod) => void;
}) {
  return (
    <div className="collective-chart-ranges" role="group" aria-label="P&L period">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-label={option.label}
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.shortLabel}
        </button>
      ))}
    </div>
  );
}
