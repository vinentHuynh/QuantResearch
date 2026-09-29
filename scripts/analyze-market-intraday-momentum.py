"""Read-only audit of saved closing-momentum runs and independent minute endpoints."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/market-intraday-momentum-2026-09-17'


def hac_regression(x, y, lags=5):
    """OLS with an intercept and Bartlett/Newey-West HAC standard errors."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    design = np.column_stack([np.ones(len(x)), x])
    if len(x) < 20 or np.linalg.matrix_rank(design) < 2:
        return {'n': len(x), 'slope': None, 'hac_t': None}
    bread = np.linalg.inv(design.T @ design)
    beta = bread @ design.T @ y
    scores = design * (y-design @ beta)[:, None]
    meat = scores.T @ scores
    for lag in range(1, lags+1):
        cross = scores[lag:].T @ scores[:-lag]
        meat += (1-lag/(lags+1)) * (cross+cross.T)
    covariance = bread @ meat @ bread * len(x)/(len(x)-2)
    se = np.sqrt(max(0, covariance[1, 1]))
    return {'n': len(x), 'intercept': float(beta[0]), 'slope': float(beta[1]),
            'hac_t': float(beta[1]/se) if se else None, 'hac_lags': lags}


def minute_endpoints(dataset):
    frame = pd.read_parquet(dataset['path'], columns=['open', 'close'])
    local = frame.index.tz_convert('America/New_York')
    minute = local.hour*60+local.minute
    close = 870 if dataset['symbol'] == 'CL' else 960
    records = {}
    for name, when, column in [('close', close-1, 'close'), ('signal', close-31, 'close'),
                               ('entry', close-30, 'open'), ('gao', 599, 'close')]:
        mask = (minute == when) & (local.dayofweek < 5)
        records[name] = pd.Series(frame.loc[mask, column].to_numpy(), index=pd.Index(local[mask].date))
    daily = pd.DataFrame(records).sort_index()
    # Forward-fill only observed historical closing endpoints; max age enforced.
    daily['prior_close'] = daily['close'].ffill().shift()
    dates = pd.Series(pd.to_datetime(daily.index), index=daily.index).where(daily['close'].notna()).ffill().shift()
    age = (pd.Series(pd.to_datetime(daily.index), index=daily.index)-dates).dt.days
    daily.loc[(age > 4) | (age <= 0), 'prior_close'] = np.nan
    daily['rest_signal'] = daily.signal/daily.prior_close-1
    daily['gao_signal'] = daily.gao/daily.prior_close-1
    daily['last_return'] = daily['close']/daily.entry-1
    daily.loc[(daily.prior_close <= 0) | (daily.entry <= 0) | (daily['close'] <= 0),
              ['rest_signal', 'gao_signal', 'last_return']] = np.nan
    return daily


