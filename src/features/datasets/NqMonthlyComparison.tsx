import { useEffect, useState } from "react";
import { Alert, Badge, Button, Group, Loader, ScrollArea, Table, Text } from "@mantine/core";
import { IconDownload } from "@tabler/icons-react";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import "./nqMonthly.css";

type MonthlyRow = {
  strategy_id: string;
  strategy_name: string;
  run_id: string | null;
  selection_note: string;
  rank: number | null;
  status: string;
  comparison_eligible: boolean;
  solvency_flag: string;
  net_return_pct: number | null;
  net_pnl_usd: number | null;
  max_drawdown_pct: number | null;
  return_to_drawdown: number | null;
  trades: number | null;
  monthly_return_pct: (number | null)[];
  monthly_pnl_usd: (number | null)[];
  issues: string[];
};

type MonthlyReport = {
  generated_at: string;
  period: { start: string; end: string };
  dataset_id: string;
  assumptions: {
    capital: number;
    fee_per_contract_per_side: number;
    slippage_ticks_per_side: number;
  };
  months: string[];
  rows: MonthlyRow[];
  zone_screen: {
    attempts: number;
    selected_exit: string | null;
    actual_exit_profitable: number;
  };
};

const API = "/api/workbench/nq-monthly";
const number = (value: number | null, digits = 2) =>
  value === null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
const percent = (value: number | null, signed = false) => {
  if (value === null || !Number.isFinite(value)) return "—";
  const rounded = Math.abs(value) < 0.005 ? 0 : value;
  return `${signed && rounded > 0 ? "+" : ""}${rounded.toFixed(2)}%`;
};
const money = (value: number | null) =>
  value === null || !Number.isFinite(value)
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(value);
const feeMoney = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
const monthLabel = (month: string) =>
  new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" }).format(
    new Date(`${month}-01T00:00:00Z`),
  );
const cellTone = (value: number | null) =>
  value === null || !Number.isFinite(value)
    ? "missing"
    : value > 0
      ? "positive"
      : value < 0
        ? "negative"
        : "flat";

function RowStatus({ row }: { row: MonthlyRow }) {
  if (row.status !== "Succeeded")
    return <Badge size="xs" color="red" variant="light">{row.status}</Badge>;
  if (row.solvency_flag)
    return <Badge size="xs" color="red" variant="light">Insolvent</Badge>;
  if (row.trades === 0)
    return <Badge size="xs" color="gray" variant="light">Zero trades</Badge>;
  if (!row.comparison_eligible)
    return <Badge size="xs" color="yellow" variant="light">Unranked</Badge>;
  return null;
}

