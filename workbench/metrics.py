"""Shared metrics v1: bar-close marked equity, no cash flows, USD, zero RF.

Daily risk statistics use UTC observed trading dates, 252 dates/year.
Missing dates are not filled; holidays/gaps are disclosed in dataset metadata.
"""
import numpy as np
import pandas as pd

VERSION = '1.0.0'


def calculate(equity, capital, trades=None):
    values = equity.equity.astype(float)
    if values.empty or not np.isfinite(values).all() or capital <= 0:
        raise ValueError('Equity must be nonempty and finite; capital must be positive')
    times = pd.to_datetime(equity.timestamp, utc=True)
    if times.duplicated().any() or not times.is_monotonic_increasing:
        raise ValueError('Equity timestamps must be unique and increasing')
    peaks = np.maximum.accumulate(np.r_[capital, values.to_numpy()])[1:]
    drawdown = values.to_numpy() / peaks - 1
    daily = pd.Series(values.to_numpy(), index=times).groupby(times.dt.date.to_numpy()).last()
    previous = daily.shift(1).fillna(capital)
    returns = daily / previous - 1
    solvent = bool((values > 0).all())
    std = float(returns.std(ddof=1)) if len(returns) > 1 and solvent else 0
    years = (times.iloc[-1] - times.iloc[0]).total_seconds() / (365.25 * 86400)
    durations, current = [], 0
    for d in drawdown:
        current = current + 1 if d < -1e-12 else 0
        durations.append(current)
    month = pd.Series(values.to_numpy(), index=times).resample('ME').last().dropna()
    monthly = month / month.shift(1).fillna(capital) - 1
    return {
        'version': VERSION, 'net_return': float(values.iloc[-1] / capital - 1),
        'net_pnl': float(values.iloc[-1] - capital), 'max_drawdown': float(drawdown.min()),
        'underwater_bars': max(durations), 'current_underwater_bars': current,
        'cagr': float((values.iloc[-1] / capital) ** (1 / years) - 1) if years >= 1 and solvent else None,
        'sharpe': float(returns.mean() / std * np.sqrt(252)) if std > 1e-12 else None,
        'volatility': float(std * np.sqrt(252)) if len(returns) > 1 and solvent else None,
        'trades': len(trades) if trades is not None else None, 'observations': len(values),
        'costs': float(equity.cost.sum()) if 'cost' in equity else None,
        'first': times.iloc[0].isoformat(), 'last': times.iloc[-1].isoformat(),
        'monthly': [{'month': t.strftime('%Y-%m'), 'return': float(v)} for t, v in monthly.items()],
        'basis': 'USD; bar-close MTM including open P&L; daily observed UTC returns; 252 dates/year; RF=0; no cash flows',
        'undefined_reason': 'Sharpe requires varying returns; CAGR requires >=1 year and positive equity. Insolvent equity has no risk annualization.',
    }
