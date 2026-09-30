"""Completed-bar decisions, next-open/limit entries, and working brackets.

This is an OHLC simulator, not an intrabar order-book replay. A resting entry
needs one tick of penetration; touch-only bars do not establish a fill. On the
entry minute a stop can fill but a target cannot, since its ordering relative
to the entry is unknown. Existing-position bracket collisions remain stop-first.
"""
import math

import numpy as np
import pandas as pd


TRADE_COLUMNS = ['entry_time', 'entry_bar_close', 'exit_time', 'quantity',
                 'entry', 'exit', 'gross_pnl', 'cost', 'net_pnl', 'exit_reason',
                 'signal_id', 'order_id', 'original_stop', 'original_target',
                 'requested_limit', 'point_value', 'fee_per_side',
                 'slippage_ticks', 'contract_label', 'initial_risk_cash',
                 'max_structural_risk_cash', 'nq_contracts', 'mnq_contracts']
SIGNAL_COLUMNS = ['event_time', 'event', 'signal_id', 'order_id', 'target',
                  'requested_limit', 'original_stop', 'original_target',
                  'fill_price', 'new_stop', 'new_target', 'point_value',
                  'fee_per_side', 'slippage_ticks', 'contract_label',
                  'structural_risk_cash', 'max_structural_risk_cash',
                  'nq_contracts', 'mnq_contracts', 'reason']


