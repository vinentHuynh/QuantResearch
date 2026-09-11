from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import sqlite3
import statistics
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal


ELIGIBILITY = {"Qualified", "Provisional", "Rejected", "Retired"}
HEALTH = {"Normal", "Watch", "Breached", "Unknown"}
ALLOCATION = {"Base", "Reduced", "Paused", "No current proposal"}
POLICY_STATES = {"Exploratory", "In validation", "Approved for paper proposals", "Approved for allocation proposals"}
CALCULATION_VERSION = "portfolio-1.0"


SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_settings (
  version INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_versions (
  id TEXT PRIMARY KEY,
  strategy_id TEXT NOT NULL,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  eligibility TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS strategy_versions_strategy ON strategy_versions(strategy_id, created_at DESC);
CREATE TABLE IF NOT EXISTS eligibility_assessments (
  id TEXT PRIMARY KEY,
  strategy_version_id TEXT NOT NULL,
  assessment_time TEXT NOT NULL,
  eligibility TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(strategy_version_id) REFERENCES strategy_versions(id)
);
CREATE INDEX IF NOT EXISTS eligibility_history ON eligibility_assessments(strategy_version_id, assessment_time DESC);
CREATE TABLE IF NOT EXISTS observations (
  id TEXT PRIMARY KEY,
  strategy_version_id TEXT NOT NULL,
  event_time TEXT NOT NULL,
  availability_time TEXT NOT NULL,
  observation_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  revision_of TEXT,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(strategy_version_id) REFERENCES strategy_versions(id),
  FOREIGN KEY(revision_of) REFERENCES observations(id)
);
CREATE INDEX IF NOT EXISTS observations_cutoff ON observations(strategy_version_id, availability_time, event_time);
CREATE TABLE IF NOT EXISTS decision_runs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  cutoff TEXT NOT NULL,
  effective_time TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  calculation_version TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_created ON decision_runs(created_at DESC);
CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY,
  strategy_version_id TEXT,
  fingerprint TEXT NOT NULL,
  state TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS alerts_open_fingerprint ON alerts(fingerprint) WHERE state != 'Resolved';
CREATE TABLE IF NOT EXISTS alert_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_id TEXT NOT NULL,
  event_time TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(alert_id) REFERENCES alerts(id)
);
CREATE TABLE IF NOT EXISTS experiments (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  state TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiment_reviews (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  review_time TEXT NOT NULL,
  state TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(experiment_id) REFERENCES experiments(id)
);
CREATE INDEX IF NOT EXISTS experiment_review_history ON experiment_reviews(experiment_id, review_time DESC);
CREATE TABLE IF NOT EXISTS overrides (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
"""


DEFAULT_SETTINGS: dict[str, Any] = {
    "base_currency": "USD",
    "calendar": None,
    "review_cadence": None,
    "staleness_days": None,
    "portfolio_volatility_budget": None,
    "volatility_floor": None,
    "gross_exposure_limit": None,
    "margin_limit": None,
    "outage_procedure": None,
    "decision_owner": None,
    "policy_version": "unconfigured-v1",
    "policy_state": "Exploratory",
    "cash_balance": None,
    "watch_window_observations": None,
    "watch_negative_fraction": None,
    "false_alert_budget": None,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def sample_std(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) > 1 else None


def compounded(values: Iterable[float]) -> float:
    total = 1.0
    for value in values:
        total *= 1.0 + value
    return total - 1.0


def covariance(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    return sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right)) / (len(left) - 1)


def elapsed_expected_sessions(start: datetime, end: datetime) -> int:
    """Weekday fallback used until an exchange holiday calendar is imported."""
    if end <= start:
        return 0
    day = start.date() + timedelta(days=1)
    count = 0
    while day <= end.date():
        if day.weekday() < 5:
            count += 1
        day += timedelta(days=1)
    return count


@dataclass
class PortfolioRepository:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            if connection.execute("SELECT COUNT(*) FROM portfolio_settings").fetchone()[0] == 0:
                connection.execute(
                    "INSERT INTO portfolio_settings(created_at, payload_json) VALUES (?, ?)",
                    (utc_now(), json.dumps(DEFAULT_SETTINGS)),
                )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def settings(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT version, created_at, payload_json FROM portfolio_settings ORDER BY version DESC LIMIT 1").fetchone()
        result = json.loads(row["payload_json"])
        return {**result, "version": row["version"], "created_at": row["created_at"]}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_SETTINGS)
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
        current = self.settings()
        current = {key: current.get(key) for key in DEFAULT_SETTINGS}
        numeric_fields = {"staleness_days", "portfolio_volatility_budget", "volatility_floor", "gross_exposure_limit", "margin_limit", "cash_balance", "watch_window_observations", "watch_negative_fraction", "false_alert_budget"}
        for key in numeric_fields & set(changes):
            if changes[key] in (None, ""):
                changes[key] = None
            else:
                parsed = number(changes[key])
                if parsed is None or parsed < 0:
                    raise ValueError(f"{key} must be a non-negative number or blank")
                changes[key] = parsed
        current.update(changes)
        if current["policy_state"] not in POLICY_STATES:
            raise ValueError("Invalid policy state")
        with self.connect() as connection:
            connection.execute("INSERT INTO portfolio_settings(created_at, payload_json) VALUES (?, ?)", (utc_now(), json.dumps(current)))
        return self.settings()

    def ensure_strategy(self, *, strategy_id: str, name: str, code_hash: str | None = None) -> dict[str, Any]:
        version_id = f"{strategy_id}@runner-v1"
        with self.connect() as connection:
            row = connection.execute("SELECT payload_json FROM strategy_versions WHERE id = ?", (version_id,)).fetchone()
            if row:
                return json.loads(row[0])
            created_at = utc_now()
            payload = {
                "id": version_id, "strategy_id": strategy_id, "name": name, "version": "runner-v1",
                "created_at": created_at, "eligibility": "Provisional", "eligibility_as_of": created_at,
                "evidence_strength": "Unknown", "eligibility_reason_codes": ["ACCEPTANCE_NOT_RECORDED"],
                "mechanism": None, "universe": [], "parameters": {}, "sizing_methodology": None,
                "calendar": None, "selection_date": None, "code_hash": code_hash,
                "data_versions": [], "cost_model": None, "acceptance_profile": None,
                "reviewer": None, "limitations": ["Imported runner definition; research acceptance has not been recorded."],
                "asset_class": None, "family": None, "shared_exposure_group": None,
                "current_exposure": 0.0, "base_allocation": None, "standalone_volatility_budget": None,
                "exposure_cap": None, "hard_drawdown_limit": None, "hard_margin_limit": None,
                "margin_per_exposure": None, "liquidity_capacity": None,
            }
            connection.execute(
                "INSERT INTO strategy_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (version_id, strategy_id, name, "runner-v1", created_at, "Provisional", json.dumps(payload)),
            )
        return payload

    def create_strategy(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = ["strategy_id", "name", "version"]
        missing = [key for key in required if not payload.get(key)]
        if missing:
            raise ValueError(f"Missing strategy fields: {', '.join(missing)}")
        eligibility = payload.get("eligibility", "Provisional")
        if eligibility not in ELIGIBILITY:
            raise ValueError("Invalid research eligibility")
        version_id = payload.get("id") or f"{payload['strategy_id']}@{payload['version']}"
        created_at = utc_now()
        record = {
            "id": version_id, "strategy_id": payload["strategy_id"], "name": payload["name"],
            "version": payload["version"], "created_at": created_at, "eligibility": eligibility,
            "eligibility_as_of": payload.get("eligibility_as_of", created_at),
            "evidence_strength": payload.get("evidence_strength", "Unknown"),
            "eligibility_reason_codes": payload.get("eligibility_reason_codes", ["ACCEPTANCE_NOT_RECORDED"]),
            "mechanism": payload.get("mechanism"), "universe": payload.get("universe", []),
            "parameters": payload.get("parameters", {}), "sizing_methodology": payload.get("sizing_methodology"),
            "calendar": payload.get("calendar"), "selection_date": payload.get("selection_date"),
            "code_hash": payload.get("code_hash"), "data_versions": payload.get("data_versions", []),
            "cost_model": payload.get("cost_model"), "acceptance_profile": payload.get("acceptance_profile"),
            "reviewer": payload.get("reviewer"), "limitations": payload.get("limitations", []),
            "asset_class": payload.get("asset_class"), "family": payload.get("family"),
            "shared_exposure_group": payload.get("shared_exposure_group"),
            "current_exposure": number(payload.get("current_exposure")) or 0.0,
            "base_allocation": number(payload.get("base_allocation")),
            "standalone_volatility_budget": number(payload.get("standalone_volatility_budget")),
            "exposure_cap": number(payload.get("exposure_cap")),
            "hard_drawdown_limit": number(payload.get("hard_drawdown_limit")),
            "hard_margin_limit": number(payload.get("hard_margin_limit")),
            "margin_per_exposure": number(payload.get("margin_per_exposure")),
            "liquidity_capacity": number(payload.get("liquidity_capacity")),
        }
        if eligibility == "Qualified":
            profile = record["acceptance_profile"]
            valid_hash = isinstance(record["code_hash"], str) and len(record["code_hash"]) == 64 and all(character in "0123456789abcdef" for character in record["code_hash"].lower())
            if not all((isinstance(profile, dict) and profile.get("objective"), record["reviewer"], record["selection_date"], valid_hash)):
                raise ValueError("Qualified versions require a predeclared objective, reviewer, selection date, and SHA-256 code/config hash")
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO strategy_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (version_id, record["strategy_id"], record["name"], record["version"], created_at, eligibility, json.dumps(record)),
            )
        return record

    def strategies(self, cutoff: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM strategy_versions ORDER BY name, created_at DESC").fetchall()
            if cutoff:
                normalized_cutoff = parse_time(cutoff).isoformat()
                assessments = connection.execute(
                    """SELECT payload_json FROM eligibility_assessments a
                       WHERE assessment_time = (SELECT MAX(assessment_time) FROM eligibility_assessments
                                                WHERE strategy_version_id = a.strategy_version_id AND assessment_time <= ?)""",
                    (normalized_cutoff,),
                ).fetchall()
            else:
                assessments = connection.execute(
                    """SELECT payload_json FROM eligibility_assessments a
                       WHERE assessment_time = (SELECT MAX(assessment_time) FROM eligibility_assessments WHERE strategy_version_id = a.strategy_version_id)"""
                ).fetchall()
        latest = {item["strategy_version_id"]: item for item in (json.loads(row[0]) for row in assessments)}
        result = []
        for row in rows:
            strategy = json.loads(row[0])
            assessment = latest.get(strategy["id"])
            if assessment:
                strategy.update({
                    "eligibility": assessment["eligibility"], "eligibility_as_of": assessment["assessment_time"],
                    "evidence_strength": assessment["evidence_strength"], "eligibility_reason_codes": assessment["reason_codes"],
                    "reviewer": assessment["reviewer"], "acceptance_profile": assessment.get("acceptance_profile"),
                    "limitations": assessment.get("limitations", []),
                })
            result.append(strategy)
        return result

    def strategy(self, version_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT payload_json FROM strategy_versions WHERE id = ?", (version_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def assess_eligibility(self, payload: dict[str, Any]) -> dict[str, Any]:
        version_id = payload.get("strategy_version_id")
        strategy = self.strategy(str(version_id)) if version_id else None
        if not strategy:
            raise ValueError("Unknown strategy version")
        eligibility = payload.get("eligibility")
        if eligibility not in ELIGIBILITY:
            raise ValueError("Invalid research eligibility")
        reviewer = str(payload.get("reviewer") or "").strip()
        if not reviewer:
            raise ValueError("Reviewer is required")
        profile = payload.get("acceptance_profile") or strategy.get("acceptance_profile")
        evidence = payload.get("evidence_snapshot")
        if eligibility == "Qualified":
            if not isinstance(profile, dict) or not profile.get("objective"):
                raise ValueError("Qualified assessments require a predeclared acceptance objective")
            if not isinstance(evidence, dict) or not evidence:
                raise ValueError("Qualified assessments require a recorded evidence snapshot")
            code_hash = strategy.get("code_hash")
            if not isinstance(code_hash, str) or len(code_hash) != 64 or any(character not in "0123456789abcdef" for character in code_hash.lower()):
                raise ValueError("Qualified assessments require a valid strategy code/config SHA-256")
            if not strategy.get("selection_date") and not payload.get("selection_date"):
                raise ValueError("Qualified assessments require the strategy selection date")
        assessment_time = utc_now()
        record = {
            "id": f"eligibility-{uuid.uuid4().hex[:12]}", "strategy_version_id": strategy["id"],
            "assessment_time": assessment_time, "eligibility": eligibility, "reviewer": reviewer,
            "evidence_strength": payload.get("evidence_strength", "Unknown"),
            "reason_codes": payload.get("reason_codes", ["REVIEWER_DECISION"]),
            "metric_values": payload.get("metric_values", {}), "acceptance_profile": profile,
            "evidence_snapshot": evidence or {}, "limitations": payload.get("limitations", []),
            "policy_version": payload.get("policy_version"), "selection_date": payload.get("selection_date") or strategy.get("selection_date"),
        }
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO eligibility_assessments VALUES (?, ?, ?, ?, ?)",
                (record["id"], strategy["id"], assessment_time, eligibility, json.dumps(record)),
            )
        return record

    def eligibility_history(self, version_id: str | None = None, cutoff: str | None = None) -> list[dict[str, Any]]:
        query, params = "SELECT payload_json FROM eligibility_assessments", []
        clauses = []
        if version_id:
            clauses.append("strategy_version_id = ?")
            params.append(version_id)
        if cutoff:
            clauses.append("assessment_time <= ?")
            params.append(parse_time(cutoff).isoformat())
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY assessment_time DESC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row[0]) for row in rows]

    def import_observations(self, *, strategy_version_id: str, rows: list[dict[str, Any]], source: str) -> dict[str, Any]:
        if not self.strategy(strategy_version_id):
            raise ValueError("Unknown strategy version")
        accepted, errors, identifiers = 0, [], []
        with self.connect() as connection:
            for index, raw in enumerate(rows, start=1):
                try:
                    event_time = parse_time(str(raw["event_time"])).isoformat()
                    availability_time = parse_time(str(raw.get("availability_time") or raw["event_time"])).isoformat()
                    observation_type = str(raw.get("observation_type", "return"))
                    if observation_type not in {"return", "position", "fill", "market", "cash_flow"}:
                        raise ValueError("unsupported observation_type")
                    payload = {
                        **raw, "event_time": event_time, "availability_time": availability_time,
                        "observation_type": observation_type, "source": source,
                        "currency": raw.get("currency", self.settings().get("base_currency")),
                    }
                    if observation_type == "return":
                        history_type = str(raw.get("history_type", "reference"))
                        if history_type not in {"backtest", "reference", "paper", "live"}:
                            raise ValueError("history_type must be backtest, reference, paper, or live")
                        payload["history_type"] = history_type
                    revision_of = raw.get("revision_of")
                    if revision_of:
                        prior = connection.execute("SELECT strategy_version_id FROM observations WHERE id = ?", (revision_of,)).fetchone()
                        if not prior or prior[0] != strategy_version_id:
                            raise ValueError("revision_of must identify an observation for the same strategy version")
                    existing = connection.execute(
                        "SELECT payload_json FROM observations WHERE strategy_version_id = ? AND event_time = ? AND observation_type = ?",
                        (strategy_version_id, event_time, observation_type),
                    ).fetchall()
                    duplicate = any(json.loads(item[0]).get("history_type") == payload.get("history_type") for item in existing)
                    if duplicate and not revision_of:
                        raise ValueError("duplicate event; provide revision_of to append a correction")
                    if observation_type == "return" and number(raw.get("net_return")) is None and number(raw.get("equity")) is None:
                        raise ValueError("return rows need net_return or equity")
                    if observation_type == "return" and number(raw.get("equity")) is not None and payload["currency"] != self.settings().get("base_currency") and number(raw.get("fx_rate_to_base")) is None:
                        raise ValueError("foreign-currency equity rows require fx_rate_to_base")
                    gross_pnl, net_pnl = number(raw.get("gross_pnl")), number(raw.get("net_pnl"))
                    if observation_type == "return" and gross_pnl is not None and net_pnl is not None:
                        expected_net = gross_pnl - (number(raw.get("fees")) or 0.0) - (number(raw.get("spread_cost")) or 0.0) - (number(raw.get("slippage_cost")) or 0.0) - (number(raw.get("financing")) or 0.0) - (number(raw.get("borrow_cost")) or 0.0)
                        if abs(expected_net - net_pnl) > max(0.01, abs(net_pnl) * 1e-8):
                            raise ValueError("gross P&L, costs, and net P&L do not reconcile")
                    identifier = raw.get("id") or stable_hash([strategy_version_id, event_time, availability_time, observation_type, source, raw])
                    connection.execute(
                        "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (identifier, strategy_version_id, event_time, availability_time, observation_type, utc_now(), revision_of, json.dumps(payload)),
                    )
                    accepted += 1
                    identifiers.append(identifier)
                except (KeyError, ValueError, TypeError, sqlite3.IntegrityError) as exc:
                    errors.append({"row": index, "message": str(exc)})
        return {"accepted": accepted, "rejected": len(errors), "errors": errors[:100], "observation_ids": identifiers}

    def observations(self, version_id: str, cutoff: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, revision_of, payload_json FROM observations WHERE strategy_version_id = ?"
        params: list[Any] = [version_id]
        if cutoff:
            query += " AND availability_time <= ?"
            params.append(parse_time(cutoff).isoformat())
        query += " ORDER BY event_time, availability_time, created_at"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        superseded = {row["revision_of"] for row in rows if row["revision_of"]}
        return [{"id": row["id"], **json.loads(row["payload_json"])} for row in rows if row["id"] not in superseded]

    def save_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO decision_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (decision["id"], decision["created_at"], decision["cutoff"], decision["effective_time"],
                 decision["snapshot_hash"], decision["policy_version"], decision["calculation_version"], json.dumps(decision)),
            )
        return decision

    def decisions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM decision_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def upsert_alert(self, *, strategy_version_id: str | None, code: str, severity: str, title: str, detail: str, evidence: dict[str, Any]) -> dict[str, Any]:
        fingerprint = stable_hash([strategy_version_id, code])
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute("SELECT id, payload_json FROM alerts WHERE fingerprint = ? AND state != 'Resolved'", (fingerprint,)).fetchone()
            if row:
                payload = json.loads(row["payload_json"])
                payload.update({"last_seen": now, "severity": severity, "title": title, "detail": detail, "evidence": evidence})
                connection.execute("UPDATE alerts SET last_seen = ?, payload_json = ? WHERE id = ?", (now, json.dumps(payload), row["id"]))
                return payload
            alert_id = f"alert-{uuid.uuid4().hex[:12]}"
            payload = {"id": alert_id, "strategy_version_id": strategy_version_id, "code": code, "severity": severity,
                       "title": title, "detail": detail, "evidence": evidence, "state": "Open", "first_seen": now,
                       "last_seen": now, "acknowledged_at": None, "resolution": None}
            connection.execute("INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (alert_id, strategy_version_id, fingerprint, "Open", now, now, json.dumps(payload)))
            connection.execute("INSERT INTO alert_events(alert_id, event_time, event_type, payload_json) VALUES (?, ?, ?, ?)",
                               (alert_id, now, "Opened", json.dumps({"evidence": evidence})))
        return payload

    def alerts(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM alerts ORDER BY CASE state WHEN 'Open' THEN 0 WHEN 'Acknowledged' THEN 1 ELSE 2 END, last_seen DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def update_alert(self, alert_id: str, action: str, note: str | None) -> dict[str, Any]:
        if action not in {"acknowledge", "resolve"}:
            raise ValueError("Action must be acknowledge or resolve")
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute("SELECT payload_json FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if not row:
                raise ValueError("Alert not found")
            payload = json.loads(row[0])
            payload["state"] = "Acknowledged" if action == "acknowledge" else "Resolved"
            if action == "acknowledge": payload["acknowledged_at"] = now
            else: payload["resolution"] = {"time": now, "note": note}
            connection.execute("UPDATE alerts SET state = ?, last_seen = ?, payload_json = ? WHERE id = ?", (payload["state"], now, json.dumps(payload), alert_id))
            connection.execute("INSERT INTO alert_events(alert_id, event_time, event_type, payload_json) VALUES (?, ?, ?, ?)",
                               (alert_id, now, payload["state"], json.dumps({"note": note})))
        return payload

    def create_override(self, payload: dict[str, Any]) -> dict[str, Any]:
        expires = parse_time(str(payload.get("expires_at", "")))
        if expires <= datetime.now(timezone.utc):
            raise ValueError("Override expiry must be in the future")
        if not payload.get("owner") or not payload.get("reason"):
            raise ValueError("Override owner and reason are required")
        record = {"id": f"override-{uuid.uuid4().hex[:12]}", "created_at": utc_now(), **payload, "expires_at": expires.isoformat()}
        with self.connect() as connection:
            connection.execute("INSERT INTO overrides VALUES (?, ?, ?, ?)", (record["id"], record["created_at"], record["expires_at"], json.dumps(record)))
        return record

    def overrides(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM overrides ORDER BY created_at DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_experiment(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = payload.get("state", "Exploratory")
        if state not in POLICY_STATES:
            raise ValueError("Invalid experiment state")
        record = {"id": f"experiment-{uuid.uuid4().hex[:12]}", "created_at": utc_now(), **payload, "state": state}
        with self.connect() as connection:
            connection.execute("INSERT INTO experiments VALUES (?, ?, ?, ?)", (record["id"], record["created_at"], state, json.dumps(record)))
        return record

    def experiments(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM experiments ORDER BY created_at DESC").fetchall()
            reviews = connection.execute(
                """SELECT payload_json FROM experiment_reviews r
                   WHERE review_time = (SELECT MAX(review_time) FROM experiment_reviews WHERE experiment_id = r.experiment_id)"""
            ).fetchall()
        latest = {item["experiment_id"]: item for item in (json.loads(row[0]) for row in reviews)}
        result = []
        for row in rows:
            experiment = json.loads(row[0])
            review = latest.get(experiment["id"])
            if review:
                experiment["state"] = review["state"]
                experiment["latest_review"] = review
            result.append(experiment)
        return result

    def experiment_reviews(self, experiment_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM experiment_reviews WHERE experiment_id = ? ORDER BY review_time DESC", (experiment_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def review_experiment(self, experiment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        experiment = next((item for item in self.experiments() if item["id"] == experiment_id), None)
        if not experiment:
            raise ValueError("Experiment not found")
        state = payload.get("state")
        if state not in POLICY_STATES:
            raise ValueError("Invalid policy state")
        reviewer = str(payload.get("reviewer") or "").strip()
        if not reviewer:
            raise ValueError("Reviewer is required")
        result = experiment.get("result", {})
        if state in {"In validation", "Approved for paper proposals", "Approved for allocation proposals"} and result.get("status") != "Complete":
            raise ValueError("Only a completed experiment can advance beyond Exploratory")
        if state in {"Approved for paper proposals", "Approved for allocation proposals"}:
            interval = result.get("paired_block_bootstrap_95_interval")
            if not isinstance(interval, list) or len(interval) != 2:
                raise ValueError("Policy approval requires stored uncertainty evidence")
            if not payload.get("untouched_evaluation_evidence"):
                raise ValueError("Policy approval requires untouched evaluation evidence")
        if state == "Approved for allocation proposals" and not payload.get("forward_paper_evidence"):
            raise ValueError("Allocation approval requires forward paper evidence")
        review_time = utc_now()
        record = {"id": f"experiment-review-{uuid.uuid4().hex[:12]}", "experiment_id": experiment_id,
                  "review_time": review_time, "state": state, "reviewer": reviewer,
                  "reason": payload.get("reason"), "untouched_evaluation_evidence": payload.get("untouched_evaluation_evidence"),
                  "forward_paper_evidence": payload.get("forward_paper_evidence"), "limitations": payload.get("limitations", [])}
        with self.connect() as connection:
            connection.execute("INSERT INTO experiment_reviews VALUES (?, ?, ?, ?, ?)",
                               (record["id"], experiment_id, review_time, state, json.dumps(record)))
        return record


def parse_import_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records")
    if isinstance(records, list):
        if not all(isinstance(row, dict) for row in records):
            raise ValueError("Every record must be an object")
        return records
    csv_text = payload.get("csv")
    if isinstance(csv_text, str):
        return list(csv.DictReader(io.StringIO(csv_text)))
    raise ValueError("Provide records or csv")


def return_rows(observations: list[dict[str, Any]], history_type: str | None = None) -> list[dict[str, Any]]:
    rows = [row for row in observations if row.get("observation_type") == "return" and (history_type is None or row.get("history_type", "reference") == history_type)]
    result: list[dict[str, Any]] = []
    previous_equity: float | None = None
    for row in rows:
        raw_equity = number(row.get("equity"))
        fx_rate = number(row.get("fx_rate_to_base")) or 1.0
        current = raw_equity * fx_rate if raw_equity is not None else None
        net_return = number(row.get("net_return"))
        cash_flow = (number(row.get("cash_flow")) or 0.0) * fx_rate
        if net_return is None and current is not None and previous_equity not in (None, 0):
            net_return = (current - cash_flow) / previous_equity - 1.0
        if net_return is not None:
            result.append({**row, "net_return": net_return, "equity": current})
        if current is not None:
            previous_equity = current
    return result


def metrics_for(rows: list[dict[str, Any]], cutoff: datetime, hard_limit: float | None) -> dict[str, Any]:
    values = [row["net_return"] for row in rows]
    event_times = [parse_time(row["event_time"]) for row in rows]
    last = max(event_times) if event_times else None
    equity, peak, drawdown, worst, underwater = 1.0, 1.0, 0.0, 0.0, 0
    curve = []
    monthly: dict[str, list[float]] = {}
    for row, value in zip(rows, values):
        equity *= 1.0 + value
        peak = max(peak, equity)
        drawdown = equity / peak - 1.0
        worst = min(worst, drawdown)
        underwater = underwater + 1 if drawdown < 0 else 0
        month = row["event_time"][:7]
        monthly.setdefault(month, []).append(value)
        curve.append({"time": row["event_time"], "equity": equity, "drawdown": drawdown})
    recent = sorted(monthly)[-12:]
    recent_months = [{"month": month, "return": compounded(monthly[month])} for month in recent]
    current_month = cutoff.strftime("%Y-%m")
    completed = [item for item in recent_months if item["month"] < current_month]
    std = sample_std(values[-252:])
    volatility = std * math.sqrt(252) if std is not None else None
    sharpe = (statistics.fmean(values) / std * math.sqrt(252)) if std not in (None, 0) else None
    trailing: dict[str, float | None] = {}
    for months in (1, 3, 6, 12):
        selected = completed[-months:]
        trailing[str(months)] = compounded(item["return"] for item in selected) if len(selected) == months else None
    health = "Unknown"
    reasons = ["NO_RETURN_OBSERVATIONS"] if not rows else []
    if rows:
        health, reasons = "Normal", ["CHECKS_PASS"]
        if hard_limit is not None and drawdown <= -abs(hard_limit):
            health, reasons = "Breached", ["HARD_DRAWDOWN_LIMIT"]
    return {
        "days_observed": len(rows), "first_event_time": min(event_times).isoformat() if event_times else None,
        "last_event_time": last.isoformat() if last else None, "mtd_return": compounded(monthly.get(current_month, [])) if current_month in monthly else None,
        "trailing_returns": trailing, "recent_completed_months": completed[-3:], "current_drawdown": drawdown if rows else None,
        "max_drawdown": worst if rows else None, "drawdown_duration_observations": underwater if rows else None,
        "realized_volatility": volatility, "sharpe": sharpe, "equity_curve": curve[-400:], "health": health, "reason_codes": reasons,
    }


def portfolio_snapshot(repository: PortfolioRepository, cutoff_value: str | None = None) -> dict[str, Any]:
    cutoff = parse_time(cutoff_value) if cutoff_value else datetime.now(timezone.utc)
    settings = repository.settings()
    staleness = number(settings.get("staleness_days"))
    assessments: list[dict[str, Any]] = []
    return_maps: dict[str, dict[str, float]] = {}
    for strategy in repository.strategies(cutoff.isoformat()):
        known_time_value = strategy.get("selection_date") or strategy.get("created_at")
        known_time = parse_time(str(known_time_value)) if known_time_value else None
        chronology_status = "Point-in-time" if known_time and known_time <= cutoff else "Retrospective"
        if chronology_status == "Retrospective":
            strategy["eligibility"] = "Provisional"
            strategy["eligibility_reason_codes"] = ["VERSION_NOT_KNOWN_AT_CUTOFF"]
        observations = repository.observations(strategy["id"], cutoff.isoformat())
        reference_returns = return_rows(observations, "reference")
        live_returns = return_rows(observations, "live")
        paper_returns = return_rows(observations, "paper")
        current_returns = live_returns or paper_returns
        reference_metrics = metrics_for(reference_returns, cutoff, number(strategy.get("hard_drawdown_limit")))
        current_metrics = metrics_for(current_returns, cutoff, number(strategy.get("hard_drawdown_limit")))
        # Current behavior uses live or paper marks. Frozen reference metrics
        # are retained separately for performance-allocation research.
        metrics = current_metrics
        last = parse_time(current_metrics["last_event_time"]) if current_metrics["last_event_time"] else None
        freshness_days = elapsed_expected_sessions(last, cutoff) if last else None
        if current_returns and metrics["health"] != "Breached" and staleness is not None and freshness_days is not None and freshness_days > staleness:
            metrics["health"] = "Unknown"
            metrics["reason_codes"] = ["STALE_RETURN_DATA"]
        positions = [row for row in observations if row.get("observation_type") == "position"]
        latest_position = positions[-1] if positions else None
        fills = [row for row in observations if row.get("observation_type") == "fill"]
        rejected_orders = sum(str(row.get("status", "")).lower() == "rejected" for row in fills)
        filled_orders = sum(str(row.get("status", "filled")).lower() in {"filled", "partial"} for row in fills)
        slippages = [value for value in (number(row.get("slippage")) for row in fills) if value is not None]
        delays = [value for value in (number(row.get("execution_delay_seconds")) for row in fills) if value is not None]
        fees = sum(number(row.get("fees")) or 0.0 for row in fills)
        current_exposure = number(latest_position.get("exposure")) if latest_position else number(strategy.get("current_exposure"))
        current_exposure = current_exposure or 0.0
        recorded_margin = number(latest_position.get("margin")) if latest_position else None
        hard_margin = number(strategy.get("hard_margin_limit"))
        if hard_margin is not None and recorded_margin is not None and recorded_margin > hard_margin:
            metrics["health"], metrics["reason_codes"] = "Breached", ["HARD_MARGIN_LIMIT"]
        watch_window = number(settings.get("watch_window_observations"))
        watch_fraction = number(settings.get("watch_negative_fraction"))
        if metrics["health"] == "Normal" and watch_window is not None and watch_fraction is not None:
            window = max(1, int(watch_window))
            values = [row["net_return"] for row in current_returns[-window:]]
            if len(values) == window and sum(value < 0 for value in values) / window >= watch_fraction:
                metrics["health"], metrics["reason_codes"] = "Watch", ["CONFIGURED_RECENT_RETURN_ANOMALY"]
        assessment = {
            **strategy, **metrics, "assessment_time": cutoff.isoformat(), "data_freshness_days": freshness_days,
            "chronology_status": chronology_status,
            "current_exposure": current_exposure, "actual_position_time": latest_position.get("event_time") if latest_position else None,
            "allocation_state": "No current proposal", "proposed_exposure": None, "allocation_reason_codes": ["POLICY_NOT_EVALUATED"],
            "policy_version": settings.get("policy_version"), "next_review_time": None,
            "data_freshness_unit": "expected weekday sessions",
            "history_coverage": {"live": len(live_returns), "paper": len(paper_returns), "reference": len(reference_returns), "backtest": len(return_rows(observations, "backtest"))},
            "live_equity_curve": metrics_for(live_returns, cutoff, None)["equity_curve"],
            "reference_equity_curve": reference_metrics["equity_curve"],
            "reference_metrics": {key: reference_metrics[key] for key in ("mtd_return", "trailing_returns", "current_drawdown", "max_drawdown", "realized_volatility", "sharpe", "days_observed", "last_event_time")},
            "live_reference_gap": (
                metrics_for(live_returns, cutoff, None)["equity_curve"][-1]["equity"] - reference_metrics["equity_curve"][-1]["equity"]
                if live_returns and reference_returns else None
            ),
            "feature_availability": {"current_performance": bool(current_returns), "reference_performance": bool(reference_returns),
                                     "execution": bool(fills), "positions": bool(positions), "daily_risk": len(current_returns) > 1},
            "execution_diagnostics": {"orders_observed": len(fills), "filled_orders": filled_orders, "rejected_orders": rejected_orders,
                                      "fill_rate": filled_orders / len(fills) if fills else None,
                                      "average_slippage": mean(slippages), "fees": fees if fills else None,
                                      "average_execution_delay_seconds": mean(delays)},
            "position_diagnostics": {"event_time": latest_position.get("event_time") if latest_position else None,
                                     "gross_exposure": number(latest_position.get("gross_exposure")) if latest_position else None,
                                     "net_exposure": number(latest_position.get("net_exposure")) if latest_position else None,
                                     "margin": recorded_margin,
                                     "liquidity_usage": number(latest_position.get("liquidity_usage")) if latest_position else None},
        }
        assessments.append(assessment)
        return_maps[strategy["id"]] = {row["event_time"][:10]: row["net_return"] for row in reference_returns}

    required_config = ["calendar", "review_cadence", "staleness_days", "portfolio_volatility_budget", "volatility_floor", "gross_exposure_limit", "margin_limit", "decision_owner", "outage_procedure"]
    missing_config = [key for key in required_config if settings.get(key) in (None, "")]
    cadence = str(settings.get("review_cadence") or "").lower()
    if "month" in cadence:
        next_month = (cutoff.replace(day=1) + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_review_time = next_month.isoformat()
    elif "day" in cadence:
        next_review_time = (cutoff + timedelta(days=1)).isoformat()
    else:
        next_review_time = None
    policy_approved = settings.get("policy_state") == "Approved for allocation proposals"
    preliminary: dict[str, float] = {}
    for item in assessments:
        item["next_review_time"] = next_review_time
        reasons: list[str] = []
        proposed: float | None = None
        state = "No current proposal"
        if item["health"] == "Breached":
            proposed, state, reasons = 0.0, "Paused", ["HARD_RISK_CONTAINMENT"]
        elif item["health"] == "Unknown":
            reasons = ["CRITICAL_DATA_UNAVAILABLE"]
        elif item["eligibility"] != "Qualified":
            reasons = ["RESEARCH_NOT_QUALIFIED"]
        elif missing_config:
            reasons = ["CONFIGURATION_INCOMPLETE"]
        elif not policy_approved:
            reasons = ["POLICY_NOT_APPROVED_FOR_ALLOCATION"]
        else:
            fixed = number(item.get("base_allocation"))
            budget = number(item.get("standalone_volatility_budget"))
            vol = number(item.get("realized_volatility"))
            floor = number(settings.get("volatility_floor"))
            if budget is not None and vol is not None and floor is not None:
                proposed = budget / max(vol, floor)
            elif fixed is not None:
                proposed = fixed
            else:
                reasons = ["STRATEGY_BUDGET_UNCONFIGURED"]
            cap = number(item.get("exposure_cap"))
            if proposed is not None and cap is not None and proposed > cap:
                proposed, reasons = cap, ["STRATEGY_CAP_BINDS"]
            if proposed is not None:
                preliminary[item["id"]] = max(0.0, proposed)
                state = "Base" if abs(proposed - (fixed if fixed is not None else proposed)) < 1e-12 else "Reduced"
                reasons = reasons or ["BASE_POLICY"]
        item["proposed_exposure"], item["allocation_state"], item["allocation_reason_codes"] = proposed, state, reasons

    gross_limit = number(settings.get("gross_exposure_limit"))
    gross = sum(preliminary.values())
    if gross_limit is not None and gross > gross_limit and gross > 0:
        scale = gross_limit / gross
        for item in assessments:
            if item["id"] in preliminary:
                item["proposed_exposure"] = preliminary[item["id"]] * scale
                item["allocation_state"] = "Reduced"
                item["allocation_reason_codes"] = [*item["allocation_reason_codes"], "PORTFOLIO_GROSS_LIMIT"]

    margin_limit = number(settings.get("margin_limit"))
    proposed_margin = sum(abs(number(item.get("proposed_exposure")) or 0.0) * (number(item.get("margin_per_exposure")) or 0.0) for item in assessments)
    if margin_limit is not None and proposed_margin > margin_limit and proposed_margin > 0:
        scale = margin_limit / proposed_margin
        for item in assessments:
            if item["proposed_exposure"] is not None and item["allocation_state"] != "Paused":
                item["proposed_exposure"] *= scale
                item["allocation_state"] = "Reduced"
                item["allocation_reason_codes"] = [*item["allocation_reason_codes"], "PORTFOLIO_MARGIN_LIMIT"]
        proposed_margin = margin_limit

    ids = [item["id"] for item in assessments]
    correlations: list[list[float | None]] = []
    covariance_matrix: list[list[float | None]] = []
    for left in ids:
        cov_row, corr_row = [], []
        for right in ids:
            common = sorted(set(return_maps[left]) & set(return_maps[right]))[-252:]
            a, b = [return_maps[left][date] for date in common], [return_maps[right][date] for date in common]
            cov = covariance(a, b)
            sa, sb = sample_std(a), sample_std(b)
            corr = cov / (sa * sb) if cov is not None and sa not in (None, 0) and sb not in (None, 0) else (1.0 if left == right and a else None)
            cov_row.append(cov * 252 if cov is not None else None)
            corr_row.append(corr)
        covariance_matrix.append(cov_row)
        correlations.append(corr_row)
    weights = [number(item.get("proposed_exposure")) or 0.0 for item in assessments]
    variance = sum(weights[i] * weights[j] * (covariance_matrix[i][j] or 0.0) for i in range(len(ids)) for j in range(len(ids)))
    portfolio_vol = math.sqrt(max(0.0, variance)) if any(any(value is not None for value in row) for row in covariance_matrix) else None
    vol_budget = number(settings.get("portfolio_volatility_budget"))
    if portfolio_vol is not None and vol_budget is not None and portfolio_vol > vol_budget and portfolio_vol > 0:
        scale = vol_budget / portfolio_vol
        for item in assessments:
            if item["proposed_exposure"] is not None and item["allocation_state"] != "Paused":
                item["proposed_exposure"] *= scale
                item["allocation_state"] = "Reduced"
                item["allocation_reason_codes"] = [*item["allocation_reason_codes"], "PORTFOLIO_VOLATILITY_LIMIT"]
        weights = [number(item.get("proposed_exposure")) or 0.0 for item in assessments]
        portfolio_vol = vol_budget
    contributions = []
    for index, weight in enumerate(weights):
        marginal = sum((covariance_matrix[index][j] or 0.0) * weights[j] for j in range(len(ids)))
        contribution = weight * marginal / portfolio_vol if portfolio_vol not in (None, 0) else None
        contributions.append(contribution)
        assessments[index]["risk_contribution"] = contribution
    actual_gross = sum(abs(number(item.get("current_exposure")) or 0.0) for item in assessments)
    proposed_gross = sum(abs(number(item.get("proposed_exposure")) or 0.0) for item in assessments if item.get("proposed_exposure") is not None)
    proposed_margin = sum(abs(number(item.get("proposed_exposure")) or 0.0) * (number(item.get("margin_per_exposure")) or 0.0) for item in assessments)
    actual_net = sum(number(item.get("current_exposure")) or 0.0 for item in assessments)
    proposed_net = sum(number(item.get("proposed_exposure")) or 0.0 for item in assessments if item.get("proposed_exposure") is not None)
    actual_margin = sum(number(item.get("position_diagnostics", {}).get("margin")) or 0.0 for item in assessments)
    unallocated = max(0.0, 1.0 - proposed_gross) if not missing_config else None
    critical_events = sum(item["health"] in {"Breached", "Unknown"} for item in assessments)
    prior_decisions = repository.decisions(1)
    last_cutoff = parse_time(prior_decisions[0]["cutoff"]) if prior_decisions else None
    review_due = False
    review_reason = "CONFIGURATION_INCOMPLETE" if missing_config else "NOT_DUE"
    if not missing_config:
        if any(item["health"] == "Breached" for item in assessments):
            review_due, review_reason = True, "HARD_RISK_EVENT"
        elif last_cutoff is None:
            review_due, review_reason = True, "NO_PRIOR_DECISION"
        elif "day" in cadence and last_cutoff.date() < cutoff.date():
            review_due, review_reason = True, "DAILY_REVIEW_DUE"
        elif "month" in cadence and (last_cutoff.year, last_cutoff.month) < (cutoff.year, cutoff.month):
            review_due, review_reason = True, "MONTH_END_REVIEW_DUE"
    return {
        "as_of": cutoff.isoformat(), "calculation_version": CALCULATION_VERSION, "settings": settings,
        "configuration_complete": not missing_config, "missing_configuration": missing_config,
        "strategies": assessments, "portfolio": {"actual_gross_exposure": actual_gross,
        "proposed_gross_exposure": proposed_gross if any(item.get("proposed_exposure") is not None for item in assessments) else None,
        "portfolio_volatility": portfolio_vol, "unallocated_capital": unallocated, "critical_events": critical_events,
        "actual_net_exposure": actual_net, "proposed_net_exposure": proposed_net,
        "actual_margin": actual_margin, "proposed_margin": proposed_margin,
        "stress_loss_10pct": proposed_gross * 0.10,
        "review_due": review_due, "review_reason": review_reason,
        "last_decision_cutoff": last_cutoff.isoformat() if last_cutoff else None,
        "monitoring_frequency": "assessment on import; interface refresh every 60 seconds",
        "correlation_labels": ids, "correlation_matrix": correlations, "covariance_matrix": covariance_matrix,
        "risk_contributions": contributions},
    }


def proposal_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    fields = ("id", "name", "version", "current_exposure", "proposed_exposure", "allocation_state", "allocation_reason_codes", "health", "reason_codes", "eligibility")
    return [{key: item.get(key) for key in fields} for item in snapshot["strategies"]]


def decision_portfolio(snapshot: dict[str, Any]) -> dict[str, Any]:
    operational = {"review_due", "review_reason", "last_decision_cutoff", "monitoring_frequency"}
    return {key: value for key, value in snapshot["portfolio"].items() if key not in operational}


def build_decision(repository: PortfolioRepository, cutoff: str | None = None, effective_time: str | None = None) -> dict[str, Any]:
    snapshot = portfolio_snapshot(repository, cutoff)
    cutoff_value = snapshot["as_of"]
    if effective_time:
        effective = parse_time(effective_time)
        if effective < parse_time(cutoff_value):
            raise ValueError("Effective time cannot precede the decision cutoff")
    else:
        effective = parse_time(cutoff_value) + timedelta(days=1)
    input_material = {
        "cutoff": cutoff_value, "settings": snapshot["settings"],
        "strategies": [{"record": repository.strategy(item["id"]), "eligibility_history": repository.eligibility_history(item["id"], cutoff_value),
                        "observations": repository.observations(item["id"], cutoff_value)} for item in snapshot["strategies"]],
    }
    proposals = proposal_rows(snapshot)
    portfolio_output = decision_portfolio(snapshot)
    output_material = {"proposals": proposals, "portfolio": portfolio_output}
    return {
        "id": f"decision-{uuid.uuid4().hex[:12]}", "created_at": utc_now(), "cutoff": cutoff_value,
        "effective_time": effective.isoformat(), "snapshot_hash": stable_hash(input_material),
        "policy_version": snapshot["settings"].get("policy_version"), "calculation_version": CALCULATION_VERSION,
        "configuration_complete": snapshot["configuration_complete"], "missing_configuration": snapshot["missing_configuration"],
        "proposals": proposals, "output_hash": stable_hash(output_material),
        "portfolio": portfolio_output, "override": None,
        "input_snapshot": input_material,
    }


def reproduce_decision(decision: dict[str, Any]) -> dict[str, Any]:
    input_snapshot = decision.get("input_snapshot")
    if not isinstance(input_snapshot, dict):
        return {"reproduced": False, "reason": "Decision predates sealed input snapshots"}
    with tempfile.TemporaryDirectory() as folder:
        repository = PortfolioRepository(Path(folder) / "reproduce.sqlite3")
        settings = {key: input_snapshot.get("settings", {}).get(key) for key in DEFAULT_SETTINGS}
        repository.update_settings(settings)
        with repository.connect() as connection:
            for item in input_snapshot.get("strategies", []):
                record = item.get("record")
                if not isinstance(record, dict):
                    continue
                connection.execute(
                    "INSERT INTO strategy_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (record["id"], record["strategy_id"], record["name"], record["version"], record["created_at"], record["eligibility"], json.dumps(record)),
                )
                for eligibility in reversed(item.get("eligibility_history", [])):
                    connection.execute(
                        "INSERT INTO eligibility_assessments VALUES (?, ?, ?, ?, ?)",
                        (eligibility["id"], record["id"], eligibility["assessment_time"], eligibility["eligibility"], json.dumps(eligibility)),
                    )
                for observation in item.get("observations", []):
                    payload = {key: value for key, value in observation.items() if key != "id"}
                    connection.execute(
                        "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (observation["id"], record["id"], observation["event_time"], observation["availability_time"],
                         observation["observation_type"], utc_now(), None, json.dumps(payload)),
                    )
        recalculated = portfolio_snapshot(repository, input_snapshot["cutoff"])
        proposals = proposal_rows(recalculated)
        portfolio_output = decision_portfolio(recalculated)
        output_hash = stable_hash({"proposals": proposals, "portfolio": portfolio_output})
        expected_hash = decision.get("output_hash") or stable_hash({"proposals": decision.get("proposals"), "portfolio": decision.get("portfolio")})
        return {"reproduced": output_hash == expected_hash, "expected_output_hash": expected_hash,
                "actual_output_hash": output_hash, "proposals": proposals, "portfolio": portfolio_output}


def what_if_snapshot(repository: PortfolioRepository, payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = portfolio_snapshot(repository, payload.get("cutoff"))
    paused = set(payload.get("paused_strategy_ids", []))
    reductions = payload.get("exposure_multipliers", {})
    if not isinstance(reductions, dict):
        raise ValueError("exposure_multipliers must be an object")
    weights = []
    for item in snapshot["strategies"]:
        original = item.get("proposed_exposure")
        multiplier = number(reductions.get(item["id"], 1.0))
        if multiplier is None or multiplier < 0 or multiplier > 1:
            raise ValueError("What-if multipliers must be between zero and one")
        proposed = 0.0 if item["id"] in paused else (original * multiplier if original is not None else None)
        item["what_if_exposure"] = proposed
        weights.append(proposed or 0.0)
    covariance_matrix = snapshot["portfolio"]["covariance_matrix"]
    variance = sum(weights[i] * weights[j] * (covariance_matrix[i][j] or 0.0) for i in range(len(weights)) for j in range(len(weights)))
    gross = sum(abs(value) for value in weights)
    snapshot["what_if"] = {"gross_exposure": gross, "portfolio_volatility": math.sqrt(max(0.0, variance)),
                           "unallocated_capital": max(0.0, 1.0 - gross), "paused_strategy_ids": sorted(paused)}
    return snapshot


def experiment_result(repository: PortfolioRepository, payload: dict[str, Any]) -> dict[str, Any]:
    universe = payload.get("strategy_version_ids")
    if not isinstance(universe, list) or not universe:
        raise ValueError("Select at least one strategy version")
    start, end = payload.get("start"), payload.get("end")
    if not start or not end or parse_time(start) >= parse_time(end):
        raise ValueError("A valid chronological start and end are required")
    costs = number(payload.get("resizing_cost_bps"))
    if costs is None or costs < 0:
        raise ValueError("resizing_cost_bps must be non-negative")
    for field in ("primary_objective", "minimum_meaningful_improvement", "acceptable_return_sacrifice"):
        if payload.get(field) in (None, ""):
            raise ValueError(f"{field} must be declared before the experiment")
    cost_stress = number(payload.get("cost_stress_bps"))
    if cost_stress is None or cost_stress < costs:
        raise ValueError("cost_stress_bps must be at least the base resizing cost")
    series: dict[str, dict[str, float]] = {}
    for version_id in universe:
        if not repository.strategy(version_id):
            raise ValueError(f"Unknown strategy version: {version_id}")
        rows = return_rows(repository.observations(version_id, end), "reference")
        series[version_id] = {row["event_time"][:10]: row["net_return"] for row in rows if start <= row["event_time"] <= end}
    dates = sorted(set.intersection(*(set(values) for values in series.values()))) if series else []
    if len(dates) < 20:
        outcome = {"status": "Inconclusive", "reason": "Fewer than 20 aligned observations", "sample_size": len(dates), "comparators": []}
    else:
        fixed = [statistics.fmean(series[key][date] for key in universe) for date in dates]
        lower = [value * 0.7 for value in fixed]
        rolling_vols: dict[str, list[float]] = {key: [] for key in universe}
        vol_scaled = []
        for index, date in enumerate(dates):
            contributions = []
            for key in universe:
                history = [series[key][item] for item in dates[max(0, index - 20):index]]
                vol = sample_std(history)
                contributions.append(series[key][date] * min(2.0, 0.01 / max(vol or 0.01, 0.0025)))
                rolling_vols[key].append(vol or 0.0)
            vol_scaled.append(statistics.fmean(contributions))
        lookback = int(payload.get("lookback_days", 63))
        reduced = number(payload.get("reduced_multiplier"))
        reduced = 0.5 if reduced is None else max(0.0, min(reduced, 1.0))
        proposed = []
        proposed_stressed = []
        last_multiplier = 1.0
        turnover = 0.0
        for index, value in enumerate(fixed):
            history = fixed[max(0, index - lookback):index]
            multiplier = reduced if history and compounded(history) < 0 else 1.0
            change = abs(multiplier - last_multiplier)
            turnover += change
            proposed.append(value * multiplier - change * costs / 10000)
            proposed_stressed.append(value * multiplier - change * cost_stress / 10000)
            last_multiplier = multiplier

        def summarize(name: str, values: list[float]) -> dict[str, Any]:
            std = sample_std(values)
            equity, peak, worst = 1.0, 1.0, 0.0
            for value in values:
                equity *= 1 + value
                peak = max(peak, equity)
                worst = min(worst, equity / peak - 1)
            return {"name": name, "net_compound_return": equity - 1, "annualized_volatility": std * math.sqrt(252) if std is not None else None,
                    "sharpe": statistics.fmean(values) / std * math.sqrt(252) if std not in (None, 0) else None,
                    "max_drawdown": worst, "observations": len(values)}
        comparators = [summarize("Always-on fixed", fixed), summarize("Earlier-calibrated lower fixed (0.7×)", lower),
                       summarize("Always-on volatility-scaled", vol_scaled), summarize("Candidate timing policy", proposed),
                       summarize("Candidate timing policy — cost stress", proposed_stressed)]
        differences = [candidate - baseline for candidate, baseline in zip(proposed, fixed)]
        generator = random.Random(int(payload.get("random_seed", 1729)))
        bootstrapped = []
        block = min(5, len(differences))
        for _ in range(500):
            sampled: list[float] = []
            while len(sampled) < len(differences):
                start_index = generator.randrange(0, max(1, len(differences) - block + 1))
                sampled.extend(differences[start_index:start_index + block])
            bootstrapped.append(statistics.fmean(sampled[:len(differences)]))
        bootstrapped.sort()
        interval = [bootstrapped[int(len(bootstrapped) * 0.025)], bootstrapped[int(len(bootstrapped) * 0.975) - 1]]
        outcome = {"status": "Complete", "sample_size": len(dates), "comparators": comparators,
                   "paired_mean_return_difference": statistics.fmean(differences), "paired_block_bootstrap_95_interval": interval,
                   "turnover_units": turnover, "random_seed": int(payload.get("random_seed", 1729)),
                   "warning": "Exploratory chronological comparison. Approval requires a declared untouched evaluation and uncertainty review."}
    return repository.save_experiment({**payload, "state": "Exploratory", "result": outcome})
