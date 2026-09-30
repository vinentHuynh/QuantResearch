from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    chart_id TEXT,
    status TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    output_dir TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS analysis_runs_created_at ON analysis_runs(created_at DESC);
CREATE TABLE IF NOT EXISTS validation_results (
    run_id TEXT NOT NULL,
    check_code TEXT NOT NULL,
    state TEXT NOT NULL,
    message TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY (run_id, check_code),
    FOREIGN KEY (run_id) REFERENCES analysis_runs(id)
);
CREATE TABLE IF NOT EXISTS run_artifacts (
    run_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    url TEXT NOT NULL,
    PRIMARY KEY (run_id, name),
    FOREIGN KEY (run_id) REFERENCES analysis_runs(id)
);
CREATE TABLE IF NOT EXISTS run_revisions (
    revision_hash TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(id)
);
CREATE INDEX IF NOT EXISTS run_revisions_run_id ON run_revisions(run_id, recorded_at);
"""


class RunRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def save(self, payload: dict[str, Any]) -> None:
        chart_id = payload.get("parameters", {}).get("chart_id")
        checks = payload.get("validation_checks", [])
        artifacts = payload.get("artifacts", [])
        encoded_payload = json.dumps(payload, default=str, sort_keys=True)
        revision_hash = hashlib.sha256(encoded_payload.encode()).hexdigest()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO analysis_runs
                   (id, strategy_id, chart_id, status, validation_status, created_at,
                    finished_at, output_dir, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     status=excluded.status,
                     validation_status=excluded.validation_status,
                     finished_at=excluded.finished_at,
                     payload_json=excluded.payload_json""",
                (payload["id"], payload["strategy_id"], chart_id, payload["status"],
                 payload.get("validation_status", "pending"), payload["created_at"],
                 payload.get("finished_at"), payload["output_dir"],
                 encoded_payload),
            )
            connection.execute(
                "INSERT OR IGNORE INTO run_revisions(revision_hash, run_id, payload_json) VALUES (?, ?, ?)",
                (revision_hash, payload["id"], encoded_payload),
            )
            connection.execute("DELETE FROM validation_results WHERE run_id = ?", (payload["id"],))
            connection.executemany(
                "INSERT INTO validation_results VALUES (?, ?, ?, ?, ?)",
                [(payload["id"], item["code"], item["state"], item["message"],
                  json.dumps(item.get("evidence", {}), default=str)) for item in checks],
            )
            connection.execute("DELETE FROM run_artifacts WHERE run_id = ?", (payload["id"],))
            connection.executemany(
                "INSERT INTO run_artifacts VALUES (?, ?, ?, ?, ?)",
                [(payload["id"], item["name"], item["kind"], item["size"], item["url"])
                 for item in artifacts],
            )

    def load(self, limit: int = 10_000) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM analysis_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def revisions(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT revision_hash, recorded_at, payload_json FROM run_revisions WHERE run_id = ? ORDER BY recorded_at, rowid",
                (run_id,),
            ).fetchall()
        return [{"revision_hash": row[0], "recorded_at": row[1], "payload": json.loads(row[2])} for row in rows]
