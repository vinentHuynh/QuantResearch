"""Compare native MNQ January runs with the frozen next-open research engine.

Uses identical session-filtered input, zone construction and flat-start bounds;
compares actual entry/exit prices, direction, entry times and gross P&L. Exit
timestamps differ by the documented intraminute close convention. Boundary
liquidations and different limit-exit costs are checked separately.
"""
import copy
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.mnq import SND_baseline_backtest as source
from strategies._snd_model import SND
from strategy_engine.data import session_bars
from strategy_engine.sessions import get_session
from workbench.contract import checksum

FOLDER = ROOT / 'reports/snd-workbench-adapter-2026-09-16'
ENGINE = ROOT / 'reports/snd-fresh-backtest-2026-09-16/engine_next_open.py'


def main():
    results = []
    for run in json.loads((FOLDER / 'runs.json').read_text(encoding='utf-8')):
        inp = run['input']
        if inp['dataset']['symbol'] != 'MNQ':
            continue
        folder = ROOT / 'data/workbench/runs' / run['id']
        actual = pd.read_csv(folder / 'trades.csv')
        start = pd.Timestamp(inp['start'], tz='UTC')
        end = pd.Timestamp(inp['end'], tz='UTC') + pd.Timedelta(days=1)
        minute = pd.read_parquet(inp['dataset']['path'], filters=[
            ('ts_event', '>=', start - pd.Timedelta(days=inp['warmup_days'])), ('ts_event', '<', end)])
        bars = session_bars(minute, get_session(inp['session']), '1m')
        bars = bars.loc[pd.to_datetime(bars.availability_time, utc=True) < end]
        model = SND(bars, inp['parameters'], inp)
        zones = copy.deepcopy([z for group in model.events.values() for z in group])
        first = {}

        def touch(zone, pos):
            if zone.physical_touch_count == 1:
                first[zone.zone_id] = model.rvol[pos]

        def passes(zone, longs, shorts):
            if model.variant == 'original_multi_tf':
                return True
            if zone.timeframe != '1h' or zone.physical_touch_count != 1:
                return False
            distances = ([o.proximal - zone.proximal for o in shorts if o.proximal > zone.proximal]
                         if zone.direction == 'long' else
                         [zone.proximal - o.proximal for o in longs if o.proximal < zone.proximal])
            if distances and min(distances) < 2 * (zone.width + 1.):
                return False
            return model.variant == 'phase6' or .75 <= first.get(zone.zone_id, np.nan) < 1.25

        namespace = {**source.__dict__, 'on_touch': touch, 'on_mark': lambda *args: None}
        exec(compile(ENGINE.read_text(encoding='utf-8'), str(ENGINE), 'exec'), namespace)
        args = copy.copy(model.args)
        args.point_value, args.cost_ticks, args.min_bars_in_trade = inp['dataset']['point_value'], 0., 1
        reference, _, audit = namespace['replay'](bars, zones, start, None, args, passes)
        ordinary = actual.loc[actual.exit_reason != 'end-of-test'].reset_index(drop=True)
        assert len(ordinary) == len(reference), (model.variant, len(ordinary), len(reference))
        if len(reference):
            np.testing.assert_allclose(ordinary.entry, reference.entry_price, atol=1e-9)
            np.testing.assert_allclose(ordinary['exit'], reference.exit_price, atol=1e-9)
            np.testing.assert_allclose(ordinary.gross_pnl, reference.gross_pnl, atol=1e-7)
            np.testing.assert_array_equal(np.sign(ordinary.quantity), np.where(reference.direction == 'long', 1, -1))
            np.testing.assert_array_equal(pd.to_datetime(ordinary.entry_time, utc=True).astype('int64'), pd.to_datetime(reference.entry_time, utc=True).astype('int64'))
            shift = pd.to_datetime(ordinary.exit_time, utc=True).reset_index(drop=True) - pd.to_datetime(reference.exit_time, utc=True).reset_index(drop=True)
            assert shift.isin([pd.Timedelta(0), pd.Timedelta(minutes=1)]).all()
        expected_cost = actual.quantity.abs() * (2 * inp['fee'] + inp['slippage'] * inp['dataset']['tick_size'] * inp['dataset']['point_value'] * (1 + (actual.exit_reason != 'limit').astype(int)))
        np.testing.assert_allclose(actual.cost, expected_cost, atol=1e-9)
        equity = pd.read_csv(folder / 'equity.csv')
        np.testing.assert_allclose(equity.equity.iloc[-1] - inp['capital'], actual.net_pnl.sum(), atol=1e-7)
        results.append({'variant': model.variant, 'run_id': run['id'], 'matched_trades': len(reference),
                        'final_liquidations': len(actual) - len(ordinary), 'reference_open_at_end': audit['open_trade_at_data_end'],
                        'status': 'PASS', 'net_pnl': float(actual.net_pnl.sum())})
        print(json.dumps(results[-1]), flush=True)
    assert len(results) == 4
    (FOLDER / 'reference-validation.json').write_text(json.dumps({'reference_engine_sha256': checksum(ENGINE),
        'scope': __doc__, 'results': results}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
