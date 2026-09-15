"""Read-only attribution of preserved ORB ledgers; never changes exit rules.

Run from the repository root after evaluate-2026.mjs. Initial risk is reconstructed
from the original opening range and signal-close entry. R excludes costs in its
denominator; both gross and net realized R are reported.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/strategy-potential-2026'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def ledger(run, name):
    path = ROOT / 'data/workbench/runs' / run['id'] / name
    expected = next(a['checksum'] for a in run['result']['artifacts'] if a['name'] == name)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, path
    return pd.read_csv(path)


def stats(trades):
    pnl = trades.net_pnl
    win, loss = pnl[pnl > 0], pnl[pnl < 0]
    return {
        'trades': len(trades), 'wins': len(win), 'losses': len(loss),
        'breakeven': int((pnl == 0).sum()), 'net_pnl': float(pnl.sum()),
        'gross_pnl': float(trades.gross_pnl.sum()), 'costs': float(trades.cost.sum()),
        'win_rate': float((pnl > 0).mean()) if len(trades) else None,
        'average_win': float(win.mean()) if len(win) else None,
        'average_loss': float(-loss.mean()) if len(loss) else None,
        'payoff_ratio': float(win.mean() / -loss.mean()) if len(win) and len(loss) else None,
        'profit_factor': float(win.sum() / -loss.sum()) if len(loss) else None,
        'expectancy': float(pnl.mean()) if len(trades) else None,
    }


def analyze(run, label, raw):
    t = ledger(run, 'trades.csv')
    p = run['input']['parameters']
    q = run['input']['dataset']
    assert p['require_close_break'] and run['input']['timeframe'] == '5m'
    local = raw.index.tz_convert(p['timezone'])
    minute = local.hour * 60 + local.minute
    opening = raw.loc[(minute >= p['opening_start']) & (minute < p['opening_end'])].copy()
    opening['date'] = opening.index.tz_convert(p['timezone']).strftime('%Y-%m-%d')
    ranges = opening.groupby('date').agg(high=('high', 'max'), low=('low', 'min'))
    if len(t):
        entry = pd.to_datetime(t.entry_time, utc=True)
        end = pd.to_datetime(t.exit_time, utc=True)
        days = entry.dt.tz_convert(p['timezone']).dt.strftime('%Y-%m-%d')
        assert days.isin(ranges.index).all(), 'Missing opening range'
        t['initial_stop'] = [ranges.loc[d, 'low' if qty > 0 else 'high'] for d, qty in zip(days, t.quantity)]
        t['initial_risk_usd'] = (t.entry - t.initial_stop).abs() * t.quantity.abs() * q['point_value']
        assert (t.initial_risk_usd > 0).all() and (t.initial_risk_usd <= p['risk_budget'] + 1e-6).all()
        t['initial_target'] = t.entry + np.sign(t.quantity) * p['reward_risk'] * (t.entry - t.initial_stop).abs()
        t['gross_r'] = t.gross_pnl / t.initial_risk_usd
        t['net_r'] = t.net_pnl / t.initial_risk_usd
        t['holding_minutes'] = (end - entry).dt.total_seconds() / 60
        t['exit_month'] = end.dt.tz_convert(p['timezone']).dt.strftime('%Y-%m')
        t['crossed_local_date'] = days != end.dt.tz_convert(p['timezone']).dt.strftime('%Y-%m-%d')
        flat_days = local[(minute >= p['flatten_start']) & (minute < p['flatten_end'])].strftime('%Y-%m-%d')
        flat_counts = pd.Series(flat_days).value_counts()
        t['source_minutes_in_entry_day_flatten_window'] = days.map(flat_counts).fillna(0).astype(int)
        t['direction'] = np.where(t.quantity > 0, 'Long', 'Short')
        assert np.allclose(t.gross_pnl, (t.exit - t.entry) * t.quantity * q['point_value'])
        # Target and stop fills can improve or worsen at a gap; otherwise equal bracket levels.
        target = t[t.exit_reason == 'limit']
        stop = t[t.exit_reason == 'stop']
        assert (target.gross_r >= p['reward_risk'] - 1e-6).all()
        assert (stop.gross_r <= -1 + 1e-6).all()
        assert np.allclose(t.net_pnl, t.gross_pnl - t.cost)
        expected_cost = t.quantity.abs() * (2 * run['input']['fee'] + run['input']['slippage'] * q['tick_size'] * q['point_value'] * np.where(t.exit_reason == 'limit', 1, 2))
        assert np.allclose(t.cost, expected_cost)
    assert len(t) == run['result']['metrics']['trades']
    assert abs(t.net_pnl.sum() - run['result']['metrics']['net_pnl']) < 0.01
    groups = []
    for reason, group in t.groupby('exit_reason'):
        groups.append({'exit_reason': reason, **stats(group),
                       'mean_gross_r': float(group.gross_r.mean()), 'mean_net_r': float(group.net_r.mean()),
                       'mean_initial_risk': float(group.initial_risk_usd.mean()),
                       'median_holding_minutes': float(group.holding_minutes.median())})
    monthly = t.groupby('exit_month').agg(trades=('net_pnl','size'), net_pnl=('net_pnl','sum')).reset_index().to_dict('records') if len(t) else []
    top = t.nlargest(min(5, len(t)), 'net_pnl')
    overnight = t[t.crossed_local_date] if len(t) else t
    summary = {'period': label, 'run_id':run['id'], **stats(t), 'target_rr':p['reward_risk'],
               'mean_gross_r':float(t.gross_r.mean()) if len(t) else None,
               'mean_net_r':float(t.net_r.mean()) if len(t) else None,
               'net_excluding_best_5':float(t.net_pnl.sum() - top.net_pnl.sum()),
               'best_5_net_pnl':float(top.net_pnl.sum()), 'best_trade_count':len(top), 'exit_groups':groups, 'monthly':monthly,
               'overnight_trades': overnight[['entry_time','exit_time','exit_reason','net_pnl','source_minutes_in_entry_day_flatten_window']].to_dict('records') if len(overnight) else [],
               'long_short':{d:stats(g) for d,g in t.groupby('direction')} if len(t) else {}}
    t.to_csv(OUT / f'orb-exits-{label}.csv', index=False, encoding='utf-8')
    return summary


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for year in ['2025', '2026']:
        detail = read_json(ROOT / f'reports/strategy-potential-{year}/pine-tsmom-orb.json')
        baseline = next(r for r in detail['evaluation']['runs'] if r['input']['research']['scenario'] == 'Baseline')
        records.append((year if year == '2025' else '2026-Jan-Aug', baseline))
        if year == '2026':
            records.append(('2026-Sep-partial', detail['september']))
    dataset = records[0][1]['input']['dataset']
    assert all(r['input']['dataset']['checksum'] == dataset['checksum'] for _, r in records)
    assert hashlib.sha256(Path(dataset['path']).read_bytes()).hexdigest() == dataset['checksum']
    raw = pd.read_parquet(dataset['path'], filters=[('ts_event','>=',pd.Timestamp('2025-01-01',tz='UTC'))])
    results = [analyze(r, label, raw) for label, r in records]
    (OUT / 'orb-exit-analysis.json').write_text(json.dumps(results,indent=2,allow_nan=False), encoding='utf-8')
    dollars = lambda x: f'${x:,.2f}'
    ratio = lambda x: 'undefined' if x is None else f'{x:.3f}'
    lines = ['# ORB exit analysis', '',
             'Full, checksum-verified baseline trade ledgers. Existing exits and parameters are unchanged.', '',
             'Initial risk is the signal-close entry distance to the opposite opening-range edge, multiplied by contract size and point value. Gross/net R divide each trade by that initial dollar risk; costs are excluded from the risk denominator. Dollar payoff ratio instead compares average winning and losing dollar amounts. These are different measures.', '',
             'The force-flat window begins with the 15:45 New York five-minute bar and normally executes at its 15:50 close. Stops and targets may exit earlier. September is an independent run starting flat, not a continuation of August.', '']
    for s in results:
        lines += [f"## {s['period']}", '',
                  f"Run `{s['run_id']}`. {s['trades']} trades; net {dollars(s['net_pnl'])}; costs {dollars(s['costs'])}; average win {ratio(s['average_win'])}, average loss {ratio(s['average_loss'])}; realized dollar payoff {ratio(s['payoff_ratio'])}:1; profit factor {ratio(s['profit_factor'])}; mean net R {ratio(s['mean_net_r'])}.", '',
                  '| Exit | Trades | Wins | Net P&L | Average net P&L | Average initial risk | Mean gross R | Mean net R | Median minutes held |',
                  '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
        for g in s['exit_groups']:
            lines.append(f"| {g['exit_reason']} | {g['trades']} | {g['wins']} | {dollars(g['net_pnl'])} | {dollars(g['expectancy'])} | {dollars(g['mean_initial_risk'])} | {g['mean_gross_r']:.3f} | {g['mean_net_r']:.3f} | {g['median_holding_minutes']:.1f} |")
        lines += ['', f"Best {s['best_trade_count']} trades contributed {dollars(s['best_5_net_pnl'])}; removing those trades arithmetically leaves {dollars(s['net_excluding_best_5'])}. This is a concentration diagnostic, not a simulated rule or an estimate of expected performance.", '',
                  '| Exit month | Trades | Closed-trade net P&L |', '| --- | ---: | ---: |']
        lines += [f"| {m['exit_month']} | {m['trades']} | {dollars(m['net_pnl'])} |" for m in s['monthly']]
        lines += ['']
        if s['overnight_trades']:
            lines += ['### Positions carried beyond the entry date', '',
                      '| Entry | Exit | Reason | Net P&L | Source minutes in entry-day flatten window |',
                      '| --- | --- | --- | ---: | ---: |']
            lines += [f"| {r['entry_time']} | {r['exit_time']} | {r['exit_reason']} | {dollars(r['net_pnl'])} | {r['source_minutes_in_entry_day_flatten_window']} |" for r in s['overnight_trades']]
            lines += ['', 'Dates are compared in the strategy timezone. A stop or target exit can also occur after an overnight hold; the exit-reason label alone does not identify every overnight position.', '']
    lines += ['## Interpretation and limits', '',
              'A 2R target applies only when a target fills. Scheduled exits can close winners below 2R and losses before -1R. Different opening-range widths mean trades have different dollar risks even at one contract; average winner/loser dollars therefore need not equal the target multiple. Costs reduce realized payoff further.', '',
              'Exit-group outcomes describe trades that reached each exit. They do not show what would have happened if timed exits were removed or changed. No alternative exit rule was selected using 2026 results.', '',
              'Monthly values attribute full trade P&L to exit month; dashboard monthly returns use marked equity and can differ. Initial stops/targets are reconstructed from unchanged opening-range rules and original minute bars. Intraminute path, margin liquidation and roll-neutral returns remain unmodeled.', '']
    (OUT / 'ORB_EXITS.md').write_text('\n'.join(lines), encoding='utf-8')
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), layout='constrained')
    for ax, s in zip(axes, results[:2]):
        groups = s['exit_groups']
        values = [g['net_pnl'] for g in groups]
        ax.bar([g['exit_reason'] for g in groups], values, color=['#247c63' if v >= 0 else '#b84c4c' for v in values])
        ax.axhline(0, color='#555', linewidth=.8)
        ax.set_title(f"ORB {s['period']}: exit contributions")
        ax.set_ylabel('Net P&L (USD)')
        for i, (g,v) in enumerate(zip(groups,values)):
            ax.annotate(f"${v:,.0f}\n{g['trades']} trades",(i,v),xytext=(0,5 if v>=0 else -5),textcoords='offset points',ha='center',va='bottom' if v>=0 else 'top',fontsize=9)
        ax.margins(y=.22)
    fig.savefig(OUT / 'orb-exit-contributions.png', dpi=170)
    fig.savefig(OUT / 'orb-exit-contributions.svg')
    plt.close(fig)
    print(json.dumps([{k:v for k,v in s.items() if k not in ['monthly','exit_groups','long_short']} for s in results],indent=2))


if __name__ == '__main__':
    main()
