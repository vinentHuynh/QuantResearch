"""JSON boundary, next-bar-open execution, validated atomic output publication."""
import importlib.util
import json
import os
import sys
import threading
import time
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

import numpy as np
import pandas as pd

from .contract import checksum, metadata, resolve_parameters
from .metrics import calculate


def simulate(bars, targets, request):
    if not isinstance(targets, pd.Series) or not targets.index.equals(bars.index):
        raise ValueError('signals() must return a Series with exactly the bars index')
    if not np.isfinite(targets.to_numpy()).all() or not np.equal(targets, np.trunc(targets)).all() or targets.abs().max() > 100:
        raise ValueError('Signals must be finite whole contract targets between -100 and 100')
    ready = pd.to_datetime(bars.availability_time, utc=True)
    # An earlier completed bar may only fill at or after its availability time.
    delay = request.get('delay_bars', 0)
    if type(delay) is not int or not 0 <= delay <= 20:
        raise ValueError('delay_bars must be an integer from 0 to 20')
    desired = targets.shift(1 + delay).fillna(0)
    desired = desired.where(ready.shift(1 + delay) <= bars.index, 0)
    start = pd.Timestamp(request['start'], tz='UTC')
    end = pd.Timestamp(request['end'], tz='UTC') + pd.Timedelta(days=1)
    mask = (bars.index >= start) & (ready < end)
    chosen = bars.loc[mask]
    if len(chosen) < 2:
        raise ValueError('Selected interval needs at least two completed bars')
    economics = request['dataset']
    point = economics['point_value']
    one_way_cost = request['fee'] + request['slippage'] * economics['tick_size'] * point
    held, previous_close, balance, active = 0, None, request['capital'], None
    equity_rows, trades, positions = [], [], []
    for i, (timestamp, row) in enumerate(chosen.iterrows()):
        target = int(desired.loc[timestamp])
        turnover = abs(target - held)
        cost = abs(target - held) * one_way_cost
        gross = held * (float(row.open) - previous_close) * point if previous_close is not None else 0
        if active is not None:
            active['gross_pnl'] += gross
        if target != held:
            if active is not None:
                active['cost'] += abs(held) * one_way_cost
                active.update(exit_time=timestamp.isoformat(), exit=float(row.open))
                active['net_pnl'] = active['gross_pnl'] - active['cost']
                trades.append(active)
            active = {'entry_time': timestamp.isoformat(), 'entry': float(row.open), 'quantity': target, 'gross_pnl': 0.0, 'cost': abs(target) * one_way_cost} if target else None
            # Resizing closes/reopens the exposure for the trade ledger; only net
            # turnover is charged. Allocate the actual cost proportionally.
            if held and target and np.sign(held) == np.sign(target):
                old_cost = abs(held) * one_way_cost
                new_cost = abs(target) * one_way_cost
                share = abs(held) / (abs(held) + abs(target))
                trades[-1]['cost'] += cost * share - old_cost
                trades[-1]['net_pnl'] = trades[-1]['gross_pnl'] - trades[-1]['cost']
                active['cost'] += cost * (1 - share) - new_cost
        intrabar = target * (float(row.close) - float(row.open)) * point
        gross += intrabar
        if active is not None:
            active['gross_pnl'] += intrabar
        held = target
        if i == len(chosen) - 1 and held:
            turnover += abs(held)
            cost += abs(held) * one_way_cost
            active['cost'] += abs(held) * one_way_cost
            active.update(exit_time=pd.Timestamp(row.availability_time).isoformat(), exit=float(row.close))
            active['net_pnl'] = active['gross_pnl'] - active['cost']
            trades.append(active)
            held = 0
        balance += gross - cost
        event = pd.Timestamp(row.availability_time).isoformat()
        equity_rows.append({'timestamp': event, 'equity': balance, 'gross_pnl': gross, 'cost': cost, 'net_pnl': gross - cost})
        positions.append({'timestamp': event, 'contracts': held, 'intrabar_contracts': target, 'turnover_contracts': turnover})
        previous_close = float(row.close)
    return pd.DataFrame(equity_rows), pd.DataFrame(trades, columns=['entry_time', 'exit_time', 'quantity', 'entry', 'exit', 'gross_pnl', 'cost', 'net_pnl']), pd.DataFrame(positions)


