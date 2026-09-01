"""Reference implementation of Robert Carver's Leveraged Trading formulas.

Pure numpy/pandas. Every public function mirrors a formula documented in the
skill's references/ directory. Run `python carver.py --self-test` to verify.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

BUSINESS_DAYS = 256
ANNUALISE = math.sqrt(BUSINESS_DAYS)  # 16.0
FORECAST_AVG = 10.0
FORECAST_CAP = 20.0
IDM_CAP = 2.5
FDM_CAP = 2.5


# --------------------------------------------------------------------------
# Volatility
# --------------------------------------------------------------------------

def daily_returns(prices: pd.Series, *, differences: bool = False) -> pd.Series:
    """Percentage returns, or price differences for series that can cross zero."""
    return prices.diff() if differences else prices.pct_change()


def rolling_vol(prices: pd.Series, window: int = 25, *, differences: bool = False) -> pd.Series:
    """Annualised vol from a flat window of daily returns (Carver default: 25 days)."""
    return daily_returns(prices, differences=differences).rolling(window).std() * ANNUALISE


def ewma_vol(prices: pd.Series, span: int = 32, *, differences: bool = False) -> pd.Series:
    """Annualised EWMA vol. span=32 approximates a 25-day flat window."""
    return daily_returns(prices, differences=differences).ewm(span=span).std() * ANNUALISE


def blended_vol(prices: pd.Series, span: int = 32, years: int = 10,
                recent_weight: float = 0.7) -> pd.Series:
    """Blend recent vol with its own long-run average (default 70/30).

    Guards against under-sizing after a calm stretch and over-reacting to a spike.
    """
    recent = ewma_vol(prices, span=span)
    longrun = recent.rolling(years * BUSINESS_DAYS, min_periods=BUSINESS_DAYS).mean()
    return recent_weight * recent + (1 - recent_weight) * longrun.fillna(recent)


# --------------------------------------------------------------------------
# Position sizing
# --------------------------------------------------------------------------

@dataclass
class Instrument:
    name: str
    price: float
    multiplier: float = 1.0
    fx: float = 1.0
    ann_vol: float = 0.16          # annualised stdev of returns, as a decimal
    cost_per_trade: float = 0.0    # one side, one contract, account currency
    holding_cost_ccy: float = 0.0  # per contract per year (rolls, financing)

    @property
    def contract_value(self) -> float:
        """Notional value of one contract in account currency."""
        return self.price * self.multiplier * self.fx

    @property
    def ann_vol_ccy(self) -> float:
        """Annualised currency volatility of one contract."""
        return self.contract_value * self.ann_vol


def notional_exposure(capital: float, risk_target: float, ann_vol: float) -> float:
    """Notional the position should carry to hit the risk target."""
    return capital * risk_target / ann_vol


def position_size(capital: float, risk_target: float, inst: Instrument, *,
                  forecast: float = FORECAST_AVG, idm: float = 1.0,
                  weight: float = 1.0, round_to_contract: bool = True) -> float:
    """Contracts to hold.

    Single instrument, binary system: leave forecast/idm/weight at their defaults.
    Portfolio with continuous forecasts: pass all three.
    """
    contracts = (capital * idm * weight * risk_target * (forecast / FORECAST_AVG)) / (
        inst.ann_vol_ccy
    )
    return float(np.round(contracts)) if round_to_contract else contracts


def average_position(capital: float, risk_target: float, inst: Instrument, *,
                     idm: float = 1.0, weight: float = 1.0) -> float:
    """Position at forecast == 10. Cache this; the forecast just scales it."""
    return position_size(capital, risk_target, inst, forecast=FORECAST_AVG,
                         idm=idm, weight=weight, round_to_contract=False)


def leverage(risk_target: float, ann_vol: float) -> float:
    """Notional exposure as a multiple of capital."""
    return risk_target / ann_vol


def min_capital(inst: Instrument, risk_target: float, *, contracts: int = 4,
                idm: float = 1.0, weight: float = 1.0) -> float:
    """Capital needed to hold `contracts` on average. 4 keeps rounding error <=12.5%."""
    return contracts * inst.ann_vol_ccy / (risk_target * idm * weight)


def buffered_position(current: float, optimal: float, avg_position: float,
                      buffer_fraction: float = 0.10) -> float:
    """Trade only to the edge of a +/-10%-of-average band. Roughly halves turnover."""
    buffer = abs(avg_position) * buffer_fraction
    lower, upper = optimal - buffer, optimal + buffer
    if current < lower:
        return float(np.round(lower))
    if current > upper:
        return float(np.round(upper))
    return current


# --------------------------------------------------------------------------
# Costs
# --------------------------------------------------------------------------

def cost_per_trade_ccy(commission: float, spread_points: float, multiplier: float,
                       slippage_points: float = 0.0) -> float:
    """One side, one contract. Half the spread is paid on each side."""
    return commission + (spread_points / 2 + slippage_points) * multiplier


def risk_adjusted_cost(inst: Instrument) -> float:
    """Cost of one trade expressed in annualised Sharpe ratio units."""
    return inst.cost_per_trade / inst.ann_vol_ccy


def annual_cost_sr(inst: Instrument, trades_per_year: float) -> float:
    """Total yearly cost drag in SR units. A round trip counts as 2 trades."""
    holding = inst.holding_cost_ccy / inst.ann_vol_ccy
    return risk_adjusted_cost(inst) * trades_per_year + holding


def speed_limit(expected_pre_cost_sr: float) -> float:
    """Never spend more than a third of expected gross Sharpe on costs."""
    return expected_pre_cost_sr / 3.0


def passes_speed_limit(inst: Instrument, trades_per_year: float,
                       expected_pre_cost_sr: float = 0.30):
    """(ok, annual_cost_sr, limit). Run this before writing a backtest."""
    cost = annual_cost_sr(inst, trades_per_year)
    limit = speed_limit(expected_pre_cost_sr)
    return cost <= limit, cost, limit


# --------------------------------------------------------------------------
# Diversification
# --------------------------------------------------------------------------

def diversification_multiplier(weights, corr, cap: float = IDM_CAP) -> float:
    """1 / sqrt(w' C w), capped. Used for both IDM (returns) and FDM (forecasts)."""
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    variance = float(w @ np.asarray(corr, dtype=float) @ w)
    return min(1.0 / math.sqrt(variance), cap)


_IDM_TABLE = {1: 1.00, 2: 1.20, 3: 1.48, 4: 1.56, 5: 1.70,
              6: 1.90, 7: 2.10, 8: 2.20, 15: 2.30, 25: 2.50}


def idm_rule_of_thumb(n_instruments: int) -> float:
    """Carver's approximate IDM table for a genuinely diversified set."""
    keys = sorted(_IDM_TABLE)
    if n_instruments <= keys[0]:
        return _IDM_TABLE[keys[0]]
    if n_instruments >= keys[-1]:
        return _IDM_TABLE[keys[-1]]
    lo = max(k for k in keys if k <= n_instruments)
    hi = min(k for k in keys if k >= n_instruments)
    if lo == hi:
        return _IDM_TABLE[lo]
    frac = (n_instruments - lo) / (hi - lo)
    return _IDM_TABLE[lo] + frac * (_IDM_TABLE[hi] - _IDM_TABLE[lo])


def handcraft_weights(groups):
    """Equal weight across groups, equal weight within each group."""
    per_group = 1.0 / len(groups)
    return {name: per_group / len(members)
            for members in groups.values() for name in members}


# --------------------------------------------------------------------------
# Forecasts
# --------------------------------------------------------------------------

EWMAC_SCALARS = {(2, 8): 12.1, (4, 16): 8.53, (8, 32): 5.95,
                 (16, 64): 4.10, (32, 128): 2.79, (64, 256): 1.91}


def cap_forecast(forecast, cap: float = FORECAST_CAP):
    return np.clip(forecast, -cap, cap)


def ewmac_forecast(prices: pd.Series, fast: int, slow: int, scalar=None) -> pd.Series:
    """Vol-normalised EWMA crossover, scaled to average |forecast| == 10, capped."""
    if scalar is None:
        scalar = EWMAC_SCALARS.get((fast, slow))
        if scalar is None:
            raise ValueError("no published scalar for EWMAC(%d,%d); pass one" % (fast, slow))
    raw = prices.ewm(span=fast).mean() - prices.ewm(span=slow).mean()
    price_vol_daily = prices.diff().ewm(span=32).std()
    return cap_forecast(raw / price_vol_daily * scalar)


def combine_forecasts(forecasts: pd.DataFrame, weights, fdm: float) -> pd.Series:
    """Weighted sum of already-capped forecasts, scaled by FDM, then capped again."""
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    return cap_forecast((forecasts * w).sum(axis=1) * fdm)


def mac_signal(prices: pd.Series, fast: int = 16, slow: int = 64) -> pd.Series:
    """Starter System binary rule: +1 long, -1 short."""
    return np.sign(prices.rolling(fast).mean() - prices.rolling(slow).mean())


# --------------------------------------------------------------------------
# Risk target, stops, expectations
# --------------------------------------------------------------------------

def half_kelly_risk_target(expected_sr: float, hard_cap: float = 0.25,
                           negative_skew: bool = False) -> float:
    """Half Kelly, capped at 25%, halved again for negative-skew payoffs."""
    tau = min(expected_sr / 2.0, hard_cap)
    return tau / 2.0 if negative_skew else tau


def stop_loss_gap(price: float, ann_vol: float, stop_fraction: float = 0.5) -> float:
    """Trailing stop distance in price units. The fraction sets the holding period."""
    return stop_fraction * price * ann_vol


def expected_max_drawdown(risk_target: float, multiple: float = 2.0) -> float:
    """Plan for at least 2x the risk target; 3x is not unusual."""
    return multiple * risk_target


def sharpe_standard_error(sr: float, years: float) -> float:
    return math.sqrt((1 + sr ** 2 / 2) / years)


def years_to_detect(sr: float, confidence_z: float = 1.96) -> float:
    """Years of live data needed to distinguish this Sharpe from zero. Sobering."""
    return (confidence_z ** 2) * (1 + sr ** 2 / 2) / (sr ** 2)


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------

def _self_test() -> None:
    es = Instrument("ES", price=5000, multiplier=50, ann_vol=0.16, cost_per_trade=6.0)
    mes = Instrument("MES", price=5000, multiplier=5, ann_vol=0.16, cost_per_trade=1.5)

    assert abs(ANNUALISE - 16.0) < 1e-9

    # Sizing: $250k at 12% -> $187.5k notional -> 0.75 ES contracts -> rounds to 1.
    assert abs(notional_exposure(250_000, 0.12, 0.16) - 187_500) < 1e-6
    assert position_size(250_000, 0.12, es, round_to_contract=False) == 0.75
    assert position_size(250_000, 0.12, es) == 1.0
    assert abs(leverage(0.12, 0.16) - 0.75) < 1e-12

    # Forecast scaling is linear about 10.
    assert abs(position_size(250_000, 0.12, es, forecast=20,
                             round_to_contract=False) - 1.5) < 1e-12
    assert position_size(250_000, 0.12, es, forecast=0, round_to_contract=False) == 0.0

    # Minimum capital: 4 ES contracts at 12%; MES needs a tenth of that.
    assert abs(min_capital(es, 0.12) - 4 * 5000 * 50 * 0.16 / 0.12) < 1e-6
    assert abs(min_capital(mes, 0.12) / min_capital(es, 0.12) - 0.1) < 1e-12

    # Buffering: inside the band -> no trade; outside -> move to the band edge.
    avg = average_position(2_000_000, 0.12, es)          # 6.0 contracts
    assert abs(avg - 6.0) < 1e-9
    assert buffered_position(6.0, 6.3, avg) == 6.0       # 0.3 < 0.6 buffer
    assert buffered_position(6.0, 8.0, avg) == 7.0       # to 8.0-0.6=7.4 -> 7

    # Costs: monthly trading is cheap in risk terms, day trading is not.
    ok_slow, cost_slow, limit = passes_speed_limit(mes, trades_per_year=24)
    ok_fast, cost_fast, _ = passes_speed_limit(mes, trades_per_year=500)
    assert ok_slow and not ok_fast
    assert cost_slow < limit < cost_fast
    assert abs(limit - 0.10) < 1e-9
    # Micros carry a higher cost per unit of risk than the full-size contract.
    assert risk_adjusted_cost(mes) > risk_adjusted_cost(es)

    # Diversification.
    corr = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert abs(diversification_multiplier([0.5, 0.5], corr) - math.sqrt(2)) < 1e-9
    ones = np.ones((3, 3))
    assert abs(diversification_multiplier([1, 1, 1], ones) - 1.0) < 1e-9
    assert diversification_multiplier([1] * 50, np.eye(50)) == IDM_CAP
    assert idm_rule_of_thumb(1) == 1.0 and idm_rule_of_thumb(100) == 2.5
    hw = handcraft_weights({"eq": ["ES", "NKD"], "fi": ["ZN"]})
    assert abs(sum(hw.values()) - 1) < 1e-12 and abs(hw["ZN"] - 0.5) < 1e-12

    # Risk target.
    assert half_kelly_risk_target(0.5) == 0.25
    assert half_kelly_risk_target(2.0) == 0.25          # hard cap bites
    assert half_kelly_risk_target(0.4, negative_skew=True) == 0.10
    assert abs(stop_loss_gap(5000, 0.16) - 400.0) < 1e-9
    assert abs(expected_max_drawdown(0.12) - 0.24) < 1e-12

    # A Starter-System Sharpe takes a human lifetime to verify.
    assert years_to_detect(0.24) > 60
    assert years_to_detect(0.5) < years_to_detect(0.24)
    assert sharpe_standard_error(0.5, 10) > 0.3

    # Forecast pipeline on synthetic trending prices.
    idx = pd.bdate_range("2015-01-01", periods=1500)
    rng = np.random.default_rng(0)
    px = pd.Series(100 + np.cumsum(rng.normal(0.05, 1.0, len(idx))), index=idx)
    f16 = ewmac_forecast(px, 16, 64)
    f32 = ewmac_forecast(px, 32, 128)
    assert f16.abs().max() <= FORECAST_CAP + 1e-9
    combined = combine_forecasts(pd.DataFrame({"a": f16, "b": f32}), [0.5, 0.5], fdm=1.25)
    assert combined.abs().max() <= FORECAST_CAP + 1e-9
    assert set(mac_signal(px).dropna().unique()) <= {-1.0, 0.0, 1.0}

    # Vol estimators agree to within a sensible tolerance.
    v_flat = rolling_vol(px, 25).iloc[-1]
    v_ewma = ewma_vol(px, 32).iloc[-1]
    assert 0.5 < v_flat / v_ewma < 2.0

    print("carver.py self-test passed")


def _demo() -> None:
    es = Instrument("ES", price=5000, multiplier=50, ann_vol=0.16, cost_per_trade=6.0)
    mes = Instrument("MES", price=5000, multiplier=5, ann_vol=0.16, cost_per_trade=1.5)
    capital, tau = 100_000, 0.12
    print("Capital $%s | risk target %.0f%% | leverage %.2fx"
          % (format(capital, ","), tau * 100, leverage(tau, es.ann_vol)))
    for inst in (es, mes):
        size = position_size(capital, tau, inst, round_to_contract=False)
        ok, cost, limit = passes_speed_limit(inst, trades_per_year=24)
        print("%-4s optimal %5.2f contracts -> trade %.0f | min capital $%10s | "
              "cost %.4f vs limit %.4f %s"
              % (inst.name, size, position_size(capital, tau, inst),
                 format(round(min_capital(inst, tau)), ","), cost, limit,
                 "OK" if ok else "BREACH"))
    print("Expect drawdowns of %.0f%%+; proving SR 0.24 takes %.0f years."
          % (expected_max_drawdown(tau) * 100, years_to_detect(0.24)))


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        _self_test()
    else:
        _demo()
