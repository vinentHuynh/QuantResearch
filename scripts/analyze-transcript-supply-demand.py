"""Frozen, reproducible transcript research; no broker access or data purchases.

Uses registered workbench datasets, its checksum and metrics helpers, and a
separate stop-entry simulator because event-v1 does not support entry stops.
Run --declare first, then --run; --report regenerates tables from saved ledgers.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import shutil
import sys
import traceback
import urllib.request

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workbench.contract import checksum
from workbench.metrics import calculate

OUT = ROOT / 'reports/transcript-supply-demand-2026-09-24'
CAPITAL = 100000.0
END = '2026-08-01'
BASE = dict(pivot_len=2, stop_model='zone', rr=1.0, use_htf=True,
            require_fvg=True, max_age=288)
VARIANTS = {
    'baseline': {}, 'candle_stop': {'stop_model': 'candle'},
    'target_2r': {'rr': 2.0}, 'target_3r': {'rr': 3.0},
    'swing_1': {'pivot_len': 1}, 'swing_3': {'pivot_len': 3},
    'without_hourly_control': {'use_htf': False},
    'without_fvg_control': {'require_fvg': False},
}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding='utf-8')


def declare():
    if (OUT / 'protocol.json').exists():
        return json.loads((OUT / 'protocol.json').read_text())
    with urllib.request.urlopen('http://127.0.0.1:8001/api/workbench/state?view=summary', timeout=60) as response:
        state = json.load(response)
    datasets = []
    for symbol in ['MNQ', 'NQ', 'ES', 'YM', 'CL']:
        d = next(d for d in state['datasets'] if d['symbol'] == symbol)
        if checksum(d['path']) != d['checksum']:
            raise ValueError(f'Dataset checksum mismatch: {symbol}')
        datasets.append(dict(symbol=symbol, files=[dict(path=d['path'], checksum=d['checksum'])],
                             dataset_id=d['id'], tick_size=d['tick_size'], point_value=d['point_value'],
                             fee=1.25 if symbol == 'MNQ' else 2.5, execution_minutes=1,
                             start='2022-01-01', end=END, warnings=d.get('warnings', [])))
    mgc_files = sorted((ROOT / 'data/_dbn_cache').glob('MGC.v.0_*_1m.parquet'))
    mgc_files = [p for p in mgc_files if int(p.name.split('_')[1][:4]) >= 2021]
    if len(mgc_files) != 6:
        raise ValueError('Expected six 2021-2026 MGC minute cache chunks')
    datasets.insert(0, dict(symbol='MGC', files=[dict(path=str(p), checksum=checksum(p)) for p in mgc_files],
                          tick_size=.1, point_value=10, fee=1.25, execution_minutes=1,
                          start='2022-01-01', end=END,
                          warnings=['Unregistered local Databento MGC.v.0 minute caches, checksummed here.',
                                    'No instrument IDs: unadjusted roll jumps cannot be identified or removed exactly.',
                                    'Gold futures are a proxy for the unspecified gold feed in the video.']))
    gc = ROOT / 'data/GC_5min_databento.parquet'
    datasets.append(dict(symbol='GC', files=[dict(path=str(gc), checksum=checksum(gc))],
                         tick_size=.1, point_value=100, fee=2.5, execution_minutes=5,
                         start='2024-09-11', end=END,
                         warnings=['Local 5m cache, no underlying minutes or instrument IDs retained.',
                                   'Shorter coverage; correlated gold comparison, not independent replication.']))
    protocol = dict(declared_at=datetime.now(timezone.utc).isoformat(),
        question='Does the transcript define a positive net-expectancy, stable supply/demand retest model?',
        status='Historical exploratory validation; previously inspected repository history is not a fresh holdout.',
        periods={'development': ['2022-01-01', '2025-01-01'],
                 'later_2025': ['2025-01-01', '2026-01-01'],
                 'latest_2026': ['2026-01-01', END]},
        selection='All eight variants on all seven markets declared before results; no optimized winner selected.',
        variants={name: BASE | value for name, value in VARIANTS.items()}, datasets=datasets,
        capital=CAPITAL, contracts=1, slippage_ticks=1, warmup_days=30,
        rules=[
            '5m signals, strict confirmed symmetric pivots, latest unused swing broken by a close determines trend.',
            'Hourly trend from the last hour completed at chart-bar OPEN; no developing-hour leakage.',
            'Last opposite candle fixed at two bars back; middle candle directional; third-bar wick FVG; final color unrestricted.',
            'Demand proximal=base high, distal=min three lows; supply mirror; confirm only at third close.',
            'Formation and arming require 5m/hourly alignment; no-HTF control removes hourly only.',
            'No-FVG control requires directional departure and confirming close beyond base; not transcript strategy.',
            'Touch on a later chart candle; next chart bar rolls stop-entry beyond the previous high/low by one tick.',
            'Wick beyond distal invalidates; latest eligible zone; 288-chart-bar expiry and 100-zone cap.',
            'Stop beyond zone or preceding candle by one tick; R target computed from actual gap-aware entry.',
            'One position; no same-chart-bar reentry; ambiguity resolved conservatively and counted.',
            'No target credited in intrabar entry candle unless entry at open establishes ordering; stop remains active.',
            'Incomplete aggregate bars cannot form signals; existing brackets still see observed source candles.',
            'Identifiable contract rolls flatten at prior close and reset state; absent IDs remain a limitation.',
            'End-exclusive intervals, final liquidation, fixed one contract; warmup supplies state only.'
        ],
        fees='USD per contract per side: MGC/MNQ 1.25; GC/NQ/ES/YM/CL 2.50. One tick slippage on entry and market/stop exit; target exits fee only.',
        stress='Double both fees and slippage by deducting the saved cost a second time. Fixed-size decisions are cost-independent.',
        candidate_gate='On primary MGC: >=100 later trades, positive 2025 and 2026 P&L, later PF>=1.10, positive later doubled-cost P&L, weekly-cluster 95% mean-R interval lower>0. Also require stable nearby rules and independent cross-market support before calling it working.',
        uncertainty='2000 seeded occupied-week bootstrap draws of net-R sum / trade count; pointwise exploratory intervals, not multiplicity-corrected.',
        engine_reason='Workbench event-v1 only supports close/next-open entry, which would change the transcript. Separate simulator reuses workbench checksums/metrics and preserves source/data identities without modifying prior runs.',
        sources=[
            'https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/',
            'https://www.tradingview.com/pine-script-docs/concepts/strategies/',
            'https://www.cmegroup.com/education/lessons/micro-gold-and-micro-silver-futures-product-overview',
            'https://www.cmegroup.com/education/courses/event-contracts-underlying-markets/product-gold'
        ])
    save(OUT / 'protocol.json', protocol)
    source = Path(r'C:\Users\vince\.codex\attachments\0bc5c214-4c73-44a2-ae50-7d77babfd3ad\pasted-text.txt')
    shutil.copy2(source, OUT / 'transcript.txt')
    print(f'Declared {len(datasets) * len(VARIANTS)} cases before results.', flush=True)
    return protocol


def load_market(d):
    chunks = []
    lower = pd.Timestamp(d['start'], tz='UTC') - pd.Timedelta(days=30)
    upper = pd.Timestamp(d['end'], tz='UTC')
    for item in d['files']:
        if checksum(item['path']) != item['checksum']:
            raise ValueError('Input changed after declaration: ' + item['path'])
        f = pd.read_parquet(item['path'])
        f.index = f.index.tz_convert('UTC')
        chunks.append(f.loc[(f.index >= lower) & (f.index < upper)])
    result = pd.concat(chunks).sort_index()
    if result.index.has_duplicates:
        raise ValueError('Overlapping market inputs; no silent deduplication')
    return result


def bootstrap_r(trades):
    if len(trades) < 20:
        return [None, None]
    weeks = pd.to_datetime(trades.exit_time, utc=True).dt.strftime('%G-%V')
    sums = trades.assign(week=weeks).groupby('week').agg(total=('net_r', 'sum'), count=('net_r', 'size'))
    if len(sums) < 10:
        return [None, None]
    rng = np.random.default_rng(24092026)
    ix = rng.integers(0, len(sums), size=(2000, len(sums)))
    means = sums.total.to_numpy()[ix].sum(axis=1) / sums['count'].to_numpy()[ix].sum(axis=1)
    return np.quantile(means, [.025, .975]).tolist()


def summarize(trades, equity):
    result = calculate(equity, CAPITAL, trades)
    if len(trades):
        wins = trades.net_pnl > 0
        losses = -trades.loc[trades.net_pnl < 0, 'net_pnl'].sum()
        net2 = trades.net_pnl - trades.cost
        result.update(win_rate=float(wins.mean()),
                      profit_factor=float(trades.loc[wins, 'net_pnl'].sum() / losses) if losses else None,
                      gross_pnl=float(trades.gross_pnl.sum()), costs=float(trades.cost.sum()),
                      mean_net_r=float(trades.net_r.mean()), expectancy=float(trades.net_pnl.mean()),
                      double_cost_net=float(net2.sum()), mean_r_95ci=bootstrap_r(trades),
                      roll_trades=int((trades.exit_reason == 'contract-roll').sum()),
                      net_without_roll_trades=float(trades.loc[trades.exit_reason != 'contract-roll', 'net_pnl'].sum()),
                      ambiguous_trades=int((trades.ambiguous_entry | trades.ambiguous_exit).sum()),
                      ambiguous_trade_net=float(trades.loc[trades.ambiguous_entry | trades.ambiguous_exit, 'net_pnl'].sum()),
                      largest_five_share=float(trades.net_pnl.nlargest(5).sum() / trades.net_pnl.sum()) if trades.net_pnl.sum() > 0 else None)
    else:
        result.update(win_rate=None, profit_factor=None, gross_pnl=0., costs=0., mean_net_r=None,
                      expectancy=None, double_cost_net=0., mean_r_95ci=[None, None], largest_five_share=None)
    values = equity.equity.to_numpy()
    result['max_drawdown_dollars'] = float((np.maximum.accumulate(np.r_[CAPITAL, values])[1:] - values).max())
    return result


def extreme_query(values, left, right, minimum=True):
    """Vectorized half-open range queries; used only for descriptive FUTURE outcomes."""
    n = 1 << (len(values) - 1).bit_length()
    neutral = np.inf if minimum else -np.inf
    op = np.minimum if minimum else np.maximum
    tree = np.full(2 * n, neutral)
    tree[n:n + len(values)] = values
    size = n
    while size > 1:
        tree[size // 2:size] = op(tree[size:2 * size:2], tree[size + 1:2 * size:2])
        size //= 2
    a, b = left.copy() + n, right.copy() + n
    answer = np.full(len(left), neutral)
    while np.any(a < b):
        mask = (a < b) & (a % 2 == 1)
        answer[mask] = op(answer[mask], tree[a[mask]])
        a[mask] += 1
        mask = (a < b) & (b % 2 == 1)
        b[mask] -= 1
        answer[mask] = op(answer[mask], tree[b[mask]])
        a //= 2
        b //= 2
    return answer


def gap_study(frame, d, folder):
    """All 3-candle FVGs; 72 elapsed hours after confirmation, never trading input."""
    rule = dict(open='first', high='max', low='min', close='last', volume='sum')
    bars = frame.resample('5min').agg(rule)
    counts = frame.close.resample('5min').count()
    bars = bars.loc[counts == 5 // d['execution_minutes']]
    idx = bars.index
    high, low = bars.high.to_numpy(), bars.low.to_numpy()
    contiguous = np.r_[False, False, (idx[2:].as_unit('ns').asi8 - idx[:-2].as_unit('ns').asi8) == 600_000_000_000]
    bull = np.r_[False, False, low[2:] > high[:-2]] & contiguous
    bear = np.r_[False, False, high[2:] < low[:-2]] & contiguous
    summary, records = {}, []
    for side, mask in [('bull', bull), ('bear', bear)]:
        ids = np.flatnonzero(mask & (idx >= pd.Timestamp(d['start'], tz='UTC')))
        confirm = idx[ids] + pd.Timedelta(minutes=5)
        deadline = confirm + pd.Timedelta(hours=72)
        keep = deadline <= frame.index[-1] + pd.Timedelta(minutes=d['execution_minutes'])
        ids, confirm, deadline = ids[keep], confirm[keep], deadline[keep]
        # Source bars rather than only complete chart bars supply observed fills.
        left = frame.index.searchsorted(confirm)
        right = frame.index.searchsorted(deadline - pd.Timedelta(minutes=d['execution_minutes']), side='right')
        observed = extreme_query(frame.low.to_numpy() if side == 'bull' else frame.high.to_numpy(), left, right, side == 'bull')
        near = low[ids] if side == 'bull' else high[ids]
        far = high[ids - 2] if side == 'bull' else low[ids - 2]
        hit = observed <= far if side == 'bull' else observed >= far
        midpoint = observed <= (near + far) / 2 if side == 'bull' else observed >= (near + far) / 2
        edge = observed <= near if side == 'bull' else observed >= near
        summary[side] = dict(eligible=int(len(ids)), full_fills=int(hit.sum()), full_fill_rate=float(hit.mean()) if len(hit) else None,
                             midpoint_rate=float(midpoint.mean()) if len(hit) else None, near_edge_rate=float(edge.mean()) if len(hit) else None)
        records.append(pd.DataFrame(dict(confirmation=confirm, deadline=deadline, side=side, near=near, far=far,
                                         future_extreme=observed, full_fill=hit, midpoint=midpoint, edge=edge)))
    pd.concat(records).to_csv(folder / 'fvg-72h.csv', index=False)
    summary['definition'] = 'All contiguous complete three-bar gaps, measured after confirmation over72 elapsed hours; full observation window required. Reaching/passing far edge counts. Overlapping events, weekends, gaps and unadjusted rolls remain; descriptive fill rate is not win rate.'
    save(folder / 'fvg-72h.json', summary)


def run_market(d, protocol):
    from strategies._transcript_supply_demand import prepare_data, run_model
    folder = OUT / d['symbol']
    folder.mkdir(parents=True, exist_ok=True)
    frame = load_market(d)
    gap_study(frame, d, folder)
    prepared = {}
    for name, params in protocol['variants'].items():
        destination = folder / name
        destination.mkdir(exist_ok=True)
        if (destination / 'result.json').exists():
            print(f'{d["symbol"]}/{name}: existing artifact retained', flush=True)
            continue
        save(destination / 'input.json', dict(dataset=d, parameters=params, protocol_checksum=checksum(OUT / 'protocol.json')))
        try:
            p = params['pivot_len']
            if p not in prepared:
                prepared[p] = prepare_data(frame, pivot_len=p, execution_minutes=d['execution_minutes'])
            outcome = run_model(prepared[p], params, start=d['start'], end=d['end'],
                                tick_size=d['tick_size'], point_value=d['point_value'], fee=d['fee'], slippage_ticks=1)
            trades, equity = outcome['trades'], outcome['equity']
            if 'timestamp' not in equity:
                equity = equity.reset_index().rename(columns={equity.index.name or 'index': 'timestamp'})
            trades['net_r'] = trades.net_pnl / (trades.risk * d['point_value']) if len(trades) else pd.Series(dtype=float)
            # Engine capital defaults to100000; do not silently rebase inconsistent ledgers.
            np.testing.assert_allclose(equity.equity.iloc[-1] - CAPITAL, trades.net_pnl.sum(), rtol=0, atol=1e-5)
            np.testing.assert_allclose(trades.gross_pnl.sum() - trades.cost.sum(), trades.net_pnl.sum(), rtol=0, atol=1e-5)
            trades.to_csv(destination / 'trades.csv', index=False)
            equity.to_parquet(destination / 'equity.parquet', index=False)
            periods = {'all': summarize(trades, equity)}
            for label, (lo, hi) in protocol['periods'].items():
                times = pd.to_datetime(equity.timestamp, utc=True)
                mask = (times >= pd.Timestamp(lo, tz='UTC')) & (times < pd.Timestamp(hi, tz='UTC'))
                part = equity.loc[mask].copy()
                if part.empty:
                    continue
                prior = equity.loc[times < pd.Timestamp(lo, tz='UTC'), 'equity']
                start_value = float(prior.iloc[-1]) if len(prior) else CAPITAL
                part['equity'] += CAPITAL - start_value
                exits = pd.to_datetime(trades.exit_time, utc=True)
                cohort = trades.loc[(exits >= pd.Timestamp(lo, tz='UTC')) & (exits < pd.Timestamp(hi, tz='UTC'))]
                periods[label] = summarize(cohort, part)
                periods[label]['closed_trade_pnl'] = float(cohort.net_pnl.sum())
            result = dict(status='succeeded', periods=periods, diagnostics=outcome.get('diagnostics', {}),
                          artifacts={p.name: checksum(p) for p in destination.glob('*') if p.name != 'result.json'})
            save(destination / 'result.json', result)
            m = periods['all']
            print(f'{d["symbol"]}/{name}: {m["trades"]} trades net${m["net_pnl"]:.2f} PF{m["profit_factor"]}', flush=True)
        except Exception:
            error = traceback.format_exc()
            save(destination / 'failed.json', dict(status='failed', error=error))
            print(f'{d["symbol"]}/{name}: FAILED\n{error}', flush=True)
    return d['symbol']


def report():
    protocol = json.loads((OUT / 'protocol.json').read_text())
    rows = []
    for d in protocol['datasets']:
        for name in protocol['variants']:
            path = OUT / d['symbol'] / name / 'result.json'
            if not path.exists():
                rows.append(dict(symbol=d['symbol'], variant=name, period='all', status='failed_or_incomplete'))
                continue
            result = json.loads(path.read_text())
            for period, m in result['periods'].items():
                rows.append(dict(symbol=d['symbol'], variant=name, period=period, status=result['status'],
                                 **{k: m.get(k) for k in ['trades', 'net_pnl', 'closed_trade_pnl', 'gross_pnl', 'costs', 'profit_factor', 'win_rate', 'mean_net_r', 'expectancy', 'double_cost_net', 'max_drawdown_dollars', 'sharpe']},
                                 ci_low=m['mean_r_95ci'][0], ci_high=m['mean_r_95ci'][1]))
    table = pd.DataFrame(rows)
    table.to_csv(OUT / 'all-results.csv', index=False)
    print(table.loc[(table.variant == 'baseline') & (table.period == 'all')].to_string(index=False))
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--declare', action='store_true')
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--symbols', default='')
    ap.add_argument('--workers', type=int, default=2)
    args = ap.parse_args()
    protocol = declare()
    if args.run:
        snap = OUT / 'source'
        sources = ['scripts/analyze-transcript-supply-demand.py', 'strategies/_transcript_supply_demand.py',
                   'workbench/metrics.py', 'workbench/contract.py', 'strategy_engine/sessions.py']
        for file in sources:
            destination = snap / file
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and checksum(destination) != checksum(ROOT / file):
                raise RuntimeError('Source changed after run snapshot; preserve earlier attempts and use an explicit new campaign.')
            shutil.copy2(ROOT / file, destination)
        save(OUT / 'source-manifest.json', {file: checksum(ROOT / file) for file in sources})
        save(OUT / 'environment.json', dict(python=sys.version, platform=platform.platform(),
                                           numpy=np.__version__, pandas=pd.__version__,
                                           declared_protocol_checksum=checksum(OUT / 'protocol.json')))
        selected = [d for d in protocol['datasets'] if not args.symbols or d['symbol'] in args.symbols.split(',')]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_market, d, protocol): d['symbol'] for d in selected}
            for job in as_completed(futures):
                try:
                    print(f'Completed market {job.result()}', flush=True)
                except Exception:
                    error = traceback.format_exc()
                    save(OUT / futures[job] / 'market-failed.json', dict(error=error))
                    print(error, flush=True)
        report()
    elif args.report:
        report()


if __name__ == '__main__':
    main()
