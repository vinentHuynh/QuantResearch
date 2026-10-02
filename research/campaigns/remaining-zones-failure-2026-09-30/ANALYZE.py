"""Reconcile full ledgers, record pointwise day-cluster uncertainty and stage gates."""
from pathlib import Path
import hashlib
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
import pandas as pd
from workbench.metrics import calculate
from strategies._cme_index_calendar import session_close_et

folder = Path(__file__).resolve().parent
campaign = json.loads((folder / 'campaign.json').read_text())
stages = {r['id']: r['stage'] for r in campaign['runs']}
rows = []
for directory in sorted((folder / 'runs').glob('*')):
    record = json.loads((directory / 'record.json').read_text())
    request = record['input']
    tag = request.get('research', {})
    row = {'run_id': record['id'], 'status': record['status'],
           'detector': request['parameters']['detector'],
           'stage': stages.get(record['id'], 'evaluation-' + str(tag.get('role', 'unknown'))),
           'half_width': request['parameters']['zone_half_width_atr'],
           'start': request['start'], 'end': request['end'], 'fee': request['fee'], 'slippage': request['slippage'],
           'research': tag, 'source_hash': request['execution_source_hash'],
           'dataset_id': request['dataset']['id'], 'failures': [], 'checks': {}}
    if record['status'] != 'Succeeded':
        row.update(disposition='Execution failed / incomplete', eligible=False)
        row['failures'].append(record.get('error', 'Execution did not succeed'))
        rows.append(row)
        continue
    manifest = json.loads((directory / 'manifest.json').read_text())
    assert manifest['run_id'] == record['id']
    assert manifest['execution_source_hash'] == request['execution_source_hash']
    for artifact in manifest['artifacts']:
        path = directory / artifact['name']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact['checksum']
        assert path.stat().st_size == artifact['bytes']
    equity = pd.read_csv(directory / 'equity.csv')
    trades = pd.read_csv(directory / 'trades.csv')
    signals = pd.read_csv(directory / 'signals.csv')
    metrics = calculate(equity, request['capital'], trades)
    for key in ['net_pnl', 'max_drawdown', 'costs', 'trades', 'observations']:
        assert np.isclose(metrics[key], manifest['metrics'][key], atol=1e-6), key
    assert np.isclose(trades.net_pnl.sum(), metrics['net_pnl'], atol=1e-6)
    assert np.isclose(trades.cost.sum(), metrics['costs'], atol=1e-6)
    winners = float(trades.loc[trades.net_pnl > 0, 'net_pnl'].sum())
    losers = float(-trades.loc[trades.net_pnl < 0, 'net_pnl'].sum())
    pf = winners / losers if losers else None
    infinite_pf = bool(winners > 0 and losers == 0)
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
    interval = None
    occupied_days = 0
    if len(trades):
        groups = trades.groupby(entry.dt.date).agg(net=('net_pnl', 'sum'), n=('net_pnl', 'size'))
        occupied_days = len(groups)
        if occupied_days >= 10:
            generator = np.random.default_rng(42)
            indices = generator.integers(0, len(groups), (5000, len(groups)))
            estimates = groups.net.to_numpy()[indices].sum(axis=1) / groups.n.to_numpy()[indices].sum(axis=1)
            interval = np.quantile(estimates, [0.025, 0.975]).tolist()
    match = re.search(r'Remaining detector funnel: (\{[^\n]+\})', record.get('log', ''))
    funnel = json.loads(match.group(1)) if match else None
    row.update(metrics=metrics, profit_factor=pf, infinite_profit_factor=infinite_pf,
               expectancy=float(trades.net_pnl.mean()) if len(trades) else None,
               win_rate=float((trades.net_pnl > 0).mean()) if len(trades) else None,
               max_drawdown_dollars=float((peaks - equity.equity.to_numpy()).max()),
               annual_net=annual, exit_reasons=trades.exit_reason.value_counts().to_dict(),
               side_net={str(side): float(net) for side, net in trades.groupby('quantity').net_pnl.sum().items()},
               top_10_winning_share=float(trades.loc[trades.net_pnl > 0, 'net_pnl'].nlargest(10).sum() / winners) if winners else None,
               best_trade=float(trades.net_pnl.max()) if len(trades) else None,
               day_cluster_expectancy_95=interval, occupied_entry_days=occupied_days,
               warmup=manifest['warmup'], warnings=manifest['warnings'], funnel=funnel,
               submitted_entries=int(((signals.event == 'submitted') & (signals.target != 0)).sum()),
               expired_orders=int((signals.event == 'expired').sum()),
               checks={'artifact_hashes_and_sizes': True, 'metrics_recalculated': True,
                       'trade_equity_cost_reconciliation': True, 'regular_session_entries': True,
                       'per_trade_costs': True, 'source_identity': True})
    development = row['stage'] == 'development' or row['stage'].startswith('nearby-')
    training = 'training' in row['stage'].lower()
    minimum = 20 if training else (100 if development else 40 if request['start'] == '2025-01-01' else 25)
    threshold = 1.05 if row['stage'] == 'development' else 1.0
    sparse = len(trades) < minimum
    if sparse:
        row['failures'].append(f'Sparse: {len(trades)} trades below operational floor {minimum}')
    if not training:
        if metrics['net_pnl'] <= 0:
            row['failures'].append('Net P&L is not positive')
        if not infinite_pf and (pf is None or (pf < threshold if threshold == 1.05 else pf <= threshold)):
            row['failures'].append(f'Profit factor misses {threshold} gate')
        if -metrics['max_drawdown'] > 0.35:
            row['failures'].append('Marked drawdown exceeds 35%')
        if development and sum(annual.get(str(year), 0) > 0 for year in [2022, 2023, 2024]) < 2:
            row['failures'].append('Fewer than two profitable development years')
    if manifest['warmup']['status'] != 'sufficient':
        row['failures'].append('Declared warmup is not sufficient')
    row['eligible'] = not row['failures']
    row['disposition'] = ('Sparse / inconclusive' if sparse else 'Eligible for next stage' if row['eligible'] else 'Tested configuration failed')
    if row['detector'] == 'generic-prior-bar':
        row['eligible'] = False
        row['disposition'] = 'Descriptive benchmark'
    rows.append(row)

(folder / 'summary.json').write_text(json.dumps(rows, indent=2, allow_nan=False))
for row in rows:
    print(json.dumps({k: row.get(k) for k in ['run_id', 'detector', 'stage', 'profit_factor', 'expectancy',
                     'annual_net', 'day_cluster_expectancy_95', 'disposition', 'eligible', 'failures']} |
                     {'net': row.get('metrics', {}).get('net_pnl'), 'trades': row.get('metrics', {}).get('trades')}))
