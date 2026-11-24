"""Read-only Databento price estimates. This script cannot download market data."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

import databento as db
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "data_quote.json"


def main():
    key = os.environ.get("DATABENTO_API_KEY") or dotenv_values(ROOT / ".env").get("DATABENTO_API_KEY")
    if not key:
        raise RuntimeError("Databento credential is not configured")
    client = db.Historical(key)
    entries = []
    for label, start, end in [
        ("development_2019_2023", "2019-05-06T13:30:00Z", "2024-01-01T00:00:00Z"),
        ("evaluation_2024_only_if_development_passes", "2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    ]:
        request = dict(dataset="GLBX.MDP3", symbols=["MNQ.v.0"], stype_in="continuous",
                       schema="trades", start=start, end=end)
        item = dict(label=label, request=request)
        try:
            item["estimated_cost_usd"] = float(client.metadata.get_cost(**request))
            item["billable_uncompressed_bytes"] = int(client.metadata.get_billable_size(**request))
        except Exception as error:
            # Avoid including credentials or request headers in exception output.
            item["error_type"] = type(error).__name__
        entries.append(item)
        print(json.dumps(item), flush=True)
    result = dict(quoted_at_utc=datetime.now(timezone.utc).isoformat(),
                  purpose="Price discovery only; no purchase or market-data request made",
                  quote_scope="Full calendar intervals including overnight data; opening-window requests may cost less",
                  estimate_is_not_a_provider_enforced_spending_cap=True,
                  entries=entries)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
