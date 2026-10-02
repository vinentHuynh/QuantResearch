"""Independently reconcile preserved ledgers and apply the frozen stage gates."""
from pathlib import Path
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
import pandas as pd

from workbench.metrics import calculate
from strategies._cme_index_calendar import session_close_et

folder = Path(__file__).resolve().parent
rows = []
for directory in sorted((folder / 'runs').glob('*')):
    record = json.loads((directory / 'record.json').read_text())
    request = record['input']
    row = {'run_id': record['id'], 'status': record['status'],
           'source': request['parameters']['level_source'],
           'half_width': request['parameters']['zone_half_width_atr'],
           'start': request['start'], 'end': request['end'],
           'fee': request['fee'], 'slippage': request['slippage'],
           'research': request.get('research'),
           'source_hash': request['execution_source_hash'],
           'dataset_id': request['dataset']['id'], 'checks': {}, 'failures': []}
    if record['status'] != 'Succeeded':
        row['failures'].append('Execution did not succeed')
        rows.append(row)
        continue
    manifest = json.loads((directory / 'manifest.json').read_text())
    assert manifest['run_id'] == record['id']
    for artifact in manifest['artifacts']:
        path = directory / artifact['name']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact['checksum']
    equity = pd.read_csv(directory / 'equity.csv')
    trades = pd.read_csv(directory / 'trades.csv')
    signals = pd.read_csv(directory / 'signals.csv')
    metrics = calculate(equity, request['capital'], trades)
    for key in ['net_pnl', 'max_drawdown', 'costs', 'trades', 'observations']:
        assert np.isclose(metrics[key], manifest['metrics'][key], atol=1e-6), key
    assert np.isclose(trades.net_pnl.sum(), metrics['net_pnl'], atol=1e-6)
    assert np.isclose(trades.cost.sum(), metrics['costs'], atol=1e-6)
    assert len(trades) == len(pd.read_csv(directory / 'trades.csv'))
    winners = float(trades.loc[trades.net_pnl > 0, 'net_pnl'].sum())
    losers = float(-trades.loc[trades.net_pnl < 0, 'net_pnl'].sum())
    pf = winners / losers if losers else (None if not winners else float('inf'))
    peaks = np.maximum.accumulate(np.r_[request['capital'], equity.equity.to_numpy()])[1:]
    years = pd.to_datetime(trades.exit_time, utc=True).dt.tz_convert('America/Chicago').dt.year
    annual = {str(year): float(value) for year, value in trades.groupby(years).net_pnl.sum().items()}
    entry = pd.to_datetime(trades.entry_time, utc=True).dt.tz_convert('America/Chicago')
    for stamp in entry:
        midnight = pd.Timestamp(stamp.date()).tz_localize('America/Chicago')
        close = session_close_et(stamp.date())
        assert close is not None
        assert midnight + pd.Timedelta(hours=8, minutes=30) <= stamp < min(midnight + pd.Timedelta(hours=15), close.tz_convert('America/Chicago'))
        assert stamp.minute % 15 == 0
    expected_cost = 2 * (request['fee'] + request['slippage'] * request['dataset']['tick_size'] * request['dataset']['point_value'])
    assert np.allclose(trades.cost, expected_cost)
    row.update(metrics=metrics, profit_factor=pf,
               expectancy=float(trades.net_pnl.mean()) if len(trades) else None,
               win_rate=float((trades.net_pnl > 0).mean()) if len(trades) else None,
               max_drawdown_dollars=float((peaks - equity.equity.to_numpy()).max()),
               annual_net=annual, exit_reasons=trades.exit_reason.value_counts().to_dict(),
               side_net={str(side): float(net) for side, net in trades.groupby('quantity').net_pnl.sum().items()},
               top_10_winners=float(trades.loc[trades.net_pnl > 0, 'net_pnl'].nlargest(10).sum()),
               gross_winning_net=winners, warmup=manifest['warmup'], warnings=manifest['warnings'],
               submitted_entries=int(((signals.event == 'submitted') & (signals.target != 0)).sum()),
               expired_orders=int((signals.event == 'expired').sum()),
               checks={'artifact_hashes': True, 'metrics_recalculated': True,
                       'trade_equity_cost_reconciliation': True,
                       'regular_session_entries': True, 'per_trade_costs': True})
    development = request['start'] == '2022-01-01'
    minimum = 100 if development else (40 if request['start'] == '2025-01-01' else 25)
    threshold = 1.05 if development and request['parameters']['zone_half_width_atr'] == 0.10 else 1.0
    if len(trades) < minimum:
        row['failures'].append(f'Trade count {len(trades)} below {minimum}')
    if metrics['net_pnl'] <= 0:
        row['failures'].append('Net P&L is not positive')
    if pf is None or (pf < threshold if threshold == 1.05 else pf <= threshold):
        row['failures'].append(f'Profit factor below gate {threshold}')
    if -metrics['max_drawdown'] > 0.35:
        row['failures'].append('Marked drawdown exceeds 35%')
    if development and sum(annual.get(str(year), 0) > 0 for year in [2022, 2023, 2024]) < 2:
        row['failures'].append('Fewer than two profitable development years')
    row['eligible'] = not row['failures']
    rows.append(row)

(folder / 'summary.json').write_text(json.dumps(rows, indent=2, allow_nan=False))
for row in rows:
    compact = {k: row.get(k) for k in ['run_id', 'source', 'half_width', 'start', 'end', 'fee', 'status', 'profit_factor', 'expectancy', 'max_drawdown_dollars', 'annual_net', 'failures', 'eligible']}
    compact['metrics'] = {k: row.get('metrics', {}).get(k) for k in ['net_pnl', 'max_drawdown', 'costs', 'trades']}
    print(json.dumps(compact))
