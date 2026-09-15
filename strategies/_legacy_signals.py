"""Shared, causal signal rules ported from the repository's research scripts.

These retain indicator decisions, not the proxy-return or fractional-NAV accounting.
The workbench owns next-open fills, fixed contracts, costs, and final liquidation.
"""
import numpy as np
import pandas as pd


def momentum(close, lookback):
    speeds = tuple(dict.fromkeys((max(2, lookback // 3), lookback, lookback * 2, lookback * 4)))
    score = pd.concat([np.sign(close.pct_change(speed)) for speed in speeds], axis=1).mean(axis=1, skipna=False)
    return np.sign(score).fillna(0)


def rsi_reversion(close, trend_lookback, entry_rsi, exit_rsi):
    # Original es_nq_strategies.rsi uses simple rolling means, not Wilder RSI.
    change = close.diff()
    up = change.clip(lower=0).rolling(2).mean()
    down = (-change.clip(upper=0)).rolling(2).mean()
    rsi = 100 - 100 / (1 + up / down.replace(0, np.nan))
    enter = (rsi < entry_rsi) & (close > close.rolling(trend_lookback).mean())
    leave = rsi > exit_rsi
    return pd.Series(np.where(enter, 1., np.where(leave, 0., np.nan)), index=close.index).ffill().fillna(0)


def vwap_reversion(bars, band):
    target = pd.Series(0., index=bars.index)
    for _, day in bars.groupby('session_date', sort=False):
        volume = day.volume.cumsum().replace(0, np.nan)
        vwap = (((day.high + day.low + day.close) / 3) * day.volume).cumsum() / volume
        position = 0.
        for timestamp, deviation in (day.close / vwap - 1).items():
            if pd.notna(deviation):
                if position == 0:
                    position = 1. if deviation < -band else -1. if deviation > band else 0.
                elif position == 1 and deviation >= 0 or position == -1 and deviation <= 0:
                    position = 0.
            target.loc[timestamp] = position
    return target
