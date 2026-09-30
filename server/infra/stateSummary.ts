import type { DatabaseSync } from "node:sqlite";

// Keep complete inputs and metrics for filtering, reuse, research, and watchlists.
// Chart/trade previews belong to the separately fetched run detail. Project in
// SQLite so polling never materializes the large arrays in the Node process.
export function runSummaries(db: DatabaseSync): unknown[] {
  const invalidLegacy = db.prepare(`SELECT id FROM records
    WHERE kind='run' AND CASE
      WHEN json_valid(body)=0 THEN 1
      WHEN json_type(body) <> 'object' THEN 1
      ELSE 0 END
    LIMIT 1`).get();
  if (invalidLegacy)
    throw new Error(
      `Invalid protocol-v1 SQLite record for run/${String(invalidLegacy.id)}`,
    );
  const invalidV2 = db.prepare(`SELECT records.id AS id FROM records
    WHERE kind='run'
      AND json_extract(body, '$.schema_version') = 2
      AND (
        json_type(body, '$.kind') IS NOT NULL
        OR json_type(body, '$.body') IS NOT NULL
      )
      AND (
        json_type(body, '$.schema_version') IS NOT 'integer'
        OR json_type(body, '$.kind') IS NOT 'text'
        OR json_extract(body, '$.kind') IS NOT records.kind
        OR json_type(body, '$.id') IS NOT 'text'
        OR json_extract(body, '$.id') IS NOT records.id
        OR json_type(body, '$.body') IS NOT 'object'
        OR (SELECT count(*) FROM json_each(records.body)) <> 4
        OR EXISTS (
          SELECT 1 FROM json_each(records.body)
          WHERE key NOT IN ('schema_version', 'kind', 'id', 'body')
        )
      )
    LIMIT 1`).get();
  if (invalidV2)
    throw new Error(
      `Invalid protocol-v2 SQLite envelope for run/${String(invalidV2.id)}`,
    );
  return db.prepare(`SELECT json_remove(
    CASE WHEN json_extract(body, '$.schema_version') = 2
      AND json_type(body, '$.kind') = 'text'
      AND json_type(body, '$.body') = 'object'
      THEN json_extract(body, '$.body') ELSE json(body) END,
    '$.result.equity_preview', '$.result.trade_preview', '$.log') AS body
    FROM records WHERE kind='run' ORDER BY rowid DESC`)
    .all().map((row) => JSON.parse(String(row.body)));
}
