"""ES/NQ visits to the prior week's and month's extremes, from the new period open."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "artifacts/research/prior-period-extremes/periods.csv"
DATASETS = {
    "ES": "d61f072b19d996c2fbea57376c8ec4fb27f12fca01600ca1c1d626ab2feaac08-composite-v1",
    "NQ": "103505183967aae05f70a878b6ee6ce1952a517cc0fd5b78d40e40ec1682ecb3-composite-v1",
}
OHLC = ["open", "high", "low", "close"]


def load_bars(market):
    directory = ROOT / "data/workbench/datasets" / DATASETS[market]
    path = directory / "bars.parquet"
    meta = json.loads((directory / "dataset.json").read_text())
    assert meta["symbol"] == market and meta["tick_size"] == 0.25
    assert hashlib.sha256(path.read_bytes()).hexdigest() == meta["checksum"]
    bars = pd.read_parquet(path, columns=OHLC + ["instrument_id"]).loc["2015-11-15":].copy()
    assert bars.index.is_monotonic_increasing and bars.index.is_unique
    assert bars.notna().all().all() and (bars.low <= bars[["open", "close"]].min(axis=1)).all()
    assert (bars.high >= bars[["open", "close"]].max(axis=1)).all()

    # Express moves in a continuous price scale. Only contract switches are bridged.
    switch = bars.instrument_id.ne(bars.instrument_id.shift())
    switch.iloc[0] = False
    jump = bars.open.sub(bars.close.shift()).where(switch, 0.0)
    bars["offset"] = jump.cumsum()
    bars[OHLC] = bars[OHLC].sub(bars.offset, axis="index")
    local = bars.index.tz_convert("America/New_York").tz_localize(None)
    trading_date = (local + pd.Timedelta(hours=6)).normalize()
    # Workbench full trading day, from 18:00 to 17:00 Eastern the next weekday.
    keep = (trading_date.dayofweek < 5) & (local.hour != 17)
    bars = bars.loc[keep].copy()
    bars["date"] = trading_date[keep]
    starts = pd.Series(local[keep], index=trading_date[keep]).groupby(level=0).first()
    delay = starts - (starts.index - pd.Timedelta(hours=6))
    bars["late_session"] = bars.date.isin(delay[delay > pd.Timedelta(minutes=5)].index)
    return bars


def first_true(mask):
    return int(mask.argmax()) if mask.any() else None


def measure(current, level, side, distance):
    # Starting outside the old range still requires a return from the opening side.
    opening = current.open.iat[0]
    reached = current.high >= level if opening <= level else current.low <= level
    touch = first_true(reached.to_numpy())
    if touch is None:
        return "", "", "unfilled"
    # The fill minute's close is known to be at or after its qualifying print.
    closes = current.close.to_numpy()[touch:]
    outward = (closes - level) * (1 if side == "high" else -1)
    move = first_true(np.abs(outward) >= distance)
    touch_time = current.index[touch].isoformat()
    if move is None:
        return touch_time, "", "unresolved"
    outcome = "extension" if outward[move] > 0 else "rejection"
    return touch_time, current.index[touch + move].isoformat(), outcome


def study_periods(market, bars, name, frequency):
    # Both endpoints are visible in the pinned source. The last group is partial.
    periods = bars.groupby(bars.date.dt.to_period(frequency), sort=True)
    last = bars.date.iat[-1].to_period(frequency)
    previous = previous_key = None
    for key, current in periods:
        if previous is not None and previous_key + 1 != key:
            raise ValueError(f"Missing {name} before {key}")
        eligible = (
            previous is not None and key.start_time >= pd.Timestamp("2016-01-01")
            and key < last and not current.late_session.any() and not previous.late_session.any()
        )
        if eligible:
            opening = current.open.iat[0]
            offset = current.offset.iat[0]
            high, low = previous.high.max(), previous.low.min()
            assert high > low
            # Both the level and the target must be on the futures tick grid.
            distance = np.ceil((high - low) * 4 / 10) / 4
            record = {
                "market": market, "period": name, "period_start": key.start_time.date(),
                "first_trade_date": current.date.iat[0].date(),
                "last_trade_date": current.date.iat[-1].date(),
                "open_time_utc": current.index[0].isoformat(),
                "open": opening + offset, "prior_high": high + offset, "prior_low": low + offset,
                "reaction_points": distance,
                "includes_roll": previous.instrument_id.nunique() > 1
                or current.instrument_id.nunique() > 1
                or previous.instrument_id.iat[-1] != current.instrument_id.iat[0],
            }
            for side, level in [("high", high), ("low", low)]:
                fill, reaction, outcome = measure(current, level, side, distance)
                record[f"{side}_gap_points"] = abs(opening - level)
                record[f"{side}_fill_minute_utc"] = fill
                record[f"{side}_reaction_minute_utc"] = reaction
                record[f"{side}_outcome"] = outcome
            yield record
        previous_key, previous = key, current


def main():
    results = []
    for market in DATASETS:
        bars = load_bars(market)
        for name, frequency in [("week", "W-SUN"), ("month", "M")]:
            results.extend(study_periods(market, bars, name, frequency))
    table = pd.DataFrame(results)
    assert not table.duplicated(["market", "period", "period_start"]).any()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUTPUT, index=False)
    for (market, period), group in table.groupby(["market", "period"]):
        print(market, period, len(group), "periods")
        for side in ["high", "low"]:
            print(side, group[f"{side}_outcome"].value_counts().to_dict())


if __name__ == "__main__":
    main()
