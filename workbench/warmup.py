"""Declared indicator history coverage, measured on completed session bars."""
import json
import sys

import pandas as pd


def required_bars(spec, parameters):
    rule = spec.get('warmup_bars')
    if rule is None:
        return None
    return parameters[rule['parameter']] * rule.get('multiplier', 1) + rule.get('offset', 0)


def coverage(bars, request, spec, parameters):
    required = required_bars(spec, parameters)
    if required is None:
        return {'status': 'undeclared', 'required_bars': None, 'available_bars': None}
    start = pd.Timestamp(request['start'], tz='UTC')
    loaded_from = start - pd.Timedelta(days=request['warmup_days'])
    # Exclude unfinished bars and a partially loaded bar at the left boundary.
    ready = pd.to_datetime(bars.availability_time, utc=True)
    count = int(((bars.index >= loaded_from) & (bars.index < start) & (ready <= start)).sum())
    return {'status': 'sufficient' if count >= required else 'insufficient',
            'required_bars': required, 'available_bars': count}


def warning(result):
    if result['status'] != 'insufficient':
        return None
    return (f"Insufficient warmup: {result['available_bars']} completed bars available before scoring; "
            f"{result['required_bars']} required by the declared indicator history. "
            "Increase warmup days or move the scored start later. Early signals may be uninitialized; "
            "this run must not be treated as fully initialized evidence.")


def preview(inputs):
    from strategy_engine.data import session_bars
    from strategy_engine.sessions import get_session
    cache, results = {}, []
    for request in inputs:
        spec, parameters = request['strategy'], request['parameters']
        if required_bars(spec, parameters) is None:
            continue
        dataset = request['dataset']
        key = (dataset['checksum'], request['start'], request['warmup_days'], request['session'], request['timeframe'])
        if key not in cache:
            end = pd.Timestamp(request['start'], tz='UTC')
            start = end - pd.Timedelta(days=request['warmup_days'])
            frame = pd.read_parquet(dataset['path'], columns=['open', 'high', 'low', 'close'],
                                    filters=[('ts_event', '>=', start), ('ts_event', '<', end)])
            cache[key] = session_bars(frame, get_session(request['session']), request['timeframe'])
        result = coverage(cache[key], request, spec, parameters)
        results.append({'dataset_id': dataset['id'], 'symbol': dataset['symbol'],
                        'timeframe': request['timeframe'], 'parameters': parameters,
                        **result, 'warning': warning(result)})
    return results


if __name__ == '__main__':
    print(json.dumps(preview(json.load(sys.stdin)), allow_nan=False))
