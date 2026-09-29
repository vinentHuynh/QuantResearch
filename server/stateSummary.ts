import type { DatabaseSync } from "node:sqlite";

// Keep complete inputs and metrics for filtering, reuse, research, and watchlists.
// Chart/trade previews belong to the separately fetched run detail. Project in
// SQLite so polling never materializes the large arrays in the Node process.
export function runSummaries(db: DatabaseSync): unknown[] {
  return db.prepare(`SELECT json_remove(body,
    '$.result.equity_preview', '$.result.trade_preview', '$.log') AS body
    FROM records WHERE kind='run' ORDER BY rowid DESC`)
    .all().map((row) => JSON.parse(String(row.body)));
}
