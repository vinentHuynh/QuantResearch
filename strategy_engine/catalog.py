from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyManifest:
    """Identity and execution capabilities for one specific strategy."""

    id: str
    name: str
    version: str
    description: str
    timeframes: tuple[str, ...]
    sessions: tuple[str, ...]
    minimum_legs: int = 1
    maximum_legs: int = 1


STRATEGIES: dict[str, StrategyManifest] = {
    "multi-speed-momentum": StrategyManifest(
        id="multi-speed-momentum",
        name="Multi-speed time-series momentum",
        version="2.1.0",
        description="Combines four lagged momentum horizons into one long/short chart position.",
        timeframes=("30m", "1h", "4h", "1d"),
        sessions=("full-trading-day", "new-york-rth", "london", "asia"),
    ),
    "moving-average-trend": StrategyManifest(
        id="moving-average-trend",
        name="Moving-average trend",
        version="2.1.0",
        description="Holds a chart long while its prior close is above its moving average.",
        timeframes=("30m", "1h", "4h", "1d"),
        sessions=("full-trading-day", "new-york-rth", "london", "asia"),
    ),
    "cross-sectional-momentum": StrategyManifest(
        id="cross-sectional-momentum",
        name="Cross-sectional momentum",
        version="2.1.0",
        description="Ranks an explicit chart universe and holds a normalized long/short basket.",
        timeframes=("1h", "4h", "1d"),
        sessions=("full-trading-day", "new-york-rth", "london", "asia"),
        minimum_legs=3,
        maximum_legs=20,
    ),
    "pairs-mean-reversion": StrategyManifest(
        id="pairs-mean-reversion",
        name="Pairs mean reversion",
        version="2.1.0",
        description="Trades an explicit two-chart spread using a lagged rolling log-price z-score.",
        timeframes=("30m", "1h", "4h", "1d"),
        sessions=("full-trading-day", "new-york-rth", "london", "asia"),
        minimum_legs=2,
        maximum_legs=2,
    ),
    "prior-range-fill": StrategyManifest(
        id="prior-range-fill",
        name="Prior-range fill",
        version="2.0.0",
        description="Fades a gap after price trades back to the prior session high or low.",
        timeframes=("1m", "5m", "15m", "30m", "1h"),
        sessions=("new-york-rth", "london", "asia"),
    ),
    "opening-range-breakout": StrategyManifest(
        id="opening-range-breakout",
        name="Opening-range breakout",
        version="2.0.0",
        description=(
            "Trades the first completed-bar close outside a session opening range "
            "with deterministic bracket exits."
        ),
        timeframes=("1m", "5m", "15m", "30m"),
        sessions=("new-york-rth", "london", "asia"),
    ),
    "overnight-session": StrategyManifest(
        id="overnight-session",
        name="Session drift",
        version="2.0.0",
        description="Holds a named market session with optional prior-session filters and bracket exits.",
        timeframes=("1m", "5m", "15m", "30m", "1h"),
        sessions=("globex-overnight", "new-york-rth", "london", "asia"),
    ),
}


def get_strategy(strategy_id: str) -> StrategyManifest:
    try:
        return STRATEGIES[strategy_id]
    except KeyError as exc:
        raise ValueError(f"Unknown canonical strategy: {strategy_id}") from exc
