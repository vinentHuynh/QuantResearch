from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Chart:
    id: str
    symbol: str
    name: str
    one_minute: str
    timeframe_dir: str
    tick_size: float
    point_value: float
    timezone: str = "America/New_York"
    source: str = "Databento GLBX.MDP3 continuous, volume roll"

    def path_1m(self) -> Path:
        return ROOT / self.one_minute

    def path_for_timeframe(self, timeframe: str) -> Path:
        return self.path_1m() if timeframe == "1m" else ROOT / self.timeframe_dir / f"candles_{timeframe}.parquet"


CHARTS: dict[str, Chart] = {
    "MNQ": Chart("MNQ", "MNQ", "Micro Nasdaq-100", "data/mnq_dom_sample/full_history/ohlcv-1m/candles_1m.parquet", "data/mnq_dom_sample/full_history/ohlcv-resampled", .25, 2),
    "NQ": Chart("NQ", "NQ", "E-mini Nasdaq-100", "data/root_charts/NQ/ohlcv-1m/candles_1m.parquet", "data/root_charts/NQ/ohlcv-resampled", .25, 20),
    "ES": Chart("ES", "ES", "E-mini S&P 500", "data/root_charts/ES/ohlcv-1m/candles_1m.parquet", "data/root_charts/ES/ohlcv-resampled", .25, 50),
    "YM": Chart("YM", "YM", "E-mini Dow", "data/root_charts/YM/ohlcv-1m/candles_1m.parquet", "data/root_charts/YM/ohlcv-resampled", 1, 5),
    "CL": Chart("CL", "CL", "WTI Crude Oil", "data/root_charts/CL/ohlcv-1m/candles_1m.parquet", "data/root_charts/CL/ohlcv-resampled", .01, 1000),
}


def file_fingerprint(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha256(f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()


def chart_metadata(chart: Chart) -> dict[str, Any]:
    value = asdict(chart)
    source_path = chart.path_1m()
    value["available"] = source_path.is_file()
    value["fingerprint"] = file_fingerprint(source_path) if source_path.is_file() else None
    manifest_path = ROOT / chart.timeframe_dir / "resample_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        value.update(rows=manifest.get("source_rows"), first_bar=manifest.get("source_first_bar"), last_bar=manifest.get("source_last_bar"), timeframes=list(manifest.get("timeframes", {})))
    else:
        value.update(rows=None, first_bar=None, last_bar=None, timeframes=[])
    return value