def simulate_events(bars, model, request, execution_bars=None, *, return_signals=False):
    """Simulate event-v1 orders; opt in to the fourth, audit-ledger result.

    ``timing='limit'`` accepts a flat-position signed ``target``, a tick-aligned
    ``limit_price``, an initial ``bracket`` and optional timezone-aware
    ``expires_at``. It first becomes active at the decision bar's availability
    time. ``timing='cancel'`` with ``order_id`` cancels the one working limit.
    Supplied IDs must be unique; omitted IDs derive from the decision timestamp.
    """
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
    tick = request['dataset']['tick_size']
    fee = request['fee']
    balance, held, price, active, bracket, pending, working = request['capital'], 0, None, None, None, None, None
    rows, trades, positions, signals = [], [], [], []
    used_order_ids = set()
    gross, cost, turnover = 0., 0., 0.
    entry_filled_this_bar = None
    close_fill_notice = None

    def record(event, timestamp, source=None, *, fill_price=None, new_levels=None,
               structural_risk_cash=None, reason=''):
        source = source or {}
        levels = source.get('bracket')
        signals.append({
            'event_time': pd.Timestamp(timestamp).isoformat(), 'event': event,
            'signal_id': source.get('signal_id'), 'order_id': source.get('order_id'),
            'target': source.get('target', source.get('quantity')),
            'requested_limit': source.get('limit_price', source.get('requested_limit')),
            'original_stop': source.get('original_stop', levels[0] if levels else None),
            'original_target': source.get('original_target', levels[1] if levels else None),
            'fill_price': fill_price,
            'new_stop': new_levels[0] if new_levels else None,
            'new_target': new_levels[1] if new_levels else None,
            'point_value': source.get('point_value'),
            'fee_per_side': source.get('fee_per_side', source.get('fee')),
            'slippage_ticks': source.get('slippage_ticks'),
            'contract_label': source.get('contract_label'),
            'structural_risk_cash': source.get('initial_risk_cash', structural_risk_cash),
            'max_structural_risk_cash': source.get('max_structural_risk_cash'),
            'nq_contracts': source.get('nq_contracts'),
            'mnq_contracts': source.get('mnq_contracts'),
            'reason': reason,
        })

    def mark(value):
        nonlocal balance, price, gross
        position_point = active['point_value'] if active is not None else point
        pnl = held * (value - price) * position_point if price is not None else 0.
        balance += pnl
        gross += pnl
        if active is not None:
            active['gross_pnl'] += pnl
        price = value

    def fill(target, value, timestamp, reason, *, limit=False, entry_order=None):
        nonlocal held, balance, active, cost, turnover, bracket, entry_filled_this_bar
        if type(target) is not int or abs(target) > 100:
            raise ValueError('Event targets must be whole contracts between -100 and 100')
        source = entry_order or {}
        current_point = active['point_value'] if active is not None else point
        current_fee = active['fee_per_side'] if active is not None else fee
        current_slip = active['slippage_ticks'] if active is not None else request['slippage']
        new_point = source.get('point_value', current_point)
        new_fee = source.get('fee', current_fee)
        new_slip = source.get('slippage_ticks', current_slip)
        if held and target and (new_point != current_point or new_fee != current_fee or new_slip != current_slip):
            raise ValueError('Cannot change contract economics while a position is held')
        initial_risk_cash = None
        risk_cap = source.get('max_structural_risk_cash')
        if target and not held and source.get('bracket') is not None:
            structural_stop = source['bracket'][0]
            if risk_cap is not None and (
                    (target > 0 and value <= structural_stop) or
                    (target < 0 and value >= structural_stop)):
                record('rejected', timestamp, source, fill_price=value,
                       structural_risk_cash=0., reason='entry-through-structural-stop')
                return False
            initial_risk_cash = abs(value - structural_stop) * abs(target) * new_point
            if risk_cap is not None and initial_risk_cash > risk_cap + 1e-9:
                record('rejected', timestamp, source, fill_price=value,
                       structural_risk_cash=initial_risk_cash,
                       reason='structural-risk-cap')
                return False
        mark(value)
        if held == target:
            return True
        charge_point, charge_fee, charge_slip = (
            (current_point, current_fee, current_slip) if held else (new_point, new_fee, new_slip))
        charge = abs(target - held) * (charge_fee + (0 if limit else charge_slip * tick * charge_point))
        old_share = abs(held) / (abs(held) + abs(target)) if held and target else 1 if held else 0
        if active is not None:
            active['cost'] += charge * old_share
            active.update(exit_time=pd.Timestamp(timestamp).isoformat(), exit=value, exit_reason=reason)
            active['net_pnl'] = active['gross_pnl'] - active['cost']
            trades.append(active)
            record('closed', timestamp, active, fill_price=value, reason=reason)
        if target:
            levels = source.get('bracket')
            active = {
                'entry_time': pd.Timestamp(timestamp).isoformat(),
                'entry_bar_close': pd.Timestamp(bar.availability_time).isoformat(),
                'entry': value, 'quantity': target, 'gross_pnl': 0.,
                'cost': charge * (1 - old_share),
                'signal_id': source.get('signal_id'), 'order_id': source.get('order_id'),
                'original_stop': levels[0] if levels else None,
                'original_target': levels[1] if levels else None,
                'requested_limit': source.get('limit_price'),
                'point_value': new_point, 'fee_per_side': new_fee,
                'slippage_ticks': new_slip,
                'contract_label': source.get('contract_label', active.get('contract_label') if active else request['dataset'].get('symbol')),
                'initial_risk_cash': initial_risk_cash,
                'max_structural_risk_cash': risk_cap,
                'nq_contracts': source.get('nq_contracts'),
                'mnq_contracts': source.get('mnq_contracts'),
            }
            record('filled', timestamp, active, fill_price=value, reason=reason)
            if not held or np.sign(target) != np.sign(held):
                entry_filled_this_bar = {'order_id': active['order_id'],
                                         'signal_id': active['signal_id']}
        else:
            active = None
        turnover += abs(target - held)
        cost += charge
        balance -= charge
        held = target
        bracket = None
        return True

    def validate_levels(target, levels):
        if levels is None:
            return
        if (not target or len(levels) != 2 or
                not all(isinstance(v, (int, float, np.number)) and math.isfinite(v) for v in levels) or
                (target > 0 and levels[0] >= levels[1]) or
                (target < 0 and levels[0] <= levels[1])):
            raise ValueError('Invalid bracket prices')

    def parse_expiry(value, earliest):
        if value is None:
            return None
        expiry = pd.Timestamp(value)
        if expiry.tzinfo is None or expiry < pd.Timestamp(earliest):
            raise ValueError('Order expiry must be timezone-aware and not precede the decision availability')
        return expiry

    def normalize(decision, i, available, timing):
        if not isinstance(decision, dict):
            raise ValueError('Event decision must be a mapping')
        target = decision['target']
        if type(target) is not int or abs(target) > 100:
            raise ValueError('Event targets must be whole contracts between -100 and 100')
        levels = decision.get('bracket')
        validate_levels(target, levels)
        automatic = f'event:{pd.Timestamp(available).isoformat()}'
        order_id = decision.get('order_id', automatic)
        signal_id = decision.get('signal_id', order_id)
        if not all(isinstance(value, str) and 0 < len(value) <= 160 and '\n' not in value
                   for value in (order_id, signal_id)):
            raise ValueError('Signal and order IDs must be nonempty strings of at most 160 characters')
        refers_to_active = (active is not None and order_id == active['order_id'] and
                            timing != 'limit' and target in (0, held))
        if order_id in used_order_ids and not refers_to_active:
            raise ValueError(f'Duplicate event order ID: {order_id}')
        if not refers_to_active:
            used_order_ids.add(order_id)
        order = {**decision, 'target': target, 'bracket': levels, 'order_id': order_id,
                 'signal_id': signal_id, 'timing': timing,
                 'expires_at': parse_expiry(decision.get('expires_at'), available)}
        for field in ('point_value', 'fee', 'slippage_ticks'):
            if field in decision:
                value = decision[field]
                if (not isinstance(value, (int, float, np.number)) or not math.isfinite(value) or
                        (field == 'point_value' and value <= 0) or (field != 'point_value' and value < 0)):
                    raise ValueError(f'Invalid per-order {field}')
                order[field] = float(value)
        if 'contract_label' in decision and (not isinstance(decision['contract_label'], str) or
                                             not 0 < len(decision['contract_label']) <= 32):
            raise ValueError('Invalid per-order contract label')
        if 'nq_contracts' in decision or 'mnq_contracts' in decision:
            nq_contracts = decision.get('nq_contracts', 0)
            mnq_contracts = decision.get('mnq_contracts', 0)
            if (type(nq_contracts) is not int or nq_contracts < 0 or
                    type(mnq_contracts) is not int or mnq_contracts < 0 or
                    not target or 10 * nq_contracts + mnq_contracts != abs(target)):
                raise ValueError('NQ/MNQ mix must be nonnegative whole contracts and equal the micro-equivalent target')
            order['nq_contracts'] = nq_contracts
            order['mnq_contracts'] = mnq_contracts
        order.setdefault('point_value', active['point_value'] if active else point)
        order.setdefault('fee', active['fee_per_side'] if active else fee)
        order.setdefault('slippage_ticks', active['slippage_ticks'] if active else request['slippage'])
        order.setdefault('contract_label', active['contract_label'] if active else request['dataset'].get('symbol'))
        if 'max_structural_risk_cash' in decision:
            risk_cap = decision['max_structural_risk_cash']
            if (not isinstance(risk_cap, (int, float, np.number)) or not math.isfinite(risk_cap) or
                    risk_cap <= 0 or not target or not levels):
                raise ValueError('Structural risk cap requires a positive cash amount and an entry bracket')
            order['max_structural_risk_cash'] = float(risk_cap)
        if timing == 'limit':
            value = decision.get('limit_price')
            if (not isinstance(value, (int, float, np.number)) or not math.isfinite(value) or
                    not math.isclose(value / tick, round(value / tick), rel_tol=0., abs_tol=1e-7)):
                raise ValueError('Limit entry price must be finite and tick-aligned')
            if not target or not levels or (target > 0 and not levels[0] < value < levels[1]) or (
                    target < 0 and not levels[1] < value < levels[0]):
                raise ValueError('Limit entry needs a flat-position target and a structural bracket around its price')
            order['limit_price'] = float(value)
            order['active_after'] = pd.Timestamp(available)
        return order

    def apply(order, value, timestamp):
        nonlocal bracket
        target, levels = order['target'], order.get('bracket')
        same_position = held == target and held != 0
        fill(target, value, timestamp, order.get('reason', 'signal'), entry_order=order)
        if same_position and levels is not None:
            record('bracket_updated', timestamp, active, new_levels=levels,
                   reason=order.get('reason', 'signal'))
        bracket = levels if held else None

    def pieces_for(timestamp, bar, i):
        if execution_bars is None:
            return bars.iloc[i:i + 1]
        left = execution_bars.index.searchsorted(timestamp)
        right = execution_bars.index.searchsorted(pd.Timestamp(bar.availability_time))
        pieces = execution_bars.iloc[left:right]
        if pieces.empty:
            raise ValueError('No execution bars cover a working order or bracket')
        return pieces

    def bracket_hit(event, piece, bar, *, entry_minute=False):
        """Return whether a bracket closed; entry-minute target is unknowable."""
        if not held or not bracket:
            return False
        stop, limit_price = bracket
        opening = float(piece.open)
        stop_gap = opening <= stop if held > 0 else opening >= stop
        limit_gap = opening >= limit_price if held > 0 else opening <= limit_price
        stop_hit = float(piece.low) <= stop if held > 0 else float(piece.high) >= stop
        limit_hit = float(piece.high) >= limit_price if held > 0 else float(piece.low) <= limit_price
        if entry_minute:
            if not (stop_gap or stop_hit):
                return False
            is_limit = False
        elif stop_gap or limit_gap or stop_hit or limit_hit:
            is_limit = not stop_gap and (limit_gap or not stop_hit)
        else:
            return False
        value = opening if stop_gap or (limit_gap and not entry_minute) else (
            limit_price if is_limit else stop)
        when = event if stop_gap or (limit_gap and not entry_minute) else (
            min(pd.Timestamp(bar.availability_time), event + pd.Timedelta(minutes=1))
            if execution_bars is not None else bar.availability_time)
        fill(0, value, when, 'limit' if is_limit else 'stop', limit=is_limit)
        return True

    for i, (timestamp, bar) in enumerate(bars.iterrows()):
        tradable = bool(scored[i])
        if not tradable:
            if timestamp < start:
                model.on_close(i, bar, {'position': 0, 'equity': request['capital'],
                                        'tradable': False, 'entry_filled_this_bar': None})
            continue
        gross, cost, turnover = 0., 0., 0
        entry_filled_this_bar, close_fill_notice = close_fill_notice, None
        mark(float(bar.open))
        if pending is not None:
            expiry = pending.get('expires_at')
            if expiry is None or timestamp <= expiry:
                apply(pending, float(bar.open), timestamp)
            else:
                print('Expired next-open order before ' + timestamp.isoformat() + ': ' + pending.get('reason', 'signal'), flush=True)
                record('expired', timestamp, pending, reason='next-open expiry')
            pending = None
        position_at_open = held
        intrabar_contracts = held
        if working is not None and working.get('expires_at') is not None and timestamp > working['expires_at']:
            record('expired', working['expires_at'], working, reason='limit expiry')
            working = None
        if (held and bracket) or working is not None:
            pieces = pieces_for(timestamp, bar, i)
            for event, piece in pieces.iterrows():
                event = pd.Timestamp(event)
                if held and bracket:
                    if bracket_hit(event, piece, bar):
                        break
                    continue
                if working is None:
                    break
                expiry = working.get('expires_at')
                if expiry is not None and event > expiry:
                    record('expired', expiry, working, reason='limit expiry')
                    working = None
                    break
                if event < working['active_after']:
                    continue
                level, target = working['limit_price'], working['target']
                penetrated = (float(piece.low) <= level - tick + 1e-9 if target > 0 else
                              float(piece.high) >= level + tick - 1e-9)
                if not penetrated:
                    continue
                opening = float(piece.open)
                at_open = opening <= level - tick + 1e-9 if target > 0 else opening >= level + tick - 1e-9
                when = event if at_open else min(pd.Timestamp(bar.availability_time), event + pd.Timedelta(minutes=1))
                order = working
                working = None
                # Price improvement at an opening gap is omitted conservatively.
                accepted = fill(target, level, when, 'limit-entry', limit=True, entry_order=order)
                bracket = order['bracket'] if accepted else None
                intrabar_contracts = held
                if accepted and bracket_hit(event, piece, bar, entry_minute=True):
                    break
            if working is not None and working.get('expires_at') is not None and pd.Timestamp(bar.availability_time) > working['expires_at']:
                record('expired', working['expires_at'], working, reason='limit expiry')
                working = None
        mark(float(bar.close))
        decision = model.on_close(i, bar, {'position': held, 'position_at_open': position_at_open,
                                         'equity': balance, 'tradable': True,
                                         'entry_price': active['entry'] if active else None,
                                         'signal_id': active['signal_id'] if active else None,
                                         'order_id': active['order_id'] if active else None,
                                         'original_stop': active['original_stop'] if active else None,
                                         'original_target': active['original_target'] if active else None,
                                         'working_order_id': working['order_id'] if working else None,
                                         'entry_filled_this_bar': entry_filled_this_bar})
        notice_seen_by_model = entry_filled_this_bar
        if decision is not None:
            if not isinstance(decision, dict):
                raise ValueError('Event decision must be a mapping')
            timing = decision.get('timing', 'close')
            if timing == 'cancel':
                order_id = decision.get('order_id')
                if working is None or order_id != working['order_id']:
                    raise ValueError('Cancel must name the current working limit order')
                record('cancelled', bar.availability_time, working,
                       reason=decision.get('reason', 'cancel'))
                working = None
            elif timing in ('close', 'next-open', 'limit'):
                order = normalize(decision, i, bar.availability_time, timing)
                if timing == 'limit':
                    if held or pending is not None or working is not None:
                        raise ValueError('Limit entry requires flat position and no other working order')
                    working = order
                elif working is not None:
                    if order['target'] != 0:
                        raise ValueError('Market order conflicts with a working limit entry')
                    record('cancelled', bar.availability_time, working, reason='flat order')
                    working = None
                record('submitted', bar.availability_time, order, reason=order.get('reason', 'signal'))
                if timing == 'close':
                    apply(order, float(bar.close), bar.availability_time)
                    if entry_filled_this_bar is not notice_seen_by_model:
                        close_fill_notice = entry_filled_this_bar
                elif timing == 'next-open':
                    pending = order
            else:
                raise ValueError('Event timing must be close, next-open, limit, or cancel')
        if i == last_scored:
            fill(0, float(bar.close), bar.availability_time, 'end-of-test')
            if pending is not None:
                record('cancelled', bar.availability_time, pending, reason='end-of-test')
            if working is not None:
                record('cancelled', bar.availability_time, working, reason='end-of-test')
            pending = working = None
        when = pd.Timestamp(bar.availability_time).isoformat()
        rows.append({'timestamp': when, 'equity': balance, 'gross_pnl': gross, 'cost': cost, 'net_pnl': gross - cost})
        positions.append({'timestamp': when, 'contracts': held, 'intrabar_contracts': intrabar_contracts,
                          'turnover_contracts': turnover})
    result = (pd.DataFrame(rows), pd.DataFrame(trades, columns=TRADE_COLUMNS), pd.DataFrame(positions))
    if return_signals:
        return (*result, pd.DataFrame(signals, columns=SIGNAL_COLUMNS))
    return result
