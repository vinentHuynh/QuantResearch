"""Bar-close decisions, next-open orders and working brackets with marked equity.

This is a historical OHLC simulator, not a TradingView broker-emulator clone.
Bracket collisions use stop-first within the smallest supplied bar. Slippage
is an explicit cash cost on market/stop fills, not on resting limit exits.
"""
import math
import numpy as np
import pandas as pd


def simulate_events(bars, model, request, execution_bars=None):
    if request.get('delay_bars', 0):
        raise ValueError('Execution delay stress is not supported by event strategies')
    start = pd.Timestamp(request['start'], tz='UTC')
    end = pd.Timestamp(request['end'], tz='UTC') + pd.Timedelta(days=1)
    ready = pd.to_datetime(bars.availability_time, utc=True)
    scored = np.asarray((bars.index >= start) & (ready < end))
    if scored.sum() < 2:
        raise ValueError('Selected interval needs at least two completed bars')
    last_scored = np.flatnonzero(scored)[-1]
    point = request['dataset']['point_value']
    fee = request['fee']
    slip = request['slippage'] * request['dataset']['tick_size'] * point
    balance, held, price, active, bracket, pending = request['capital'], 0, None, None, None, None
    rows, trades, positions = [], [], []
    gross, cost, turnover = 0., 0., 0

    def mark(value):
        nonlocal balance, price, gross
        pnl = held * (value - price) * point if price is not None else 0.
        balance += pnl
        gross += pnl
        if active is not None:
            active['gross_pnl'] += pnl
        price = value

    def fill(target, value, timestamp, reason, limit=False):
        nonlocal held, balance, active, cost, turnover, bracket
        if type(target) is not int or abs(target) > 100:
            raise ValueError('Event targets must be whole contracts between -100 and 100')
        mark(value)
        if held == target:
            return
        charge = abs(target - held) * (fee + (0 if limit else slip))
        old_share = abs(held) / (abs(held) + abs(target)) if held and target else 1 if held else 0
        if active is not None:
            active['cost'] += charge * old_share
            active.update(exit_time=pd.Timestamp(timestamp).isoformat(), exit=value, exit_reason=reason)
            active['net_pnl'] = active['gross_pnl'] - active['cost']
            trades.append(active)
        active = {'entry_time': pd.Timestamp(timestamp).isoformat(), 'entry_bar_close': pd.Timestamp(bar.availability_time).isoformat(), 'entry': value, 'quantity': target,
                  'gross_pnl': 0., 'cost': charge * (1 - old_share)} if target else None
        turnover += abs(target - held)
        cost += charge
        balance -= charge
        held = target
        bracket = None

    def apply(order, value, timestamp):
        nonlocal bracket
        target = order['target']
        levels = order.get('bracket')
        if levels is not None:
            stop, limit = levels
            if not target or not all(math.isfinite(v) for v in levels) or (target > 0 and stop >= limit) or (target < 0 and stop <= limit):
                raise ValueError('Invalid bracket prices')
        fill(target, value, timestamp, order.get('reason', 'signal'))
        bracket = levels if held else None

    for i, (timestamp, bar) in enumerate(bars.iterrows()):
        tradable = bool(scored[i])
        if not tradable:
            if timestamp < start:
                model.on_close(i, bar, {'position': 0, 'equity': request['capital'], 'tradable': False})
            continue
        gross, cost, turnover = 0., 0., 0
        mark(float(bar.open))
        if pending is not None:
            apply(pending, float(bar.open), timestamp)
            pending = None
        intrabar_contracts = held
        if held and bracket:
            if execution_bars is None:
                pieces = bars.iloc[i:i + 1]
            else:
                left = execution_bars.index.searchsorted(timestamp)
                right = execution_bars.index.searchsorted(pd.Timestamp(bar.availability_time))
                pieces = execution_bars.iloc[left:right]
                if pieces.empty:
                    raise ValueError('No execution bars cover a working bracket')
            for event, piece in pieces.iterrows():
                stop, limit = bracket
                opening = float(piece.open)
                stop_gap = opening <= stop if held > 0 else opening >= stop
                limit_gap = opening >= limit if held > 0 else opening <= limit
                stop_hit = float(piece.low) <= stop if held > 0 else float(piece.high) >= stop
                limit_hit = float(piece.high) >= limit if held > 0 else float(piece.low) <= limit
                if stop_gap or limit_gap or stop_hit or limit_hit:
                    is_limit = not stop_gap and (limit_gap or not stop_hit)
                    value = opening if stop_gap or limit_gap else limit if is_limit else stop
                    when = event if stop_gap or limit_gap else min(pd.Timestamp(bar.availability_time), event + pd.Timedelta(minutes=1)) if execution_bars is not None else bar.availability_time
                    fill(0, value, when, 'limit' if is_limit else 'stop', limit=is_limit)
                    break
        mark(float(bar.close))
        decision = model.on_close(i, bar, {'position': held, 'equity': balance, 'tradable': True})
        if decision is not None:
            timing = decision.get('timing', 'close')
            if timing == 'close':
                apply(decision, float(bar.close), bar.availability_time)
            elif timing == 'next-open':
                pending = decision
            else:
                raise ValueError('Event timing must be close or next-open')
        if i == last_scored:
            fill(0, float(bar.close), bar.availability_time, 'end-of-test')
            pending = None
        when = pd.Timestamp(bar.availability_time).isoformat()
        rows.append({'timestamp': when, 'equity': balance, 'gross_pnl': gross, 'cost': cost, 'net_pnl': gross - cost})
        positions.append({'timestamp': when, 'contracts': held, 'intrabar_contracts': intrabar_contracts, 'turnover_contracts': turnover})
    return (pd.DataFrame(rows), pd.DataFrame(trades, columns=['entry_time', 'entry_bar_close', 'exit_time', 'quantity', 'entry', 'exit', 'gross_pnl', 'cost', 'net_pnl', 'exit_reason']), pd.DataFrame(positions))
