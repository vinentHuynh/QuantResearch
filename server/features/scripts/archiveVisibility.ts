import { parseCsv } from "../scorecards/dashboard.ts";

type MonthlyRow = { strategy_id: string; rank: number | null };
type MonthlyReport<T extends MonthlyRow> = { rows: T[]; zone_screen?: { attempts: number; selected_exit: string | null; actual_exit_profitable: number } };

export function visibleMonthlyReport<T extends MonthlyRow>(report: MonthlyReport<T>, archived: ReadonlySet<string>): MonthlyReport<T> {
  if (!archived.size) return report;
  let rank = 0;
  const rows = report.rows
    .filter(row => !archived.has(row.strategy_id))
    .map(row => ({ ...row, rank: row.rank === null ? null : ++rank }));
  return {
    ...report,
    rows,
    ...(archived.has("snd") || archived.has("snd-zone-exit")
      ? { zone_screen: { attempts: 0, selected_exit: null, actual_exit_profitable: 0 } }
      : {}),
  };
}

const csvCell = (value: string) => `"${value.replaceAll('"', '""')}"`;

export function visibleMonthlyCsv(source: string, archived: ReadonlySet<string>): string {
  if (!archived.size) return source;
  const [header, ...rows] = parseCsv(source);
  const idColumn = header?.indexOf("strategy_id") ?? -1;
  if (idColumn < 0) throw new Error("Saved comparison is missing strategy IDs");
  const rankColumn = header.indexOf("rank");
  let rank = 0;
  const visible = rows
    .filter(row => !archived.has(row[idColumn]))
    .map(row => {
      if (rankColumn < 0 || !row[rankColumn]) return row;
      const next = [...row];
      next[rankColumn] = String(++rank);
      return next;
    });
  return [header, ...visible].map(row => row.map(csvCell).join(",")).join("\n") + "\n";
}