def main(request_file):
    request = json.loads(Path(request_file).read_text())
    lease = os.environ.get('WORKBENCH_SUPERVISOR_FILE')
    token = os.environ.get('WORKBENCH_SUPERVISOR_TOKEN')
    if lease and token:
        def monitor():
            while True:
                time.sleep(1)
                try:
                    path = Path(lease)
                    stale = time.time() - path.stat().st_mtime > 15
                    changed = json.loads(path.read_text())['token'] != token
                    if stale or changed:
                        os._exit(75)
                except (OSError, ValueError, KeyError):
                    # A heartbeat write may momentarily expose an empty file.
                    time.sleep(.1)
                    if not Path(lease).exists():
                        os._exit(75)
        threading.Thread(target=monitor, daemon=True).start()
    print('Preflight: verifying preserved data and strategy', flush=True)
    if request['protocol'] != 1:
        raise ValueError('Unsupported protocol version')
    dataset = request['dataset']
    if checksum(dataset['path']) != dataset['checksum']:
        raise ValueError('Immutable dataset checksum mismatch')
    source = Path(request['source_dir']) / request['strategy']['file']
    if checksum(source) != request['strategy']['file_hash']:
        raise ValueError('Preserved strategy checksum mismatch')
    source_manifest = Path(request['source_dir']) / 'sources.json'
    if source_manifest.exists():
        for filename, digest in json.loads(source_manifest.read_text()).items():
            if checksum(Path(request['source_dir']) / filename) != digest:
                raise ValueError(f'Preserved source checksum mismatch: {filename}')
    environment = json.loads((Path(request['source_dir']) / 'environment.json').read_text())
    for package in environment['dependencies']:
        try:
            installed = version(package['name'])
        except PackageNotFoundError:
            installed = None
        if installed != package['version']:
            raise ValueError(f'Environment changed: {package["name"]}; restore snapshot dependencies before replay')
    spec = metadata(source)
    parameters = resolve_parameters(spec, request['parameters'])
    if request['timeframe'] not in spec['timeframes']:
        raise ValueError('Unsupported timeframe')
    if request['capital'] <= 0 or min(request['fee'], request['slippage']) < 0:
        raise ValueError('Invalid accounting assumptions')
    from strategy_engine.data import session_bars
    from strategy_engine.sessions import get_session
    start = pd.Timestamp(request['start'], tz='UTC') - pd.Timedelta(days=request['warmup_days'])
    end = pd.Timestamp(request['end'], tz='UTC') + pd.Timedelta(days=1)
    frame = pd.read_parquet(dataset['path'], filters=[('ts_event', '>=', start), ('ts_event', '<', end)])
    if frame.empty:
        raise ValueError('Dataset has no bars in the requested interval')
    print(f'Loaded {len(frame):,} source bars; building {request["timeframe"]} bars', flush=True)
    bars = session_bars(frame, get_session(request['session']), request['timeframe'])
    module_spec = importlib.util.spec_from_file_location('user_strategy', source)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if hasattr(module, 'validate'):
        module.validate(parameters, request)
    print(f'Accounting for {len(bars):,} bars including warmup', flush=True)
    if spec.get('execution_model') == 'event-v1':
        from .events import simulate_events
        model = module.create_strategy(bars.copy(), parameters, request)
        equity, trades, positions = simulate_events(bars, model, request, execution_bars=frame)
    else:
        targets = module.signals(bars.copy(), parameters)
        equity, trades, positions = simulate(bars, targets, request)
    metrics = calculate(equity, request['capital'], trades)
    metrics['time_invested_bar_fraction'] = float((positions.intrabar_contracts != 0).mean())
    metrics['turnover_contracts'] = int(positions.turnover_contracts.sum())
    if not np.isclose(trades.net_pnl.sum(), metrics['net_pnl'], atol=1e-6):
        raise ValueError('Trade ledger does not reconcile with marked equity')
    folder = Path(request_file).parent
    artifacts = []
    for name, frame in [('equity', equity), ('trades', trades), ('positions', positions)]:
        path = folder / f'{name}.csv'
        frame.to_csv(path, index=False)
        artifacts.append({'name': path.name, 'checksum': checksum(path), 'rows': len(frame)})
    warnings = [*dataset['warnings'], 'Final bar closes all positions. Warmup initializes signals; scoring starts flat. Positions carry across excluded session gaps.', 'Intrabar paths are unknown; fills use next bar open and slippage, with no stop/limit simulation.']
    if spec.get('execution_model') == 'event-v1':
        warnings = [*dataset['warnings'],
                    'Historical event simulation: strategy-declared close or next-open fills. Scoring starts flat; final bar liquidates positions.',
                    'Working brackets use one-minute OHLC; stop wins ties within a minute. Intraminute timestamps are the minute close. Market/stop slippage is charged as cash cost; limit exits pay commission only.',
                    'TradingView data, margin liquidations, sub-minute Bar Magnifier, and intrabar recalculation can differ. TradingView parity is not certified.']
    if metrics['trades'] == 0:
        warnings.append('No completed trades; this run supplies no trading evidence.')
    if spec.get('migration_scope'):
        warnings.append(spec['migration_scope'])
    if metrics['observations'] < 100:
        warnings.append('Small sample: fewer than 100 scored bars.')
    # Downsample previews only; full accounting series remains downloadable.
    stride = max(1, len(equity) // 1000)
    equity['drawdown'] = equity.equity.to_numpy() / np.maximum.accumulate(np.r_[request['capital'], equity.equity.to_numpy()])[1:] - 1
    preview = equity.iloc[::stride]
    preview = pd.concat([preview, equity.tail(1)]).drop_duplicates('timestamp')
    manifest = {'protocol': 1, 'run_id': request['id'], 'metrics': metrics, 'warnings': warnings,
                'artifacts': artifacts, 'equity_preview': preview[['timestamp', 'equity', 'drawdown']].to_dict('records'),
                'trade_preview': trades.head(100).to_dict('records')}
    partial = folder / 'manifest.partial.json'
    partial.write_text(json.dumps(manifest, allow_nan=False, indent=2))
    os.replace(partial, folder / 'manifest.json')
    print('Validated and published all artifacts', flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
