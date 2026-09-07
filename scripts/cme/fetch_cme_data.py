"""Pull daily history for CME Group products (via PWB proxies) into a local cache.

Papers With Backtest has no dataset called "CME". The CME Group complex
(CME / CBOT / NYMEX / COMEX) is spread across four daily datasets, and each
listed contract is represented by a cash, spot, or continuous-front proxy:

    Indices-Daily-Price      SPX, NDX, RTY, INDU, NKY   -> ES, NQ, RTY, YM, NKD
    Bonds-Daily-Price        US2Y ... US30Y             -> ZT, ZF, ZN, ZB
    Forex-Daily-Price        EURUSD ...                 -> 6E, 6J, 6B, ...
    Commodities-Daily-Price  CL1, GC1, C1, LC1, ...     -> CL, GC, ZC, LE, ...

Important caveats before running statistics on the output:

* These are proxies, not futures. No roll returns, no contract multipliers,
  no margin, no exchange fees. Momentum/vol/correlation statistics survive
  this; carry, roll-yield, and term-structure statistics do not.
* The bond series are PRICE indices (they rise when yields fall), verified
  against the 2020 low-yield and 2023 high-yield regimes. They are not
  duration-matched to ZT/ZF/ZN/ZB, so cross-tenor vol ratios are indicative.
* FX proxies quote USD per unit of foreign currency (EURUSD, JPYUSD, ...),
  the same direction as the CME contracts.
* PA (palladium) has no continuous future in PWB; spot XPDUSD stands in.

Usage:

    python fetch_cme_data.py                    # cached pull, all sectors
    python fetch_cme_data.py --refresh          # ignore the cache
    python fetch_cme_data.py --sectors energy,metals
    python fetch_cme_data.py --include-reference   # add non-CME comparators
    python fetch_cme_data.py --start 2000-01-01
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


# Load the workspace's dataset-only PWB key without printing it.
_env_path = (Path(__file__).resolve().parents[2] / ".env")
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip())

import pwb_toolbox.datasets as pwb_ds


DATA_DIR = (Path(__file__).resolve().parents[2] / "data")
PANEL_PATH = DATA_DIR / "cme_daily.parquet"
UNIVERSE_PATH = DATA_DIR / "cme_universe.csv"


@dataclass(frozen=True)
class Contract:
    market: str  # CME ticker root
    name: str
    exchange: str  # CME / CBOT / NYMEX / COMEX, or the listing venue for reference rows
    sector: str
    dataset: str
    symbol: str  # PWB proxy symbol
    proxy: str
    reference: bool = False  # True = not a CME Group listing, carried for context


CONTRACTS: tuple[Contract, ...] = (
    # --- CME: equity index ---------------------------------------------
    Contract("ES", "E-mini S&P 500", "CME", "equity_index", "Indices-Daily-Price", "SPX", "SPX cash index"),
    Contract("NQ", "E-mini Nasdaq 100", "CME", "equity_index", "Indices-Daily-Price", "NDX", "NDX cash index"),
    Contract("RTY", "E-mini Russell 2000", "CME", "equity_index", "Indices-Daily-Price", "RTY", "RTY cash index"),
    Contract("YM", "E-mini Dow", "CME", "equity_index", "Indices-Daily-Price", "INDU", "Dow Jones cash index"),
    Contract("NKD", "Nikkei 225 (USD)", "CME", "equity_index", "Indices-Daily-Price", "NKY", "Nikkei 225 cash index"),
    # --- CBOT: interest rates ------------------------------------------
    Contract("ZT", "2-Year T-Note", "CBOT", "rates", "Bonds-Daily-Price", "US2Y", "US 2Y bond price index"),
    Contract("ZF", "5-Year T-Note", "CBOT", "rates", "Bonds-Daily-Price", "US5Y", "US 5Y bond price index"),
    Contract("ZN", "10-Year T-Note", "CBOT", "rates", "Bonds-Daily-Price", "US10Y", "US 10Y bond price index"),
    Contract("ZB", "30-Year T-Bond", "CBOT", "rates", "Bonds-Daily-Price", "US30Y", "US 30Y bond price index"),
    # --- CME: FX ---------------------------------------------------------
    Contract("6E", "Euro FX", "CME", "fx", "Forex-Daily-Price", "EURUSD", "EURUSD spot"),
    Contract("6J", "Japanese Yen", "CME", "fx", "Forex-Daily-Price", "JPYUSD", "JPYUSD spot"),
    Contract("6B", "British Pound", "CME", "fx", "Forex-Daily-Price", "GBPUSD", "GBPUSD spot"),
    Contract("6A", "Australian Dollar", "CME", "fx", "Forex-Daily-Price", "AUDUSD", "AUDUSD spot"),
    Contract("6C", "Canadian Dollar", "CME", "fx", "Forex-Daily-Price", "CADUSD", "CADUSD spot"),
    Contract("6S", "Swiss Franc", "CME", "fx", "Forex-Daily-Price", "CHFUSD", "CHFUSD spot"),
    Contract("6N", "New Zealand Dollar", "CME", "fx", "Forex-Daily-Price", "NZDUSD", "NZDUSD spot"),
    Contract("6M", "Mexican Peso", "CME", "fx", "Forex-Daily-Price", "MXNUSD", "MXNUSD spot"),
    Contract("6L", "Brazilian Real", "CME", "fx", "Forex-Daily-Price", "BRLUSD", "BRLUSD spot"),
    Contract("6Z", "South African Rand", "CME", "fx", "Forex-Daily-Price", "ZARUSD", "ZARUSD spot"),
    Contract("CNH", "USD/Offshore RMB", "CME", "fx", "Forex-Daily-Price", "CNHUSD", "CNHUSD spot"),
    # --- NYMEX: energy ---------------------------------------------------
    Contract("CL", "WTI Crude Oil", "NYMEX", "energy", "Commodities-Daily-Price", "CL1", "CL1 continuous front"),
    Contract("NG", "Henry Hub Natural Gas", "NYMEX", "energy", "Commodities-Daily-Price", "NG1", "NG1 continuous front"),
    Contract("HO", "NY Harbor ULSD", "NYMEX", "energy", "Commodities-Daily-Price", "HO1", "HO1 continuous front"),
    Contract("RB", "RBOB Gasoline", "NYMEX", "energy", "Commodities-Daily-Price", "XB1", "XB1 continuous front"),
    # --- COMEX: metals ---------------------------------------------------
    Contract("GC", "Gold", "COMEX", "metals", "Commodities-Daily-Price", "GC1", "GC1 continuous front"),
    Contract("SI", "Silver", "COMEX", "metals", "Commodities-Daily-Price", "SI1", "SI1 continuous front"),
    Contract("HG", "Copper", "COMEX", "metals", "Commodities-Daily-Price", "HG1", "HG1 continuous front"),
    Contract("PL", "Platinum", "NYMEX", "metals", "Commodities-Daily-Price", "PL1", "PL1 continuous front"),
    Contract("PA", "Palladium", "NYMEX", "metals", "Commodities-Daily-Price", "XPDUSD", "spot palladium (no future in PWB)"),
    # --- CBOT: grains ----------------------------------------------------
    Contract("ZC", "Corn", "CBOT", "grains", "Commodities-Daily-Price", "C1", "C1 continuous front"),
    Contract("ZS", "Soybeans", "CBOT", "grains", "Commodities-Daily-Price", "S1", "S1 continuous front"),
    Contract("ZW", "Chicago Wheat", "CBOT", "grains", "Commodities-Daily-Price", "W1", "W1 continuous front"),
    Contract("ZO", "Oats", "CBOT", "grains", "Commodities-Daily-Price", "O1", "O1 continuous front"),
    Contract("ZR", "Rough Rice", "CBOT", "grains", "Commodities-Daily-Price", "RR1", "RR1 continuous front"),
    # --- CME: livestock and other ----------------------------------------
    Contract("LE", "Live Cattle", "CME", "livestock", "Commodities-Daily-Price", "LC1", "LC1 continuous front"),
    Contract("GF", "Feeder Cattle", "CME", "livestock", "Commodities-Daily-Price", "FC1", "FC1 continuous front"),
    Contract("HE", "Lean Hogs", "CME", "livestock", "Commodities-Daily-Price", "LH1", "LH1 continuous front"),
    Contract("LBR", "Lumber", "CME", "softs", "Commodities-Daily-Price", "LB1", "LB1 continuous front"),
    Contract("DC", "Class III Milk", "CME", "softs", "Commodities-Daily-Price", "DL1", "DL1 continuous front"),
    # --- Reference: not CME Group, useful comparators --------------------
    Contract("BZ", "Brent Crude", "ICE", "energy", "Commodities-Daily-Price", "CO1", "CO1 continuous front", True),
    Contract("KC", "Coffee", "ICE", "softs", "Commodities-Daily-Price", "KC1", "KC1 continuous front", True),
    Contract("CC", "Cocoa", "ICE", "softs", "Commodities-Daily-Price", "CC1", "CC1 continuous front", True),
    Contract("CT", "Cotton", "ICE", "softs", "Commodities-Daily-Price", "CT1", "CT1 continuous front", True),
    Contract("SB", "Sugar #11", "ICE", "softs", "Commodities-Daily-Price", "SB1", "SB1 continuous front", True),
    Contract("VX", "VIX", "CFE", "volatility", "Indices-Daily-Price", "VIX", "VIX cash index", True),
)

SECTORS = tuple(dict.fromkeys(c.sector for c in CONTRACTS))
REQUIRED_COLUMNS = ("symbol", "date", "open", "high", "low", "close")


def select_contracts(sectors: tuple[str, ...] | None, include_reference: bool) -> list[Contract]:
    chosen = [c for c in CONTRACTS if include_reference or not c.reference]
    if sectors:
        unknown = set(sectors) - set(SECTORS)
        if unknown:
            raise SystemExit(f"unknown sector(s): {sorted(unknown)}; pick from {list(SECTORS)}")
        chosen = [c for c in chosen if c.sector in sectors]
    if not chosen:
        raise SystemExit("no contracts selected")
    return chosen


def fetch(contracts: list[Contract]) -> pd.DataFrame:
    """Load each PWB dataset once, then slice out the proxies it holds."""
    by_dataset: dict[str, list[Contract]] = {}
    for contract in contracts:
        by_dataset.setdefault(contract.dataset, []).append(contract)

    frames: list[pd.DataFrame] = []
    for dataset, group in by_dataset.items():
        symbols = sorted({c.symbol for c in group})
        print(f"[fetch] {dataset}: {len(symbols)} symbols")
        raw = pwb_ds.load_dataset(dataset, symbols=symbols).copy()

        missing = set(REQUIRED_COLUMNS).difference(raw.columns)
        if missing:
            raise ValueError(f"{dataset} is missing {sorted(missing)}")
        if "volume" not in raw.columns:
            raw["volume"] = pd.NA

        raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            raw[column] = pd.to_numeric(raw[column], errors="coerce")
        raw = raw.dropna(subset=["symbol", "date", "close"])

        for contract in group:
            slice_ = raw.loc[raw["symbol"].eq(contract.symbol)]
            if slice_.empty:
                print(f"[warn] {contract.market}: proxy {contract.symbol} returned no rows; skipped")
                continue
            slice_ = (
                slice_.drop_duplicates("date", keep="last")
                .sort_values("date")
                .assign(
                    market=contract.market,
                    name=contract.name,
                    exchange=contract.exchange,
                    sector=contract.sector,
                    dataset=contract.dataset,
                    proxy=contract.proxy,
                    is_reference=contract.reference,
                )
            )
            frames.append(slice_)

    if not frames:
        raise SystemExit("every proxy came back empty — check PWB_API_KEY and its expiry")

    panel = pd.concat(frames, ignore_index=True)
    columns = [
        "market", "name", "exchange", "sector", "symbol", "dataset", "proxy",
        "is_reference", "date", "open", "high", "low", "close", "volume",
    ]
    return panel[columns].sort_values(["market", "date"]).reset_index(drop=True)


def summarize(panel: pd.DataFrame) -> pd.DataFrame:
    """One row per market: coverage, gaps, and the level range, for eyeballing."""
    rows = []
    for market, group in panel.groupby("market", sort=False):
        group = group.sort_values("date")
        span_days = (group["date"].iloc[-1] - group["date"].iloc[0]).days
        rows.append(
            {
                "market": market,
                "name": group["name"].iloc[0],
                "exchange": group["exchange"].iloc[0],
                "sector": group["sector"].iloc[0],
                "proxy_symbol": group["symbol"].iloc[0],
                "proxy": group["proxy"].iloc[0],
                "is_reference": bool(group["is_reference"].iloc[0]),
                "rows": len(group),
                "start": group["date"].iloc[0].date(),
                "end": group["date"].iloc[-1].date(),
                "years": round(span_days / 365.25, 1),
                "rows_per_year": round(len(group) / max(span_days / 365.25, 1e-9), 1),
                "max_gap_days": int(group["date"].diff().dt.days.max() or 0),
                "min_close": round(float(group["close"].min()), 4),
                "max_close": round(float(group["close"].max()), 4),
                "last_close": round(float(group["close"].iloc[-1]), 4),
                "pct_volume_missing": round(float(group["volume"].isna().mean()) * 100, 1),
            }
        )
    order = {c.market: i for i, c in enumerate(CONTRACTS)}
    return pd.DataFrame(rows).sort_values("market", key=lambda s: s.map(order)).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sectors", type=str, default=None, help=f"comma-separated subset of {list(SECTORS)}")
    parser.add_argument("--include-reference", action="store_true", help="also pull non-CME comparators (Brent, ICE softs, VIX)")
    parser.add_argument("--start", type=str, default=None, help="drop rows before this date (YYYY-MM-DD)")
    parser.add_argument("--refresh", action="store_true", help="redownload even if the cache exists")
    parser.add_argument("--out", type=Path, default=PANEL_PATH, help=f"panel path (default {PANEL_PATH.name})")
    args = parser.parse_args()

    sectors = tuple(s.strip() for s in args.sectors.split(",")) if args.sectors else None
    contracts = select_contracts(sectors, args.include_reference)

    if args.out.exists() and not args.refresh:
        panel = pd.read_parquet(args.out)
        print(f"[cache] {args.out} ({len(panel):,} rows, {panel['market'].nunique()} markets) — use --refresh to repull")
    else:
        panel = fetch(contracts)
        DATA_DIR.mkdir(exist_ok=True)
        panel.to_parquet(args.out, index=False)
        print(f"[write] {args.out} ({len(panel):,} rows, {panel['market'].nunique()} markets)")

    if args.start:
        panel = panel.loc[panel["date"] >= pd.Timestamp(args.start)]

    universe = summarize(panel)
    universe.to_csv(UNIVERSE_PATH, index=False)
    print(f"[write] {UNIVERSE_PATH}\n")
    with pd.option_context("display.width", 200, "display.max_columns", 30, "display.max_rows", 100):
        print(universe.drop(columns=["proxy", "dataset"], errors="ignore").to_string(index=False))


if __name__ == "__main__":
    main()
