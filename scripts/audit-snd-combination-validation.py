"""Independent selected-fold implementation audit; imports no strategy engine.

All saved sizing decisions and all trades receive arithmetic and chronology
checks. Every decision's formation and signal are reconstructed from raw bars.
Trade entry/exit formation checks use first/middle/last ordinal samples. Full
five-minute equity is reconstructed from source closes and observed fill times.
This cannot prove that a simulator omitted no otherwise eligible signal.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SPEC = importlib.util.spec_from_file_location('combination_independent_audit', Path(__file__).with_name('audit-snd-combinations.py'))
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)
MINUTE, FIVE = base.MINUTE, base.FIVE


def identity(case):
    return '/'.join(str(case[k]) for k in ('symbol', 'fold_id', 'role', 'scenario'))


def declared_cases(selection, protocol, configs):
    """Rebuild case identities independently of the validation runner."""
    folds = {f['id']: f for f in protocol['folds']}
    choices = {(s['symbol'], s['fold_id']): s for s in selection['selections']}
    expected = {(d['symbol'], f) for d in protocol['datasets'] for f in folds}
    if len(choices) != len(selection['selections']) or set(choices) != expected:
        raise ValueError('Selections must cover each unique market/fold')
    rows = []
    for symbol, fold_id in sorted(expected):
        selected, fold = choices[symbol, fold_id], folds[fold_id]
        if selected['cutoff'] != fold['cutoff'] or selected['test_end'] != fold['test_end']:
            raise ValueError('Selection changed its declared fold boundaries')
        cid = selected['selected_id']
        chosen = configs[cid]['parameters'] if cid is not None else None
        roles = [('reference', 'c00000', configs['c00000']['parameters']), ('selected', cid, chosen)]
        for i, delta in enumerate(protocol['validation_neighbors']):
            roles.append((f'neighbor-{i}', cid, None if chosen is None else dict(chosen, **delta)))
        for budget in (50, 100, 200):
            roles.append((f'risk-{budget}', cid, None if chosen is None else dict(chosen,
                sizing_mode='fixed_risk', risk_budget=float(budget), max_contracts=10)))
        for role, config_id, p in roles:
            scenarios = protocol['validation_scenarios'][:1] if role.startswith('neighbor-') else protocol['validation_scenarios']
            for scenario in scenarios:
                rows.append(dict(symbol=symbol, fold_id=fold_id, start=fold['cutoff'], end=fold['test_end'],
                    role=role, config_id=config_id, decision='cash' if p is None else 'selected',
                    scenario=scenario['id'], parameters=None if p is None else dict(p, slippage_model=scenario['slippage_model']),
                    fee_multiple=scenario['fee_multiple'], slippage_ticks=scenario['slippage_ticks']))
    return rows


def normalize_one_contract(trades):
    """Normalize only for price/geometry checks; actual quantities are audited separately."""
    t = trades.copy()
    if len(t):
        size = np.abs(t.quantity.to_numpy(float))
        if not (np.isfinite(size) & (size >= 1) & (size == np.rint(size))).all():
            raise ValueError('Cannot normalize nonpositive or fractional quantities')
        for name in ('risk_cash', 'initial_risk_cash', 'gross_pnl', 'cost', 'net_pnl'):
            t[name] = t[name] / size
        t['quantity'] = t.side
    return t


def observed_exits(trades, raw):
    """Roll liquidation is learned on the next contract bar, not at its stale close."""
    exits = base.ns(trades.exit_time).copy()
    source_times = base.ns(raw['source'].index)
    reasons = trades.exit_reason.to_numpy()
    ordinary = np.isin(reasons, ('target', 'stop'))
    exits[ordinary] += MINUTE
    for i in np.flatnonzero(reasons == 'contract-roll'):
        before = int(np.searchsorted(source_times, exits[i] - MINUTE))
        if before + 1 >= len(source_times) or source_times[before] != exits[i] - MINUTE:
            raise ValueError('Roll close has no following raw contract bar')
        segments = raw['source']['_segment'].to_numpy()
        if segments[before] == segments[before + 1]:
            raise ValueError('Recorded roll is not an observed contract transition')
        exits[i] = source_times[before + 1] + MINUTE
    return exits


def audit_accounting(trades, equity, p, dataset, raw, summary, fee, slippage_ticks):
    """Independent dollar arithmetic and every five-minute mark, including drawdown."""
    check = base.Checks('full validation accounting and raw marked equity')
    capital, point, tick = float(p.get('capital', 100000)), dataset['point_value'], dataset['tick_size']
    n = len(trades)
    check.result.update(trades=n, equity_rows=len(equity))
    times = base.ns(equity.timestamp)
    chart, source = raw['chart'], raw['source']
    source_times = base.ns(source.index)
    starts, ends = pd.Timestamp(dataset['start'], tz='UTC').value, pd.Timestamp(dataset['end'], tz='UTC').value
    raw_marks = source_times[chart.final.to_numpy(int)] + MINUTE
    keep = (raw_marks > starts) & (raw_marks <= ends)
    expected_times = raw_marks[keep]
    check.require('every observed scored five-minute mark retained', np.array_equal(times, expected_times))
    check.require('nonempty ordered equity', len(times) > 0 and (np.diff(times) > 0).all())
    rows = np.searchsorted(source_times, times - MINUTE)
    valid = (rows < len(source_times))
    check.require('marks map to raw source closes', valid.all() and np.array_equal(source_times[rows[valid]], (times - MINUTE)[valid]))
    if not valid.all():
        return check.finish()
    balance = np.full(len(times), capital)
    unrealized = np.zeros(len(times))
    contracts = np.zeros(len(times))
    net = costs = gross_total = 0.
    if n:
        size, side = np.abs(trades.quantity.to_numpy(float)), trades.side.to_numpy(float)
        check.require('signed whole positive quantities', (np.isin(side, [-1, 1]) & (size >= 1) &
                      (size == np.rint(size)) & (trades.quantity.to_numpy(float) == side * size)).all())
        risk = side * (trades.entry - trades.stop).to_numpy(float)
        gross = side * size * (trades.exit - trades.entry).to_numpy(float) * point
        slip = slippage_ticks * tick * point if p['slippage_model'] == 'cash' else 0.
        entry_cost = size * (fee + slip)
        exit_cost = size * (fee + slip * trades.exit_reason.ne('target').to_numpy(int))
        check.close('actual gross dollars', trades.gross_pnl, gross)
        check.close('actual all-in costs', trades.cost, entry_cost + exit_cost)
        check.close('actual net dollars', trades.net_pnl, gross - entry_cost - exit_cost)
        check.close('actual immutable cash risk', trades.risk_cash, risk * point * size)
        check.close('actual initial cash risk', trades.initial_risk_cash, risk * point * size)
        check.close('actual net R', trades.net_r, (gross - entry_cost - exit_cost) / (risk * point * size))
        entered, exited = base.ns(trades.entry_time) + MINUTE, observed_exits(trades, raw)
        check.require('observed exits follow entries', (exited >= entered).all())
        check.require('observed exits ordered', (np.diff(exited) >= 0).all())
        known_entries = np.searchsorted(entered, times, side='right')
        known_exits = np.searchsorted(exited, times, side='right')
        check.require('observed single position lifecycle', np.isin(known_entries - known_exits, (0, 1)).all())
        balance -= np.r_[0., np.cumsum(entry_cost)][known_entries]
        balance += np.r_[0., np.cumsum(gross - exit_cost)][known_exits]
        active = known_entries > known_exits
        selected = known_entries[active] - 1
        contracts[active] = trades.quantity.to_numpy(float)[selected]
        unrealized[active] = contracts[active] * (source.close.to_numpy(float)[rows[active]] - trades.entry.to_numpy(float)[selected]) * point
        net, costs, gross_total = float(trades.net_pnl.sum()), float(trades.cost.sum()), float(trades.gross_pnl.sum())
    marked = balance + unrealized
    for name, expected in [('balance', balance), ('unrealized_pnl', unrealized), ('equity', marked),
                            ('contracts', contracts), ('net_pnl', np.diff(np.r_[capital, marked]))]:
        check.close('independent full-resolution ' + name, equity[name], expected, atol=1e-5)
    check.close('terminal realized cash', marked[-1], capital + net, atol=1e-5)
    check.close('terminal flat position', contracts[-1], 0)
    path = np.r_[capital, marked]
    expected = dict(trades=n, net_pnl=net, closed_net=net, gross_pnl=gross_total, cost=costs,
        double_cost_closed_net=net - costs, net_r_sum=float(trades.net_r.sum()),
        max_drawdown=float(np.max(np.maximum.accumulate(path) - path)), min_equity=float(path.min()),
        max_trade_loss=max(0., -float(trades.net_pnl.min())) if n else 0.)
    if n:
        expected.update(mean_net_r=float(trades.net_r.mean()))
    for name, value in expected.items():
        check.require('saved summary field ' + name, name in summary)
        if name in summary:
            check.close('independent summary ' + name, summary[name], value, atol=1e-5)
    return check.finish()


def decision_facts(raw, p, decision, tick):
    """Direct formation, touch, stop and opposing-room facts for one saved signal."""
    key = (p['require_fvg'], p.get('zone_boundary', 'wick'))
    if key not in raw.setdefault('formation_cache', {}):
        raw['formation_cache'][key] = base.formations(raw['chart'], *key)
    cache_key = (key, p['pivot_len'], p['stop_model'], p['max_age'], decision.zone_id, pd.Timestamp(decision.observed_time).value)
    cache = raw.setdefault('decision_facts_cache', {})
    if cache_key in cache:
        return cache[cache_key]
    segment, side, born = (int(v) for v in decision.zone_id.split(':'))
    signal = pd.Timestamp(decision.observed_time).value
    chart = raw['chart']
    ts = base.ns(chart.index)
    z, s = int(np.searchsorted(ts, born - FIVE)), int(np.searchsorted(ts, signal - FIVE))
    if not 2 <= z < s < len(chart) or ts[z] != born - FIVE or ts[s] != signal - FIVE:
        raise ValueError('Decision zone/signal does not identify observed chart candles')
    sides, tops, bottoms = raw['formation_cache'][key]
    highs, lows, segments = chart.high.to_numpy(float), chart.low.to_numpy(float), chart.segment.to_numpy()
    top, bottom, epsilon = tops[z], bottoms[z], tick * 1e-7
    hits = np.flatnonzero((lows[z + 1:s + 1] <= top + epsilon) & (highs[z + 1:s + 1] >= bottom - epsilon))
    first = z + 1 + int(hits[0]) if len(hits) else -1
    touch = lows[s] <= top + epsilon and highs[s] >= bottom - epsilon
    valid = (lows[z + 1:s + 1] >= bottom - epsilon).all() if side == 1 else (highs[z + 1:s + 1] <= top + epsilon).all()
    bias, hourly = base.structures(raw, int(p['pivot_len']))
    trigger = highs[s] + tick if side == 1 else lows[s] - tick
    anchor = (bottom if side == 1 else top) if p['stop_model'] == 'zone' else (lows[s] if side == 1 else highs[s])
    stop = anchor - side * tick
    boundaries = []
    begin = max(0, s - int(p['max_age']))
    for k in np.flatnonzero(sides[begin:s + 1] == -side) + begin:
        if segments[k] != segment:
            continue
        alive = ((lows[k + 1:s + 1] >= bottoms[k] - epsilon).all() if sides[k] == 1 else
                 (highs[k + 1:s + 1] <= tops[k] + epsilon).all())
        ahead = tops[k] >= trigger - epsilon if side == 1 else bottoms[k] <= trigger + epsilon
        if alive and ahead:
            boundaries.append(bottoms[k] if side == 1 else tops[k])
    boundary = (min(boundaries) if side == 1 else max(boundaries)) if boundaries else np.nan
    risk = side * (trigger - stop)
    facts = dict(side=side, trigger=trigger, stop=stop,
        formation=bool(sides[z] == side and segments[z] == segment == segments[s]),
        valid=bool(valid and s - z <= p['max_age']), signal_complete=bool(chart.complete.iloc[s]),
        overlap=bool(touch), first=first, signal_index=s, first_bucket=ts[first] if first >= 0 else -1,
        structure=bool(bias[z] == side and bias[s] == side), hourly=bool(hourly[z] == side and hourly[s] == side),
        room=np.inf if not boundaries else max(0., side * (boundary - trigger)) / risk,
        signal_age_hours=(signal - born) / (60 * MINUTE), **base.raw_quality(raw, z, top, bottom))
    cache[cache_key] = facts
    return facts


def audit_sizing(trades, decisions, p, dataset, raw, diagnostics, fee, slippage_ticks):
    check = base.Checks('all quantity decisions, raw signals and frozen fills')
    check.result.update(decisions=len(decisions), zero_quantity_decisions=0)
    tick, point = dataset['tick_size'], dataset['point_value']
    budget, cap = float(p['risk_budget']), int(p['max_contracts'])
    check.require('fixed risk policy', p['sizing_mode'] == 'fixed_risk' and budget > 0 and cap >= 1)
    check.require('zero context capacity discards', diagnostics.get('context_zones_discarded_capacity') == 0)
    check.require('sizing decision count diagnostic', diagnostics.get('sizing_decisions') == len(decisions))
    if decisions.empty:
        check.require('no trades without decisions', trades.empty)
        for name in ('sizing_rejections', 'entry_orders_armed', 'quantity_capped_orders', 'contracts_entered'):
            check.require('empty decision diagnostic ' + name, diagnostics.get(name) == 0)
        return check.finish()
    planned = abs(decisions.trigger - decisions.stop).to_numpy(float) * point + 2 * fee + 2 * slippage_ticks * tick * point
    uncapped = np.floor(budget / planned)
    quantity = np.minimum(uncapped, cap)
    zeros, accepted = quantity == 0, quantity > 0
    check.result['zero_quantity_decisions'] = int(zeros.sum())
    check.require('finite positive planned loss', (np.isfinite(planned) & (planned > 0)).all())
    check.close('decision all-in planned loss', decisions.planned_stop_risk_per_contract, planned)
    check.close('decision uncapped whole quantity', decisions.quantity_uncapped, uncapped)
    check.close('decision capped whole quantity', decisions.quantity_selected, quantity)
    check.require('decision cap flags', np.array_equal(decisions.quantity_capped.to_numpy(bool), uncapped > cap))
    check.close('decision fixed budget', decisions.risk_budget, budget)
    check.require('decision sizing mode', decisions.sizing_mode.eq('fixed_risk').all())
    check.require('zero quantity rejection reason', decisions.loc[zeros, 'rejection_reason'].eq('risk-budget-below-one-contract').all())
    check.require('zero quantities never arm', decisions.loc[zeros, 'order_id'].isna().all())
    check.require('accepted quantities have no rejection', decisions.loc[accepted, 'rejection_reason'].isna().all())
    check.require('accepted order IDs unique and present', decisions.loc[accepted, 'order_id'].notna().all() and decisions.loc[accepted, 'order_id'].is_unique)
    check.require('one recorded decision per zone/signal', not decisions.duplicated(['zone_id', 'observed_time']).any())
    observed = base.ns(decisions.observed_time)
    check.require('ordered decisions', (np.diff(observed) >= 0).all())
    start, end = pd.Timestamp(dataset['start'], tz='UTC').value, pd.Timestamp(dataset['end'], tz='UTC').value
    check.require('decisions inside scored bars', ((observed - FIVE >= start) & (observed <= end)).all())
    for name, expected in [('sizing_rejections', int(zeros.sum())), ('entry_orders_armed', int(accepted.sum())),
                           ('quantity_capped_orders', int((uncapped > cap).sum()))]:
        check.require('diagnostic ' + name, diagnostics.get(name) == expected)
    raw_conditions, triggers, stops, sides = [], [], [], []
    for row in decisions.itertuples(index=False):
        facts = decision_facts(raw, p, row, tick)
        valid = facts['formation'] and facts['valid'] and facts['signal_complete'] and facts['overlap'] and facts['structure']
        valid &= not p['use_htf'] or facts['hourly']
        valid &= facts['room'] + 1e-9 >= p['min_opposing_room_r']
        if p['entry_eligibility'] == 'first_touch':
            valid &= facts['first'] == facts['signal_index'] and facts['first_bucket'] >= start
        for parameter, feature, maximum in [('max_zone_width_atr', 'zone_width_atr', True),
                ('min_departure_atr', 'departure_atr', False), ('min_departure_rvol', 'departure_rvol', False),
                ('max_touch_age_hours', 'signal_age_hours', True)]:
            if p.get(parameter) is not None:
                value = facts[feature]
                valid &= np.isfinite(value) and (value <= p[parameter] if maximum else value >= p[parameter])
        raw_conditions.append(valid)
        triggers.append(facts['trigger']); stops.append(facts['stop']); sides.append(facts['side'])
    check.require('every sizing decision has valid raw formation touch structure quality and room', all(raw_conditions))
    check.close('raw decision side', decisions.side, sides)
    check.close('raw decision trigger', decisions.trigger, triggers)
    check.close('raw decision selected stop', decisions.stop, stops)
    positive = decisions.loc[accepted].set_index('order_id', drop=False)
    if len(trades):
        check.require('one fill per frozen order', trades.order_id.is_unique)
        check.require('every fill was accepted', trades.order_id.isin(positive.index).all())
        if not trades.order_id.isin(positive.index).all():
            return check.finish()
        frozen = positive.loc[trades.order_id].reset_index(drop=True)
        for saved, declared in [('contracts_abs', 'quantity_selected'), ('side', 'side'),
                ('entry_reference', 'trigger'), ('stop', 'stop'), ('planned_stop_risk_per_contract', 'planned_stop_risk_per_contract')]:
            check.close('fill preserves armed ' + saved, trades[saved], frozen[declared])
        check.require('fill preserves zone identity', trades.zone_id.to_list() == frozen.zone_id.to_list())
        check.require('fill preserves signal time', np.array_equal(base.ns(trades.signal_time), base.ns(frozen.observed_time)))
        size = trades.contracts_abs.to_numpy(float)
        check.close('fill signed quantity', trades.quantity, trades.side.to_numpy(float) * size)
        check.close('fill planned total risk', trades.planned_stop_risk_cash, frozen.planned_stop_risk_per_contract.to_numpy(float) * size)
        actual = abs(trades.entry - trades.stop).to_numpy(float) * point + 2 * fee + slippage_ticks * tick * point * (2 if p['slippage_model'] == 'cash' else 1)
        check.close('actual stop loss per contract', trades.actual_stop_risk_per_contract, actual)
        check.close('actual stop loss total', trades.actual_stop_risk_cash, actual * size)
        check.close('actual budget overshoot', trades.risk_budget_overshoot_cash, np.maximum(0, actual * size - budget))
        check.close('filled budget declaration', trades.risk_budget, budget)
        check.require('filled sizing declaration', trades.sizing_mode.eq('fixed_risk').all())
        check.require('fill cap declaration', np.array_equal(trades.quantity_capped.to_numpy(bool), frozen.quantity_capped.to_numpy(bool)))
        # A recorded signal cannot arm while a known position occupies any part
        # of its overlap bucket, including a same-bucket close.
        entered, exited = base.ns(trades.entry_time), observed_exits(trades, raw)
        busy = [bool(((entered < t) & (exited > t - FIVE)).any()) for t in observed]
        check.require('no sizing during known occupied or exit bucket', not any(busy))
        expected_diagnostics = dict(contracts_entered=int(size.sum()),
            planned_stop_risk_cash_entered=float(trades.planned_stop_risk_cash.sum()),
            actual_stop_risk_cash_entered=float((actual * size).sum()),
            risk_budget_overshoot_entries=int((actual * size - budget > 1e-9).sum()),
            risk_budget_overshoot_cash=float(np.maximum(0, actual * size - budget).sum()))
        for name, expected in expected_diagnostics.items():
            check.close('diagnostic ' + name, diagnostics[name], expected, atol=1e-5)
    return check.finish()


def audit_case(case, dataset, trades, equity, summary, diagnostics, raw, decisions=None):
    """In-memory entry point used by mutation tests and immutable artifact CLI."""
    check = base.Checks(identity(case))
    components = {}
    capital = float((case['parameters'] or {}).get('capital', 100000))
    if case['decision'] == 'cash':
        check.require('cash has no chosen parameters', case['parameters'] is None)
        check.require('cash has no trades or quantity decisions', trades.empty and (decisions is None or decisions.empty))
        check.close('cash constant equity', equity.equity, capital)
        for name in ('unrealized_pnl', 'net_pnl', 'contracts'):
            check.close('cash zero ' + name, equity[name], 0)
        check.close('cash balance', equity.balance, capital)
        check.require('cash interval boundaries', np.array_equal(base.ns(equity.timestamp), base.ns([case['start'], case['end']])))
        for name in ('trades', 'net_pnl', 'max_drawdown'):
            check.close('cash summary ' + name, summary[name], 0)
    else:
        p = case['parameters']
        d = dict(dataset, start=case['start'], end=case['end'])
        fee = dataset['fee'] * case['fee_multiple']
        ticks = case['slippage_ticks']
        normalized = normalize_one_contract(trades)
        one_p = dict(p, sizing_mode='fixed_contracts', contracts=1)
        components['ledger_geometry'] = base.audit_ledger(normalized, one_p, d, fee=fee, slippage_ticks=ticks)
        components['accounting'] = audit_accounting(trades, equity, p, d, raw, summary, fee, ticks)
        sample = base.sample_indices(len(trades))
        components['raw_sample'] = base.audit_raw_trades(normalized.iloc[sample].reset_index(drop=True), one_p, d, raw,
            fee=fee, slippage_ticks=ticks, diagnostics=diagnostics)
        check.result['sample_ordinals'] = sample.tolist()
        if case['role'].startswith('risk-'):
            check.require('risk decision ledger retained', decisions is not None)
            if decisions is not None:
                components['sizing'] = audit_sizing(trades, decisions, p, d, raw, diagnostics, fee, ticks)
            sizing_summary = dict(contracts_entered=int(trades.contracts_abs.sum()),
                max_quantity=int(trades.contracts_abs.max()) if len(trades) else 0,
                maximum_planned_stop_loss=float(trades.planned_stop_risk_cash.max()) if len(trades) else 0.,
                maximum_actual_stop_loss=float(trades.actual_stop_risk_cash.max()) if len(trades) else 0.,
                total_budget_overshoot=float(trades.risk_budget_overshoot_cash.sum()) if len(trades) else 0.)
            for name, value in sizing_summary.items():
                check.require('sizing summary field ' + name, name in summary)
                if name in summary:
                    check.close('sizing summary ' + name, summary[name], value, atol=1e-5)
        else:
            check.close('reference selected neighbor fixed one contract', trades.quantity, trades.side)
        check.require('diagnostic trade count', diagnostics.get('trades') == len(trades))
    for name, result in components.items():
        check.result['checks'] += result['checks']
        check.result['failures'].extend(name + ': ' + failure for failure in result['failures'])
    check.result['components'] = {k: base._compact(v) for k, v in components.items()}
    return check.finish()


def audit_artifact(folder, case, dataset, raw, identities):
    folder = Path(folder)
    check = base.Checks(identity(case) + '/artifacts')
    saved, result = base.read(folder / 'input.json'), base.read(folder / 'result.json')
    check.require('succeeded result and status', result['status'] == base.read(folder / 'status.json')['status'] == 'succeeded')
    for name, value in dict(case, **identities).items():
        check.require('input identity ' + name, saved.get(name) == value)
        check.require('result identity ' + name, result.get(name) == value)
    check.require('input declared dataset', saved.get('dataset') == dataset)
    names = [a['name'] for a in result['artifacts']]
    required = {'trades.parquet', 'equity.parquet'}
    if case['decision'] != 'cash' and case['role'].startswith('risk-'):
        required.add('sizing-decisions.parquet')
    check.require('complete unique artifact list', set(names) == required and len(names) == len(set(names)))
    for artifact in result['artifacts']:
        path = (folder / artifact['name']).resolve()
        check.require('contained artifact ' + artifact['name'], path.is_relative_to(folder.resolve()))
        check.require('artifact hash ' + artifact['name'], base.sha(path) == artifact['checksum'])
    record = audit_case(case, dataset, pd.read_parquet(folder / 'trades.parquet'), pd.read_parquet(folder / 'equity.parquet'),
        result['summary'], result['diagnostics'], raw,
        pd.read_parquet(folder / 'sizing-decisions.parquet') if 'sizing-decisions.parquet' in required else None)
    record['checks'] += check.result['checks']
    record['failures'].extend(check.result['failures'])
    record['passed'] = not record['failures']
    record['artifact_checks'] = check.finish()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=base.DEFAULT_OUT)
    parser.add_argument('--symbol', action='append', help='Diagnostic subset; never reported complete.')
    args = parser.parse_args()
    out = args.output.resolve()
    source, protocol, manifest, configs = base.audit_frozen_inputs(out)
    runtime = {'scripts/audit-snd-combination-validation.py': __file__,
               'scripts/audit-snd-combinations.py': base.__file__}
    base.require_frozen_runtime(manifest, runtime)
    check = base.Checks('validation plan and source identities')
    check.require('frozen source audit', source['passed'])
    own = next((f for f in manifest['files'] if f['path'] == 'scripts/audit-snd-combination-validation.py'), None)
    check.require('validation auditor matches frozen source', own is not None and own['checksum'] == base.sha(__file__))
    selection, plan = base.read(out / 'selection.json'), base.read(out / 'validation-plan.json')
    completion = base.read(out / 'validation-results.json')
    identities = {k: manifest[k] for k in ('protocol_checksum', 'source_hash', 'configurations_checksum')}
    for name, value in identities.items():
        check.require('selection identity ' + name, selection.get(name) == value)
    check.require('selection training-only full-grid declaration', selection.get('training_only') is True and selection.get('complete_grid_verified') is True)
    identities['selection_checksum'] = base.sha(out / 'selection.json')
    for name, value in identities.items():
        check.require('plan identity ' + name, plan.get(name) == value)
        check.require('completion identity ' + name, completion.get(name) == value)
    expected = declared_cases(selection, protocol, {c['config_id']: c for c in configs})
    expected_by_id = {identity(c): c for c in expected}
    actual_by_id = {identity(c): c for c in plan['cases']}
    completed_by_id = {identity(c): c for c in completion['cases']}
    check.require('complete exact independently declared 312 case plan', len(expected) == 312 and
                  len(plan['cases']) == 312 and expected_by_id == actual_by_id and plan['expected_cases'] == 312)
    check.require('complete validation terminal manifest', completion.get('status') == 'succeeded' and
        completion.get('expected_cases') == completion.get('completed_cases') == len(completion['cases']) == 312 and
        set(completed_by_id) == set(expected_by_id))
    if args.symbol and not set(args.symbol).issubset(protocol['markets']):
        parser.error('Unknown market')
    reports, failures, raw_sources = [], [], []
    if not check.finish()['passed']:
        failures.append(dict(identity=check.result['identity'], failures=check.result['failures']))
    for dataset in protocol['datasets']:
        if args.symbol and dataset['symbol'] not in args.symbol:
            continue
        for fold in protocol['folds']:
            cases = [c for c in expected if c['symbol'] == dataset['symbol'] and c['fold_id'] == fold['id']]
            raw = base.raw_market(dict(dataset, start=fold['cutoff'], end=fold['test_end']))
            raw_sources.extend(raw['identities'])
            for case in cases:
                folder = out / 'validation' / identity(case)
                try:
                    record = audit_artifact(folder, case, dataset, raw, identities)
                    result = base.read(folder / 'result.json')
                    if result != completed_by_id.get(identity(case)):
                        record['failures'].append('Terminal aggregate does not equal saved case result')
                        record['passed'] = False
                    if pd.Timestamp(plan['declared_at']) > pd.Timestamp(result['completed_at']):
                        record['failures'].append('Case completed before validation plan declaration')
                        record['passed'] = False
                    record['checks'] += 2
                except Exception as error:
                    record = dict(identity=identity(case), passed=False, checks=0, failures=[type(error).__name__ + ': ' + str(error)])
                destination = out / 'audit' / 'validation' / (identity(case) + '.json')
                base._save(destination, record)
                reports.append(dict(identity=identity(case), passed=record['passed'], checks=record['checks'],
                    path=str(destination.relative_to(out)), checksum=base.sha(destination)))
                if not record['passed']:
                    failures.append(dict(identity=record['identity'], failures=record['failures']))
            print(dataset['symbol'] + '/' + fold['id'] + ': ' + str(len(cases)) + ' validation cases audited', flush=True)
            del raw
    observed = {identity(dict(zip(('symbol', 'fold_id', 'role', 'scenario'), p.relative_to(out / 'validation').parts[:-1])))
                for p in (out / 'validation').glob('*/*/*/*/result.json')}
    complete = len(reports) == 312 and {r['identity'] for r in reports} == set(expected_by_id)
    check.require('no undeclared validation results', observed.issubset(expected_by_id))
    for failure in check.result['failures']:
        if not any(failure in f['failures'] for f in failures):
            failures.append(dict(identity=check.result['identity'], failures=[failure]))
    report = dict(audited_at=datetime.now(timezone.utc).isoformat(), **identities,
        script_checksum=base.sha(__file__), status='failed' if failures else ('passed' if complete else 'incomplete'),
        complete_validation=complete, expected_cases=312, audited_cases=len(reports),
        total_checks=source['checks'] + check.result['checks'] + sum(r['checks'] for r in reports),
        source_checks=source, identity_checks=check.finish(), raw_sources=raw_sources, records=reports, failures=failures,
        scope='Independent arithmetic and raw conditions for every saved quantity decision, including zero quantities; full trade accounting and raw-close five-minute equity; deterministic first/middle/last raw trade samples.',
        limitations=['Does not prove absence of omitted otherwise eligible signals or replay every intervening trade bracket path.',
            'Full simulator/reference parity and selection-statistic validity require separate evidence.',
            'No queue, margin, buying-power, liquidity or prospective trading claim.'])
    base.require_frozen_runtime(manifest, runtime)
    base._save(out / 'independent-validation-audit.json', report)
    print({k: report[k] for k in ('status', 'complete_validation', 'audited_cases', 'total_checks')}, flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
