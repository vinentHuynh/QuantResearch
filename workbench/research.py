"""Chronological evaluation summaries and training-calibrated state studies.

All monetary paths are derived from validated run artifacts. Analysis never
selects a candidate or alters saved runs. State features use preceding bars.
"""
import json
import os
import sys
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

import numpy as np
import pandas as pd

from .contract import checksum
from .metrics import calculate


def read_artifact(run, name):
    path = Path(run['folder']) / name
    entry = next(a for a in run['result']['artifacts'] if a['name'] == name)
    if checksum(path) != entry['checksum']:
        raise ValueError(f'Changed run artifact: {path}')
    return pd.read_csv(path)


def stitch(runs, capital):
    """Fold simulations use fixed sizing capital. Sum P&L without resetting peaks."""
    frames, trades = [], []
    last = None
    for run in sorted(runs, key=lambda r: r['input']['research']['fold']):
        equity = read_artifact(run, 'equity.csv')
        times = pd.to_datetime(equity.timestamp, utc=True)
        if last is not None and times.iloc[0] <= last:
            raise ValueError('Overlapping evaluation folds cannot be stitched')
        if run['input']['capital'] != capital:
            raise ValueError('Fold sizing capital changed')
        if not np.isclose(equity.net_pnl.sum(), equity.equity.iloc[-1] - capital, atol=1e-6):
            raise ValueError('Fold P&L does not reconcile')
        last = times.iloc[-1]
        equity['fold'] = run['input']['research']['fold']
        frames.append(equity)
        trades.append(read_artifact(run, 'trades.csv'))
    combined = pd.concat(frames, ignore_index=True)
    combined['equity'] = capital + combined.net_pnl.cumsum()
    return combined, calculate(combined, capital, pd.concat(trades, ignore_index=True))


