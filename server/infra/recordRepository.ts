import type { DatabaseSync } from "node:sqlite";

export const RECORD_SCHEMA_VERSION = 2;

export type RecordEnvelope<T = Record<string, unknown>> = {
  schema_version: typeof RECORD_SCHEMA_VERSION;
  kind: string;
  id: string;
  body: T;
};

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isRecordEnvelope<T>(
  value: unknown,
  kind?: string,
  id?: string,
): value is RecordEnvelope<T> {
  if (!isObject(value)) return false;
  const keys = Object.keys(value).sort();
  return (
    keys.length === 4 &&
    keys.join("\0") === "body\0id\0kind\0schema_version" &&
    value.schema_version === RECORD_SCHEMA_VERSION &&
    typeof value.kind === "string" &&
    /^[a-z][a-z0-9_-]{0,79}$/.test(value.kind) &&
    typeof value.id === "string" &&
    value.id.length >= 1 &&
    value.id.length <= 200 &&
    isObject(value.body) &&
    (kind === undefined || value.kind === kind) &&
    (id === undefined || value.id === id)
  );
}

export function decodeRecord<T>(raw: string, kind: string, id: string): T {
  const value: unknown = JSON.parse(raw);
  if (isRecordEnvelope<T>(value, kind, id)) return value.body;
  if (
    isObject(value) &&
    value.schema_version === RECORD_SCHEMA_VERSION &&
    (Object.hasOwn(value, "kind") || Object.hasOwn(value, "body"))
  )
    throw new Error(`Invalid protocol-v2 SQLite envelope for ${kind}/${id}`);
  if (!isObject(value))
    throw new Error(`Invalid protocol-v1 SQLite record for ${kind}/${id}`);
  // Protocol-v1 records are deliberately left in their original shape.
  return value as T;
}

export function encodeRecord<T>(
  kind: string,
  id: string,
  body: T,
): string {
  if (!isObject(body)) throw new Error("Record body must be an object");
  return JSON.stringify({
    schema_version: RECORD_SCHEMA_VERSION,
    kind,
    id,
    body,
  } satisfies RecordEnvelope<T>);
}

export type RecordRepository = ReturnType<typeof createRecordRepository>;

export function createRecordRepository(db: DatabaseSync) {
  db.exec(
    "CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(kind,id))",
  );

  function raw(kind: string, id: string): string | undefined {
    const row = db
      .prepare("SELECT body FROM records WHERE kind=? AND id=?")
      .get(kind, id);
    return row ? String(row.body) : undefined;
  }

  function put(kind: string, id: string, body: unknown) {
    if (!isObject(body)) throw new Error("Record body must be an object");
    const previous = raw(kind, id);
    let encoded: string;
    if (previous !== undefined) {
      const value: unknown = JSON.parse(previous);
      decodeRecord(previous, kind, id);
      // Updating a v1 row must not silently rewrite it into protocol v2.
      encoded = isRecordEnvelope(value, kind, id)
        ? encodeRecord(kind, id, body)
        : JSON.stringify(body);
    } else {
      encoded = encodeRecord(kind, id, body);
    }
    db.prepare(
      "INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
    ).run(kind, id, encoded);
  }

  function get<T>(kind: string, id: string): T {
    const value = raw(kind, id);
    if (value === undefined) throw new Error(`${kind} not found`);
    return decodeRecord<T>(value, kind, id);
  }

  function all<T>(kind: string): T[] {
    return db
      .prepare("SELECT id, body FROM records WHERE kind=? ORDER BY rowid DESC")
      .all(kind)
      .map((row) => decodeRecord<T>(String(row.body), kind, String(row.id)));
  }

  return { put, get, all, raw };
}