export function NqMonthlyComparison({
  onInspect,
  refreshKey,
}: {
  onInspect: (runId: string) => void;
  refreshKey: number;
}) {
  const [report, setReport] = useState<MonthlyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [monthlyValue, setMonthlyValue] = useState<"return" | "pnl">("return");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetch(API, { signal: controller.signal })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
        if (!Array.isArray(result.rows) || !Array.isArray(result.months))
          throw new Error("The saved comparison is incomplete.");
        return result as MonthlyReport;
      })
      .then((result) => {
        setReport(result);
        setError("");
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [refreshKey]);

  if (loading && !report)
    return <div className="wb-content"><div className="wb-card nq-monthly-loading"><Loader size="sm" /><Text size="sm">Loading the saved NQ comparison…</Text></div></div>;

  if (!report)
    return <div className="wb-content"><Alert color="red" title="NQ comparison unavailable">{error || "The saved campaign could not be loaded."}</Alert></div>;

  const best = report.rows.find((row) => row.rank === 1);
  const successful = report.rows.filter((row) => row.status === "Succeeded").length;
  const formattedPeriod = `${report.period.start} → ${report.period.end}`;
  const generated = new Date(report.generated_at);
  const generatedLabel = Number.isNaN(generated.valueOf())
    ? report.generated_at
    : generated.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });

  return (
    <div className="wb-content nq-monthly">
      {error && <Alert color="red" title="Refresh failed">Showing the previously loaded comparison. {error}</Alert>}
      <div className="wb-card nq-monthly-intro">
        <div>
          <Text className="nq-monthly-eyebrow">Saved historical campaign · NQ futures</Text>
          <h2>NQ strategy comparison</h2>
          <Text size="sm" c="dimmed">
            {formattedPeriod} · {report.rows.length} strategies · {successful} succeeded
            {loading ? " · Refreshing…" : ""}
          </Text>
        </div>
        <Button component="a" href={`${API}/report.csv`} variant="light" size="xs" leftSection={<IconDownload size={15} />}>
          Download results CSV
        </Button>
      </div>

      {best && (
        <div className="wb-card nq-monthly-best">
          <div>
            <Text className="nq-monthly-eyebrow">Best return / drawdown in this period</Text>
            <h2>{strategyTitle(best.strategy_name)}</h2>
            <Text size="xs" c="dimmed">Ranked among comparable, traded runs with positive simulated equity.</Text>
          </div>
          <div className="nq-monthly-best-metrics">
            <div><span>Score</span><strong>{number(best.return_to_drawdown)}</strong></div>
            <div><span>Net return</span><strong>{percent(best.net_return_pct, true)}</strong></div>
            <div><span>Max drawdown</span><strong>{percent(best.max_drawdown_pct === null ? null : Math.abs(best.max_drawdown_pct))}</strong></div>
            <div><span>Trades</span><strong>{best.trades ?? "—"}</strong></div>
          </div>
          {best.run_id && <button type="button" className="nq-monthly-run-link" onClick={() => onInspect(best.run_id!)}>Inspect winning run</button>}
        </div>
      )}

      <div className="wb-card nq-monthly-table-card">
        <Group justify="space-between" align="flex-end" mb="sm" gap="xs">
          <div>
            <h2>Monthly results</h2>
            <Text size="xs" c="dimmed">Month-end marked equity from each continuous run. Scroll the table sideways for all months.</Text>
          </div>
          <div className="nq-monthly-table-actions">
            <div className="nq-monthly-metric-switch" role="group" aria-label="Monthly value">
              <button type="button" aria-pressed={monthlyValue === "return"} onClick={() => setMonthlyValue("return")}>Return %</button>
              <button type="button" aria-pressed={monthlyValue === "pnl"} onClick={() => setMonthlyValue("pnl")}>P&amp;L $</button>
            </div>
            <div className="nq-monthly-legend" aria-label="Result colors">
              <span><i className="positive" /> Gain</span>
              <span><i className="negative" /> Loss</span>
              <span><i className="flat" /> Flat</span>
            </div>
          </div>
        </Group>
        <ScrollArea type="auto" offsetScrollbars>
          <Table className="nq-monthly-table" striped={false} highlightOnHover verticalSpacing="xs" horizontalSpacing="xs">
            <Table.Caption>Risk adjusted NQ ranking and monthly {monthlyValue === "return" ? "returns" : "profit and loss"} for {formattedPeriod}</Table.Caption>
            <Table.Thead>
              <Table.Tr>
                <Table.Th scope="col">Rank</Table.Th>
                <Table.Th scope="col" className="nq-monthly-strategy-head">Strategy / run</Table.Th>
                <Table.Th scope="col" ta="right" className="nq-monthly-summary-col">Return / DD</Table.Th>
                <Table.Th scope="col" ta="right" className="nq-monthly-summary-col">Net return</Table.Th>
                <Table.Th scope="col" ta="right" className="nq-monthly-summary-col">Max DD</Table.Th>
                <Table.Th scope="col" ta="right" className="nq-monthly-summary-col">Trades</Table.Th>
                {report.months.map((month) => <Table.Th scope="col" ta="right" key={month} title={month}>{monthLabel(month)}</Table.Th>)}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {report.rows.map((row) => (
                <Table.Tr key={row.strategy_id} className={row.rank === 1 ? "nq-monthly-first" : undefined}>
                  <Table.Td className="nq-monthly-rank">{row.rank ?? "—"}</Table.Td>
                  <Table.Th scope="row" className="nq-monthly-strategy">
                    {row.run_id ? (
                      <button type="button" className="nq-monthly-run-link" onClick={() => onInspect(row.run_id!)}>
                        {strategyTitle(row.strategy_name)}
                      </button>
                    ) : <strong>{strategyTitle(row.strategy_name)}</strong>}
                    <div className="nq-monthly-row-sub">
                      <RowStatus row={row} />
                      {row.run_id && <span title={row.run_id}>Run {row.run_id.slice(0, 8)}</span>}
                      <span className="nq-monthly-mobile-summary">
                        {percent(row.net_return_pct, true)} net · {percent(row.max_drawdown_pct === null ? null : Math.abs(row.max_drawdown_pct))} DD · {row.trades ?? "—"} trades · {number(row.comparison_eligible ? row.return_to_drawdown : null)} score
                      </span>
                    </div>
                  </Table.Th>
                  <Table.Td ta="right" className="nq-monthly-number nq-monthly-summary-col">{number(row.comparison_eligible ? row.return_to_drawdown : null)}</Table.Td>
                  <Table.Td ta="right" className={`nq-monthly-number nq-monthly-summary-col ${cellTone(row.net_return_pct)}`}>{percent(row.net_return_pct, true)}</Table.Td>
                  <Table.Td ta="right" className="nq-monthly-number nq-monthly-summary-col">{percent(row.max_drawdown_pct === null ? null : Math.abs(row.max_drawdown_pct))}</Table.Td>
                  <Table.Td ta="right" className="nq-monthly-number nq-monthly-summary-col">{row.trades ?? "—"}</Table.Td>
                  {report.months.map((month, index) => {
                    const value = row.monthly_return_pct[index] ?? null;
                    const pnl = row.monthly_pnl_usd[index] ?? null;
                    const displayed = monthlyValue === "return" ? value : pnl;
                    return (
                      <Table.Td
                        key={month}
                        ta="right"
                        className="nq-monthly-cell"
                        data-tone={cellTone(displayed)}
                        title={`${strategyTitle(row.strategy_name)} · ${month}: ${percent(value, true)}; ${money(pnl)}`}
                        aria-label={`${strategyTitle(row.strategy_name)}, ${month}: return ${percent(value, true)}, P&L ${money(pnl)}`}
                      >
                        {monthlyValue === "return" ? percent(value, true) : money(pnl)}
                      </Table.Td>
                    );
                  })}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
        <Group justify="space-between" gap="xs" mt="sm">
          <Text size="xs" c="dimmed">— means unavailable or ineligible for a rank. Select a strategy name to inspect its saved run and full warnings.</Text>
          <Button component="a" href={`${API}/monthly-pnl.csv`} variant="subtle" size="xs" leftSection={<IconDownload size={15} />}>Download monthly P&amp;L CSV</Button>
        </Group>
      </div>

      <div className="nq-monthly-foot-grid">
        <div className="wb-card">
          <h2>Comparison assumptions</h2>
          <dl className="nq-monthly-facts">
            <div><dt>Market / period</dt><dd>NQ · {formattedPeriod}</dd></div>
            <div><dt>Starting capital per run</dt><dd>{money(report.assumptions.capital)}</dd></div>
            <div><dt>Commission per contract, per side</dt><dd>{feeMoney(report.assumptions.fee_per_contract_per_side)}</dd></div>
            <div><dt>Slippage per side</dt><dd>{report.assumptions.slippage_ticks_per_side} tick{report.assumptions.slippage_ticks_per_side === 1 ? "" : "s"}</dd></div>
            <div><dt>Dataset version</dt><dd><code title={report.dataset_id}>{report.dataset_id}</code></dd></div>
            <div><dt>Report generated</dt><dd>{generatedLabel}</dd></div>
          </dl>
        </div>
        <div className="wb-card">
          <h2>How to read this campaign</h2>
          <Text size="sm" mt="xs">Rank uses net return divided by absolute maximum drawdown. A rank requires a completed, comparable run with trades and positive simulated equity throughout.</Text>
          <Text size="sm" mt="xs">These January–August 2026 dates were already inspected in earlier research. The ranking is descriptive historical evidence, not a fresh holdout or live trading approval.</Text>
          <Text size="sm" mt="xs">Multi-speed momentum fell below zero simulated equity and is unranked at this capital level. Wyckoff made no trades.</Text>
          {report.zone_screen.attempts > 0 && <Text size="sm" mt="xs">The SND exit screen tested {report.zone_screen.attempts} settings. {report.zone_screen.actual_exit_profitable === 0 ? "No actual opposing-zone exit setting was profitable." : `${report.zone_screen.actual_exit_profitable} opposing-zone exit settings were profitable.`} The selected setting was {report.zone_screen.selected_exit || "unspecified"}.</Text>}
        </div>
      </div>

      <details className="wb-card nq-monthly-provenance">
        <summary>Configuration selection and review notes</summary>
        <Text size="xs" c="dimmed" mt="sm" mb="sm">Settings were selected from recorded historical research. A reference that overlaps this campaign does not establish independent prior evidence.</Text>
        <div className="nq-monthly-provenance-list">
          {report.rows.map((row) => (
            <div key={row.strategy_id}>
              <strong>{strategyTitle(row.strategy_name)}</strong>
              <span>{row.selection_note || "No selection note recorded."}</span>
              {row.issues.length > 0 && <span className="nq-monthly-issue">Review: {row.issues.join("; ")}</span>}
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