def evaluate(payload, folder):
    evaluation, runs = payload['evaluation'], payload['runs']
    capital = evaluation['candidates'][0]['capital']
    scenarios, paths = [], []
    names = evaluation.get('scenarios', ['Baseline', 'Higher costs', 'Delayed execution'])
    if names not in (['Baseline', 'Higher costs'], ['Baseline', 'Higher costs', 'Delayed execution']):
        raise ValueError('Invalid declared evaluation scenarios')
    for name in names:
        selected = [r for r in runs if r['input']['research']['scenario'] == name]
        if len(selected) != len(evaluation['folds']):
            raise ValueError(f'Incomplete scenario: {name}')
        equity, metrics = stitch(selected, capital)
        equity['scenario'] = name
        paths.append(equity)
        outcome = ('Inconclusive' if metrics['trades'] < evaluation['min_test_trades'] else
                   'Meets criteria' if metrics['net_return'] >= evaluation['min_return'] and
                   abs(metrics['max_drawdown']) <= evaluation['max_drawdown'] else 'Does not meet criteria')
        stride = max(1, len(equity) // 800)
        preview = pd.concat([equity.iloc[::stride], equity.tail(1)]).drop_duplicates('timestamp')
        scenarios.append({'name': name, 'metrics': metrics, 'outcome': outcome,
                          'equity_preview': preview[['timestamp', 'equity']].to_dict('records')})
    pd.concat(paths, ignore_index=True).to_csv(folder / 'equity.csv', index=False)
    return {'version': 1, 'outcome': scenarios[0]['outcome'], 'scenarios': scenarios,
            'boundary': 'Each test fold starts and ends flat; fixed sizing capital; joined dollar P&L with continuous equity peaks. Costs include each fold liquidation. Warmup is excluded from scored P&L.',
            'warnings': [*(['Execution-delay stress was not run; event-order delay is unsupported. Baseline and higher-cost results do not establish delay robustness.'] if 'Delayed execution' not in names and evaluation['candidates'][0]['strategy'].get('execution_model') == 'event-v1' else ['Execution-delay stress was not included in this protocol.'] if 'Delayed execution' not in names else []),
                         'Selection uses training only; later rolling training windows may include earlier test observations under the frozen protocol.',
                         'Historical walk-forward is a simulation, not prospective paper evidence. Repeated experiments on the same history are not fresh holdouts.',
                         'Criteria apply to the combined baseline test path; stress outcomes are reported separately.',
                         f'{len(evaluation["inspected_overlap"])} previously successful runs overlap the test interval; prior exposure is preserved in the evaluation record.',
                         *sorted({warning for run in runs for warning in run['result'].get('warnings', [])})]}


def state_features(bars, feature, window):
    """Value at t uses only completed bars preceding t (known before its outcome)."""
    close = bars.close.astype(float)
    if feature == 'volatility':
        # Percentage returns across zero/negative prices have no stable meaning.
        returns = close.pct_change(fill_method=None).where((close > 0) & (close.shift(1) > 0))
        values = returns.rolling(window, min_periods=window).std(ddof=1).shift(1)
    elif feature == 'trend':
        average = close.rolling(window, min_periods=window).mean()
        values = (close / average - 1).where((close > 0) & (average > 0)).shift(1)
    else:
        raise ValueError('Unknown regime feature')
    ready = pd.to_datetime(bars.availability_time, utc=True)
    return values.where(ready.shift(1) <= bars.index).replace([np.inf, -np.inf], np.nan)


def assign_states(bars, feature, window, quantile, train_start, train_end):
    values = state_features(bars, feature, window)
    ready = pd.to_datetime(bars.availability_time, utc=True)
    allowed = (bars.index >= pd.Timestamp(train_start, tz='UTC')) & (ready < pd.Timestamp(train_end, tz='UTC') + pd.Timedelta(days=1))
    sample = values.loc[allowed].dropna()
    if len(sample) < 20:
        raise ValueError('At least 20 finite training feature observations are required')
    threshold = float(sample.quantile(quantile))
    labels = pd.Series('Unknown', index=bars.index)
    labels.loc[values.notna() & (values <= threshold)] = 'Lower'
    labels.loc[values.notna() & (values > threshold)] = 'Higher'
    return values, labels, threshold, len(sample)


def episode_summary(observations, seed):
    # Reset episodes at fold boundaries; adjacent bars are not independent trials.
    frame = observations.copy()
    transitions = (frame.state != frame.state.shift(1)) | (frame.fold != frame.fold.shift(1))
    frame['episode'] = transitions.cumsum()
    rng = np.random.default_rng(seed)
    results = []
    for state, rows in frame.groupby('state', sort=True):
        episode_pnl = rows.groupby('episode').net_pnl.sum().to_numpy()
        count = len(episode_pnl)
        interval = None
        if count >= 10 and state != 'Unknown':
            means = [rng.choice(episode_pnl, size=count, replace=True).mean() for _ in range(1000)]
            interval = [float(x) for x in np.quantile(means, [.025, .975])]
        results.append({'state': state, 'observations': len(rows), 'episodes': count,
                        'net_pnl': float(rows.net_pnl.sum()), 'costs': float(rows.cost.sum()),
                        'invested_bar_fraction': float((rows.intrabar_contracts != 0).mean()),
                        'entry_count': int(rows.entry_count.sum()),
                        'mean_episode_pnl': float(episode_pnl.mean()),
                        'mean_episode_pnl_interval_95': interval,
                        'evidence': 'Sparse / interval unavailable' if interval is None else 'Descriptive episode bootstrap'})
    return results


def entry_bar_indices(times, trades):
    """Event entries name their execution bar; signal entries fill at its open."""
    times = pd.DatetimeIndex(times)
    if 'entry_bar_close' in trades:
        indices = times.get_indexer(pd.to_datetime(trades.entry_bar_close, utc=True))
        if (indices < 0).any():
            raise ValueError('Cannot attribute an event entry to its recorded bar')
        return indices
    return np.searchsorted(times, pd.to_datetime(trades.entry_time, utc=True), side='right')


def investigate(payload, folder):
    from strategy_engine.data import session_bars
    from strategy_engine.sessions import get_session
    evaluation, task = payload['evaluation'], payload['task']
    observations, thresholds = [], []
    for run in payload['runs']:
        request = run['input']
        fold = evaluation['folds'][request['research']['fold']]
        dataset = request['dataset']
        if checksum(dataset['path']) != dataset['checksum']:
            raise ValueError('Dataset changed since evaluation')
        start = pd.Timestamp(fold['train_start'], tz='UTC') - pd.Timedelta(days=request['warmup_days'])
        end = pd.Timestamp(fold['test_end'], tz='UTC') + pd.Timedelta(days=1)
        source = pd.read_parquet(dataset['path'], filters=[('ts_event', '>=', start), ('ts_event', '<', end)])
        bars = session_bars(source, get_session(request['session']), request['timeframe'])
        features, labels, threshold, count = assign_states(bars, task['feature'], task['window'], task['quantile'], fold['train_start'], fold['train_end'])
        by_time = pd.DataFrame({'timestamp': pd.to_datetime(bars.availability_time, utc=True), 'feature': features.to_numpy(), 'state': labels.to_numpy()})
        equity = read_artifact(run, 'equity.csv')
        positions = read_artifact(run, 'positions.csv')
        trades = read_artifact(run, 'trades.csv')
        equity.timestamp = pd.to_datetime(equity.timestamp, utc=True)
        positions.timestamp = pd.to_datetime(positions.timestamp, utc=True)
        rows = equity.merge(by_time, on='timestamp', how='left', validate='one_to_one').merge(positions[['timestamp', 'intrabar_contracts']], on='timestamp', validate='one_to_one')
        if rows.state.isna().any():
            raise ValueError('Cannot align regime labels to every scored observation')
        rows['fold'] = fold['index']
        rows['threshold'] = threshold
        rows['entry_count'] = 0
        # Count trade openings within each scored bar, attributed by its state.
        if not trades.empty:
            indices = entry_bar_indices(rows.timestamp, trades)
            for index in indices:
                if index < len(rows):
                    rows.iloc[index, rows.columns.get_loc('entry_count')] += 1
        observations.append(rows)
        thresholds.append({'fold': fold['index'], 'threshold': threshold, 'training_observations': count,
                           'calibrated_start': fold['train_start'], 'calibrated_through': fold['train_end']})
    combined = pd.concat(observations, ignore_index=True)
    combined.to_csv(folder / 'observations.csv', index=False)
    return {'version': 1, 'source': 'Historical conditional attribution', 'feature': task['feature'],
            'formula': 'std of trailing positive-price bar returns, shifted one completed bar' if task['feature'] == 'volatility' else 'close / trailing mean(close) - 1, shifted one completed bar',
            'window': task['window'], 'threshold_quantile': task['quantile'], 'thresholds': thresholds,
            'states': episode_summary(combined, task['seed']), 'seed': task['seed'], 'bootstrap_samples': 1000,
            'warnings': ['Labels use preceding completed bars; each threshold uses its own earlier training period only.',
                         'Episode bootstrap intervals describe mean episode dollar P&L, not an independent-bar significance test or switching-policy forecast. Episodes may remain dependent.',
                         'Fewer than 10 episodes gives no uncertainty interval. Unknown features (including nonpositive-price windows) remain a separate group.',
                         'Entry count is attributed by opening bar; a trade may cross states, so it is not a state-specific closed-trade performance metric.',
                         'Drawdown is not computed on disconnected state subsets. Refer to the continuous evaluation path.',
                         'This investigation was specified after observing evaluation results. It is exploratory historical research, not a prospective predictive test or allocation recommendation.']}


def main(kind, path):
    from .supervision import monitor_lease
    monitor_lease()
    folder = Path(path).parent
    payload = json.loads(Path(path).read_text())
    snapshot = Path(payload['evaluation']['source_dir'])
    for package in json.loads((snapshot / 'environment.json').read_text())['dependencies']:
        try:
            installed = version(package['name'])
        except PackageNotFoundError:
            installed = None
        if installed != package['version']:
            raise ValueError(f'Environment changed: {package["name"]}; restore the recorded dependencies before analysis')
    for filename, expected in json.loads((snapshot / 'sources.json').read_text()).items():
        if checksum(snapshot / filename) != expected:
            raise ValueError(f'Preserved source changed: {filename}')
    result = evaluate(payload, folder) if kind == 'evaluations' else investigate(payload, folder)
    partial = folder / 'result.partial.json'
    partial.write_text(json.dumps(result, allow_nan=False, indent=2))
    os.replace(partial, folder / 'result.json')
    print('Validated research artifacts published', flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
