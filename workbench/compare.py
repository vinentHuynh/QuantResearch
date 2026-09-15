"""Derived aligned view: carry saved positions; retain original equity bases."""
import json
import sys
from pathlib import Path
import pandas as pd
from .metrics import calculate


def compare(paths):
    inputs = [json.loads(Path(p).read_text()) for p in paths]
    series = [pd.read_csv(Path(p).parent / 'equity.csv') for p in paths]
    for frame in series:
        frame['time'] = pd.to_datetime(frame.timestamp, utc=True)
    start = max(frame.time.iloc[0] for frame in series)
    end = min(frame.time.iloc[-1] for frame in series)
    if start >= end:
        raise ValueError('No shared evaluation interval')
    baseline = series[0].loc[(series[0].time >= start) & (series[0].time <= end), 'time'].reset_index(drop=True)
    rows = []
    for request, frame in zip(inputs, series):
        window = frame.loc[(frame.time >= start) & (frame.time <= end)].copy()
        if not window.time.reset_index(drop=True).equals(baseline):
            raise ValueError('Observation calendars differ. Missing returns cannot be filled for alignment.')
        prior = frame.loc[frame.time < start]
        capital = float(prior.equity.iloc[-1]) if len(prior) else request['capital']
        # Trade counts at cut boundaries cannot be inferred from bar equity alone.
        rows.append({'id': request['id'], 'metrics': calculate(window, capital), 'baseline_equity': capital})
    return {'mode': 'Aligned', 'start': start.isoformat(), 'end': end.isoformat(), 'boundary': 'Carry original simulated positions; rebase each saved equity path to its prior mark. No rerun or return filling; cut-interval trade count unavailable.', 'rows': rows}


if __name__ == '__main__':
    print(json.dumps(compare(sys.argv[1:]), allow_nan=False))