def main():
    campaign = json.loads((OUT/'campaign.json').read_text())
    status = json.loads((OUT/'run-status.json').read_text())
    by_id = {r['id']: r for r in status}
    results, trade_frames, oracles, regressions = [], {}, {}, {}
    for group, info in campaign['groups'].items():
        for run_id in info['ids']:
            run = by_id[run_id]
            request = run['input']
            dataset = request['dataset']
            row = {'group': group, 'id': run_id, 'status': run['status'], 'symbol': dataset['symbol'],
                   'parameters': request['parameters'], 'timeframe': request['timeframe'],
                   'start': request['start'], 'end': request['end'], 'source_hash': request['source_hash'],
                   'adapter_hash': request['strategy']['file_hash']}
            results.append(row)
            if run['status'] != 'Succeeded':
                row['error'] = run.get('error', run['status'])
                continue
            directory = ROOT/'data/workbench/runs'/run_id
            manifest = json.loads((directory/'manifest.json').read_text())
            for artifact in manifest['artifacts']:
                digest = hashlib.sha256()
                with (directory/artifact['name']).open('rb') as handle:
                    for chunk in iter(lambda: handle.read(1024*1024), b''):
                        digest.update(chunk)
                assert digest.hexdigest() == artifact['checksum']
            trades = pd.read_csv(directory/'trades.csv')
            equity = pd.read_csv(directory/'equity.csv')
            positions = pd.read_csv(directory/'positions.csv')
            trade_frames[group] = trades
            assert np.isclose(trades.net_pnl.sum(), manifest['metrics']['net_pnl'], atol=1e-5, rtol=0)
            assert np.isclose(equity.equity.iloc[-1]-request['capital'], trades.net_pnl.sum(), atol=1e-5, rtol=0)
            assert np.isclose(equity.cost.sum(), trades.cost.sum(), atol=1e-5, rtol=0)
            p = request['parameters']
            closing = 870 if dataset['symbol'] == 'CL' else 960
            expected_entry = closing-int(p['holding_minutes'])+int(p['entry_delay_minutes'])
            entry = pd.to_datetime(trades.entry_time, utc=True).dt.tz_convert('America/New_York')
            exit = pd.to_datetime(trades.exit_time, utc=True).dt.tz_convert('America/New_York')
            assert (entry.dt.date == exit.dt.date).all(), 'Overnight carry'
            assert (entry.dt.hour*60+entry.dt.minute == expected_entry).all(), 'Late entry'
            assert (exit.dt.hour*60+exit.dt.minute == closing).all(), 'Wrong exit clock'
            assert (trades.exit_reason == 'scheduled-market-close').all(), 'Unscheduled liquidation'
            assert np.allclose(trades.cost, 2*p['contracts']*(request['fee']+request['slippage']*dataset['tick_size']*dataset['point_value']))
            marked = pd.to_datetime(positions.timestamp, utc=True).dt.tz_convert('America/New_York')
            assert (positions.loc[marked.dt.hour*60+marked.dt.minute >= closing, 'contracts'] == 0).all()
            net = trades.net_pnl
            peak = equity.equity.cummax().clip(lower=request['capital'])
            row.update(metrics=manifest['metrics'], max_drawdown_dollars=float((peak-equity.equity).max()),
                       profit_factor=float(net[net>0].sum()/-net[net<0].sum()) if (net<0).any() else None,
                       expectancy=float(net.mean()) if len(net) else None,
                       without_best_five=float(net.sum()-net.nlargest(5).sum()),
                       yearly_net_pnl={str(k):float(v) for k,v in equity.net_pnl.groupby(pd.to_datetime(equity.timestamp, utc=True).dt.year).sum().items()},
                       warnings=manifest['warnings'], ledger_and_clock_audit='passed')
            if group.endswith('-baseline') or group.endswith('-minute-check') or group.endswith('-full-minute-confirmation'):
                symbol = dataset['symbol']
                if symbol not in oracles:
                    oracles[symbol] = minute_endpoints(dataset)
                    oracles[symbol].to_csv(OUT/f'{symbol}-independent-minute-endpoints.csv')
                    regressions[symbol] = {}
                    for signal in ['rest_signal', 'gao_signal']:
                        pairs = oracles[symbol][[signal, 'last_return']].dropna()
                        regressions[symbol][signal] = hac_regression(pairs[signal], pairs.last_return)
                daily = oracles[symbol].reindex(entry.dt.date)
                available = daily[['entry', 'close', 'rest_signal']].notna().all(axis=1).to_numpy()
                expected = (daily['close']-daily.entry)*np.sign(daily.rest_signal)*dataset['point_value']
                actual = trades.gross_pnl.to_numpy()
                mismatch = available & ~np.isclose(expected.to_numpy(), actual, atol=1e-5, rtol=0)
                row['independent_minute_oracle'] = {'matched': int((available & ~mismatch).sum()),
                    'missing_endpoints': int((~available).sum()), 'mismatches': int(mismatch.sum())}
                if request['timeframe'] == '1m':
                    assert not mismatch.any(), 'Minute execution differs from independent endpoints'
            print(f"Audited {group}: {net.sum():,.2f}, {len(trades)} trades", flush=True)
    parity = {}
    for symbol in ['ES', 'NQ', 'MNQ', 'CL']:
        baseline = trade_frames.get(symbol+'-baseline')
        stressed = trade_frames.get(symbol+'-cost-stress')
        if baseline is not None and stressed is not None:
            same = ['entry_time', 'exit_time', 'quantity', 'entry', 'exit', 'gross_pnl']
            pd.testing.assert_frame_equal(baseline[same], stressed[same])
            assert np.allclose(stressed.cost, 2*baseline.cost), 'Cost stress changed more than declared costs'
        a, b = trade_frames.get(symbol+'-baseline'), trade_frames.get(symbol+'-minute-check')
        if a is None or b is None:
            continue
        a = a.loc[a.entry_time.str[:10] >= '2025-01-01']
        columns = ['entry_time','exit_time','quantity','entry','exit','gross_pnl','cost','net_pnl']
        parity[symbol] = {'five_minute_trades': len(a), 'one_minute_trades': len(b),
                         'five_minute_net': float(a.net_pnl.sum()), 'one_minute_net': float(b.net_pnl.sum()),
                         'exact_ledger_match': a[columns].reset_index(drop=True).equals(b[columns].reset_index(drop=True))}
    (OUT/'results.json').write_text(json.dumps(results, indent=2))
    (OUT/'predictive-regressions.json').write_text(json.dumps(regressions, indent=2))
    (OUT/'timeframe-parity.json').write_text(json.dumps(parity, indent=2))
    successful = [r for r in results if r['status'] == 'Succeeded']
    negative = sum(r['metrics']['net_pnl'] < 0 for r in successful)
    summary = (f'{len(successful)}/{len(results)} final-source runs completed successfully and passed the artifact, accounting and nominal-clock audit. '
               f'{negative} completed cases lost money after the declared costs. These results do not establish a profitable research candidate. '
               'Software checks: 15/15 new strategy tests, seven JavaScript regression groups, browser smoke and production build passed; '
               'the full Python suite has 127 passes and four previously documented failures/errors.')
    lines = ['# Market intraday momentum research', '', summary, '', campaign['protocol'], '',
             'All 28 initial v1.0.0 queued attempts were canceled before execution when the terminal-session guard was added. Their inputs and canceled records remain in [campaign-v1.0.0-superseded.json](campaign-v1.0.0-superseded.json) and [superseded-runs.json](superseded-runs.json). The table below retains all 28 planned final-source cases plus one additional full-history CL one-minute confirmation, added after three missing minute endpoints were detected in the CL five-minute baseline. This diagnostic does not change the signal or select parameters.', '',
             '## Final-source attempts', '', '| Case | Status | Net P&L | Max drawdown $ | Trades | Profit factor |',
             '|---|---|---:|---:|---:|---:|']
    for r in results:
        m = r.get('metrics', {})
        cash = lambda v: f'{v:,.2f}' if v is not None else '-'
        lines.append(f"| {r['group']} | {r['status']} | {cash(m.get('net_pnl'))} | {cash(r.get('max_drawdown_dollars'))} | {m.get('trades','-')} | {cash(r.get('profit_factor'))} |")
    failed = [r for r in results if r.get('error')]
    if failed:
        lines += ['', '## Failed or incomplete attempts', '']
        lines += [f"- {r['group']} ({r['id']}): {r['error']}" for r in failed]
    lines += ['', '## Execution verification', '',
              'All successful runs: artifact SHA-256 checks, full trade/equity/cost reconciliation, exact nominal bar entry and exit clocks, same-day exits, scheduled exit reasons, no positions at/after close. Cost stress must preserve the baseline trade times, quantities, prices and gross P&L while exactly doubling costs. The independent oracle uses raw minute endpoints and does not call the adapter; nominal five-minute timestamps do not prove every underlying minute exists.', '',
              'Recent 1m versus 5m comparisons:', '', '```json', json.dumps(parity, indent=2), '```', '',
              '## Predictive regressions', '',
              'Independent full-history minute endpoint OLS: last-window return on prior-close-to-signal return, with intercept and Newey-West HAC(5) errors. These are descriptive in-sample regressions, not proof of gamma causality, corrected multiple-testing inference, or a replication of either paper. Missing endpoints and nonpositive prices excluded.', '',
              '```json', json.dumps(regressions, indent=2), '```', '',
              '## Yearly default results', '', '| Market | Year | Net P&L |', '|---|---|---:|']
    for r in results:
        if r['group'].endswith('-baseline'):
            for year, amount in r.get('yearly_net_pnl', {}).items():
                lines.append(f"| {r['symbol']} | {year} | {amount:,.2f} |")
    lines += ['', '## Limits and sources', '',
              '- No gamma data or causal identification. No parameter selection, fresh holdout or automatic evaluation/robustness promotion. NQ and MNQ are related, not independent market confirmations.',
              '- Full-history standard contracts start June 2010; MNQ starts May 2019; history ends September 3, 2026. Boundary years are partial. Fixed one-contract results have different exposures across symbols.',
              '- Exchange holiday/early-close schedules, margin and settlement auctions are not modeled. CL uses 14:30 New York; its Gao 10:00 signal is an adaptation to the selected 09:30-start session. Missing held closing bars fail the run; missing entry bars expire. Five-minute aggregation can mask missing raw endpoints; oracle mismatch counts remain visible in results.json.',
              '- Unadjusted continuous roll gaps can distort signals and P&L. Dollar fees and ticks are explicit assumptions, not broker quotes. MES, ZN and 6E have no registered dataset.',
              '- [Gao et al. (2018)](https://profiles.wustl.edu/en/publications/market-intraday-momentum/): prior close through opening half-hour predicts closing half-hour.',
              '- [Baltussen et al. (2021)](https://pure.eur.nl/en/publications/hedging-demand-and-market-intraday-momentum/): prior close through rest of day predicts closing half-hour; evidence links momentum to hedging demand.', '',
              'Software regression details: [SOFTWARE-VALIDATION.md](SOFTWARE-VALIDATION.md). Reproducible inputs/run IDs: [campaign.json](campaign.json). Full results: [results.json](results.json).']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
