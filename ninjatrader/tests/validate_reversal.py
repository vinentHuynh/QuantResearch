"""Compare the compiled C# streaming core with original Python schedule.

Uses the preserved local MNQ data and synthetic edge cases, with temp fixtures.
This verifies decisions, not NinjaTrader fills, broker behavior, or profitability.
Run: .venv/Scripts/python.exe ninjatrader/tests/validate_reversal.py
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.short_term_reversal_minute import STRATEGY, schedule
from strategy_engine.data import session_bars
from strategy_engine.sessions import get_session
from workbench.contract import resolve_parameters


def synthetic():
    parts = []
    # Mar08=>Mar11 crosses the US spring DST/weekend boundary. Two successive
    # selloffs above SMA exercise expiry winning over a repeated entry signal.
    for date, price in [('2024-03-06', 80.), ('2024-03-07', 100.),
                        ('2024-03-08', 98.), ('2024-03-11', 96.5),
                        ('2024-03-12', 95.), ('2024-03-13', 100.),
                        ('2024-03-14', 98.75), ('2024-03-15', 100.)]:
        index = pd.date_range(date + ' 09:25', date + ' 16:00', freq='min', tz='America/New_York')
        parts.append(pd.DataFrame(dict(open=price, high=price + .1, low=price - .1,
                                       close=price, availability_time=index + pd.Timedelta(minutes=1)), index=index))
    return pd.concat(parts)


def check(exe, folder, label, bars, lookback):
    parameters = resolve_parameters(STRATEGY, dict(trend_lookback=lookback, open_delay_minutes=5))
    expected = schedule(bars, parameters)[['decision_index', 'target']].astype(int).to_numpy()
    record = np.empty(len(bars), dtype=[('open', '<i8'), ('close', '<i8'), ('price', '<f8')])
    origin = 621355968000000000
    record['open'] = bars.index.tz_convert('America/New_York').tz_localize(None).asi8 // 100 + origin
    ready = pd.DatetimeIndex(bars.availability_time).tz_convert('America/New_York').tz_localize(None)
    record['close'] = ready.asi8 // 100 + origin
    record['price'] = bars.close.to_numpy()
    fixture, result = folder / 'input.bin', folder / 'actual.csv'
    record.tofile(fixture)
    subprocess.run([str(exe), str(fixture), str(result), str(lookback)], check=True)
    actual = pd.read_csv(result, header=None, names=['index', 'target', 'days'])
    np.testing.assert_array_equal(actual[['index', 'target']].to_numpy(), expected, err_msg=label)
    return dict(case=label, bars=len(bars), scheduled_decisions=len(expected),
                long_targets=int((expected[:, 1] == 1).sum()), result='PASS')


def main():
    core = ROOT / 'ninjatrader/WorkbenchMnqReversalCore.cs'
    harness = ROOT / 'ninjatrader/tests/ReversalReplay.cs'
    compiler = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    results = []
    with tempfile.TemporaryDirectory(prefix='mnq-reversal-check-') as temporary:
        folder = Path(temporary)
        exe = folder / 'replay.exe'
        subprocess.run([str(compiler), '/nologo', '/warnaserror+', '/langversion:5',
                        '/out:' + str(exe), str(core), str(harness)], check=True)
        bars = synthetic()
        cases = {
            'DST-weekend-expiry-strict-threshold': bars,
            'incomplete-future-day': bars.loc[:'2024-03-08 12:00'],
            'partial-left-day': bars.loc['2024-03-06 12:00':],
            'late-missing-entry': bars.drop(bars.loc['2024-03-11 09:34':'2024-03-11 09:42'].index),
            'sparse-early-close': bars.drop(bars.loc['2024-03-08 13:00':'2024-03-08 16:00'].index),
        }
        for label, frame in cases.items():
            results.append(check(exe, folder, label, frame, 3))
        data = next((ROOT / 'data/workbench/datasets').glob('*mnq-cache-v1/bars.parquet'))
        frame = pd.read_parquet(data, columns=['open', 'high', 'low', 'close', 'volume'])
        bars = session_bars(frame, get_session('full-trading-day'), '1m')
        results.append(check(exe, folder, 'all-preserved-MNQ-minute-data-SMA200', bars, 200))
    report = dict(scope='Compiled C# decision parity only; no NinjaTrader fill/performance claim',
                  core_sha256=hashlib.sha256(core.read_bytes()).hexdigest(),
                  python_sources={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in [ROOT / 'strategies/short_term_reversal.py', ROOT / 'strategies/short_term_reversal_minute.py']},
                  results=results)
    output = ROOT / 'ninjatrader/working_nq_to_mnq/reversal-validation.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
