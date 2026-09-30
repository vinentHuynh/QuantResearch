"""Verify and summarize immutable whole-contract MNQ sizing results."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/snd-risk-research-2026-09-25'
spec = importlib.util.spec_from_file_location('risk_report_identity', ROOT / 'scripts/report-snd-body-retest.py')
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)
helper = identity.helper
checksum, clean, save, read = helper.checksum, helper.clean, helper.save, helper.read_json
FIELDS = ['trades', 'net_pnl', 'closed_trade_pnl', 'profit_factor', 'max_drawdown_dollars',
          'mean_net_r', 'mean_planned_stop_r', 'median_contracts', 'maximum_contracts',
          'modeled_execution_costs', 'median_risk_points', 'mean_planned_stop_risk_cash',
          'actual_stop_budget_overrun_trades', 'maximum_actual_stop_budget_overrun',
          'realized_loss_over_budget_trades', 'maximum_realized_loss_over_budget',
          'net_excluding_top_five_winners']


def verify_case(out, definition, dataset, protocol_hash, source_hash, capital):
    folder = out / definition['symbol'] / definition['variant']
    result = read(folder / 'result.json')
    if result.get('status') != 'succeeded':
        raise ValueError('Historical attempt status: ' + result.get('status', 'missing'))
    if result['protocol_checksum'] != protocol_hash or result['source_hash'] != source_hash:
        raise ValueError('Result evidence identity mismatch')
    inp = read(folder / 'input.json')
    if any(inp.get(k) != v for k, v in definition.items()) or inp['dataset'] != dataset:
        raise ValueError('Saved input differs from declaration')
    if any(result['parameters'].get(k) != v for k, v in definition['parameters'].items()):
        raise ValueError('Resolved parameters differ from declaration')
    required = {'trades.csv', 'equity.parquet', 'sizing-decisions.csv'}
    artifacts = {item['name']: item['checksum'] for item in result['artifacts']}
    if not required.issubset(artifacts):
        raise ValueError('Missing declared artifact')
    for name, digest in artifacts.items():
        if checksum(helper.safely_beneath(folder, name)) != digest:
            raise ValueError('Changed artifact: ' + name)
    trades = pd.read_csv(folder / 'trades.csv')
    equity = pd.read_parquet(folder / 'equity.parquet')
    decisions = pd.read_csv(folder / 'sizing-decisions.csv')
    qty = trades.quantity.abs()
    if ((qty < 1) | (qty > definition['parameters']['max_contracts']) | (qty != np.floor(qty))).any():
        raise ValueError('Noninteger or excessive quantity')
    np.testing.assert_allclose(trades.risk_cash, trades.risk * dataset['point_value'] * qty, atol=1e-7, rtol=0)
    np.testing.assert_allclose(trades.net_r, trades.net_pnl / trades.risk_cash, atol=1e-7, rtol=0)
    np.testing.assert_allclose(trades.gross_pnl, trades.quantity * (trades.exit-trades.entry) * dataset['point_value'], atol=1e-7, rtol=0)
    np.testing.assert_allclose(trades.net_pnl, trades.gross_pnl-trades.cost, atol=1e-7, rtol=0)
    np.testing.assert_allclose(equity.equity, equity.balance+equity.unrealized_pnl, atol=1e-6, rtol=0)
    np.testing.assert_allclose(equity.equity.iloc[-1]-capital, trades.net_pnl.sum(), atol=1e-5, rtol=0)
    np.testing.assert_allclose(equity.net_pnl.sum(), trades.net_pnl.sum(), atol=1e-5, rtol=0)
    if equity.contracts.iloc[-1] != 0:
        raise ValueError('Historical endpoint did not flatten')
    if pd.to_datetime(equity.timestamp, utc=True).duplicated().any():
        raise ValueError('Duplicate equity marks')
    return result, trades, equity, decisions


def cohort_for(trades, bounds):
    if bounds is None:
        return trades
    return trades.loc[helper.helper.trade_mask(trades, helper.helper.utc(bounds[0]), helper.helper.utc(bounds[1]))]


def summarize(trades, equity, dataset, bounds, parameters):
    metrics = helper.summarize(trades, equity, dataset, bounds)
    cohort = cohort_for(trades, bounds)
    qty = cohort.quantity.abs()
    embedded = 0.
    if parameters['slippage_model'] == 'price':
        embedded = float((((cohort.entry-cohort.entry_price_before_slippage).abs() +
            (cohort.exit-cohort.exit_price_before_slippage).abs()) * qty * dataset['point_value']).sum())
    for key in ['double_cost_net', 'double_cost_repricing_net']:
        metrics.pop(key, None)
    fixed_risk = parameters['sizing_mode'] == 'fixed_risk'
    budget = float(parameters['risk_budget'])
    actual_overrun = (cohort.actual_stop_risk_cash-budget).clip(lower=0) if fixed_risk else pd.Series(dtype=float)
    realized_overrun = (-cohort.net_pnl-budget).clip(lower=0) if fixed_risk else pd.Series(dtype=float)
    metrics.update(
        stress_basis='Only separately declared complete cost/price simulator reruns; no unchanged-ledger doubled-cost claim.',
        minimum_risk_cash=float(cohort.risk_cash.min()) if len(cohort) else None,
        median_contracts=float(qty.median()) if len(cohort) else None,
        maximum_contracts=int(qty.max()) if len(cohort) else None,
        quantity_distribution=qty.value_counts().sort_index().to_dict(),
        modeled_execution_costs=float(cohort.cost.sum())+embedded,
        embedded_price_slippage=embedded,
        mean_planned_stop_r=float((cohort.net_pnl/cohort.planned_stop_risk_cash).mean()) if len(cohort) else None,
        mean_planned_stop_risk_cash=float(cohort.planned_stop_risk_cash.mean()) if len(cohort) else None,
        mean_budget_utilization=float((cohort.planned_stop_risk_cash/budget).mean()) if len(cohort) and fixed_risk else None,
        actual_stop_budget_overrun_trades=int((actual_overrun > 1e-7).sum()) if fixed_risk else None,
        maximum_actual_stop_budget_overrun=float(actual_overrun.max()) if len(actual_overrun) else None,
        realized_loss_over_budget_trades=int((realized_overrun > 1e-7).sum()) if fixed_risk else None,
        maximum_realized_loss_over_budget=float(realized_overrun.max()) if len(realized_overrun) else None,
    )
    return clean(metrics)


def cached_summary(out, definition, trades, equity, dataset, periods, protocol_hash, source_hash):
    folder = out / 'MNQ' / definition['variant']
    keydata = dict(protocol=protocol_hash, source=source_hash, parameters=definition['parameters'],
        trades=checksum(folder/'trades.csv'), equity=checksum(folder/'equity.parquet'), periods=periods,
        summary=hashlib.sha256((inspect.getsource(summarize)+inspect.getsource(cohort_for)).encode()).hexdigest())
    digest = hashlib.sha256(json.dumps(keydata, sort_keys=True).encode()).hexdigest()
    path = out / 'analysis-cache' / (definition['variant']+'-'+digest+'.json')
    if path.exists():
        prior = read(path)
        if prior['identity'] == keydata:
            return prior['periods']
    result = {name: summarize(trades, equity, dataset, bounds, definition['parameters']) for name, bounds in periods.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, dict(identity=keydata, periods=result))
    return result


def report(analysis):
    p = analysis['protocol']
    lines = ['# MNQ sizing test and prospective setup', '',
        f"Evidence status: **{analysis['status']}**. Verified {analysis['completed_cases']}/{p['expected_cases']} cases; {len(analysis['exact_controls'])} exact prior controls.", '',
        f"The primary planned budget is ${p['primary_risk_budget']:g} with a {p['max_contracts']}-contract cap. Half/double budgets are sensitivity checks. All signal rules remain frozen. No tested budget is automatically selected for deployment.", '',
        '## Sizing assumptions', '',
        'At arming, divide the fixed dollar budget by the known trigger-to-stop cash loss plus modeled round-trip stop slippage and commissions; round down and cap contracts. The order keeps that quantity. A zero-contract candidate is skipped, so subsequent trades can change. Entry and stop gaps can overrun the planned budget. The cap does not establish margin feasibility.', '',
        'Cash mode preserves the earlier cash-charge simulator. Price mode moves entry/non-limit exit prices adversely; targets stay at their limit. All fees, price slippage attribution and cash risk scale by quantity. Reported net P&L already includes these costs.', '',
        'Mean R divides each trade net P&L by actual fill-to-stop price-distance risk times point value times quantity. It is not return divided by the fixed dollar budget. Quantity normally cancels from this ratio; sizing changes mean R mainly through trade selection. Return divided by planned all-in stop risk is saved separately in analysis.', '',
        '## Results', '']
    for period, label in [('all','January2022–July2026'), ('later_combined','January2025–July2026'),
                          ('year_2024','Calendar2024'), ('later_2025','Calendar2025'), ('latest_2026','January–July2026')]:
        lines += ['### '+label, '', helper.table(
            ['Case','Trades','Marked net','PF','Max DD','Mean R','Median qty','Actual stop-risk overruns'],
            [[c['variant'], c.get('periods',{}).get(period,{}).get('trades','n/a'),
              *[helper.number(c.get('periods',{}).get(period,{}).get(k), money=k in ['net_pnl','max_drawdown_dollars']) for k in ['net_pnl','profit_factor','max_drawdown_dollars','mean_net_r','median_contracts','actual_stop_budget_overrun_trades']]]
             for c in analysis['cases']]), '']
    lines += ['## Predeclared primary sizing check', '',
        f"Positive full and later net in every declared execution scenario: **{analysis['primary_economic_check']}**. This is a narrow historical sizing check; it is not a fresh-data validation or live approval.", '',
        '## Selection and risk diagnostics', '', helper.table(
            ['Case','Sizing attempts','Budget skips','Capped attempts','Max actual stop-risk excess','Max realized loss excess'],
            [[c['variant'],c.get('sizing_attempts','n/a'),c.get('budget_skips','n/a'),c.get('capped_attempts','n/a'),
              helper.number(c.get('periods',{}).get('all',{}).get('maximum_actual_stop_budget_overrun'),money=True),
              helper.number(c.get('periods',{}).get('all',{}).get('maximum_realized_loss_over_budget'),money=True)] for c in analysis['cases']]), '',
        'The actual-stop-risk excess uses the actual entry and an assumed nongapping stop exit. A later stop gap can create an additional realized-loss excess. Neither measure is a guaranteed risk bound.', '',
        '## Fractional diagnostic only', '',
        'The following reprices prior one-contract executed trades to the primary budget using actual initial price-distance risk. It can use fractional contracts and actual fill information, so it is a mathematical equal-R diagnostic, not an executable order-sizing backtest. It also preserves the original opportunity sequence. Integer sizing above is a separate simulator rerun.', '',
        helper.table(['Control','Period','Sum net R','Theoretical constant-risk net'],
            [[x['variant'],x['period'],helper.number(x['sum_net_r'],4),helper.number(x['theoretical_constant_price_risk_net'],money=True)] for x in analysis['fractional_diagnostic']]), '',
        '## Evidence and limits', '',
        'Marked P&L and drawdown use saved observed five-minute closes and period opening marks. PF, sample counts, costs, quantity/risk distributions and mean R use trades closed within each period. The 2,000-draw occupied-exit-week mean-R intervals are descriptive and do not adjust for selection among the research variants.', '',
        'All scored history was previously inspected. Contract roll adjustments, missing-minute ambiguities and conservative intraminute ordering remain inherited. Margin, queue, partial fills, liquidity and market impact are not modeled. The historical test cannot establish prospective profitability.', '',
        f"Independent audit: {analysis.get('audit',{}).get('status','missing')}; {analysis.get('audit',{}).get('total_checks','n/a')} checks. See [audit](independent-audit.json) for its precise scope and limitations.", '',
        '- [Every case and period](all-results.csv)',
        '- [Structured analysis](analysis.json)',
        '- [Frozen protocol](protocol.json)',
        '- [Source and artifact verification](verification.json)',
        '- [Prospective workflow](../../docs/research/snd/SND_FORWARD_TEST.md)', '',
        '![Marked sizing equity](mnq-risk-sizing.png)', '']
    if analysis['errors']:
        lines += ['## Incomplete or failed evidence', '', *['- '+x for x in analysis['errors']], '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--require-complete',action='store_true')
    args=parser.parse_args()
    out=args.output.resolve()
    p=read(out/'protocol.json')
    ph=checksum(out/'protocol.json')
    source,manifest=identity.check_source_set(out,ph)
    data_check=identity.check_dataset_files(p['datasets'])
    prior,old_protocol,old_manifest,old_out=identity.prior_campaign(p)
    errors=[*source['errors'],*prior['errors']]
    if not data_check['verified']: errors.append('Input dataset checksum failure')
    dataset=p['datasets'][0]
    periods={'all':None,**p['periods']}
    cases,rows,controls,fractional,curves=[],[],[],[],{}
    for definition in p['cases']:
        case={k:definition[k] for k in ['symbol','variant','sizing','scenario']}
        try:
            result,trades,equity,decisions=verify_case(out,definition,dataset,ph,manifest['source_hash'],p['capital'])
            case.update(status='succeeded',diagnostics=result['diagnostics'],sizing_attempts=len(decisions))
            case['periods']=cached_summary(out,definition,trades,equity,dataset,periods,ph,manifest['source_hash'])
            case['budget_skips']=int((decisions.quantity_selected==0).sum())
            case['capped_attempts']=int(decisions.quantity_capped.sum())
            if definition['scenario']=='price_1': curves[definition['sizing']]=equity
            if definition['prior_control']:
                old_folder=old_out/'MNQ'/definition['prior_control']
                old_result=read(old_folder/'result.json')
                for artifact in old_result['artifacts']:
                    if checksum(old_folder/artifact['name'])!=artifact['checksum']: raise ValueError('Prior control artifact changed')
                old_trades=pd.read_csv(old_folder/'trades.csv')
                old_equity=pd.read_parquet(old_folder/'equity.parquet')
                pd.testing.assert_frame_equal(old_trades,trades.loc[:,old_trades.columns],check_exact=True,check_dtype=True)
                pd.testing.assert_frame_equal(old_equity,equity,check_exact=True,check_dtype=True)
                controls.append(dict(variant=definition['variant'],prior_variant=definition['prior_control'],status='exact'))
                for period in ['all','later_combined']:
                    part=cohort_for(trades,periods[period])
                    sr=float(part.net_r.sum())
                    fractional.append(dict(variant=definition['variant'],period=period,sum_net_r=sr,
                        theoretical_constant_price_risk_net=sr*p['primary_risk_budget']))
        except Exception as ex:
            case.update(status='verification_failed',error=type(ex).__name__+': '+str(ex))
            errors.append(case['variant']+': '+case['error'])
        cases.append(case)
        for period in periods:
            metrics=case.get('periods',{}).get(period,{})
            ci=metrics.get('mean_r_95ci',[None,None])
            rows.append(dict(symbol='MNQ',variant=case['variant'],period=period,status=case['status'],
                **{field:metrics.get(field) for field in FIELDS},ci_low=ci[0],ci_high=ci[1]))
        print(case['variant']+': '+case['status'],flush=True)
    audit=read(out/'independent-audit.json') if (out/'independent-audit.json').exists() else {}
    if audit.get('status')!='passed' or audit.get('protocol_checksum')!=ph or audit.get('source_manifest_checksum')!=checksum(out/'source-manifest.json'):
        errors.append('Independent audit missing, failed or identity mismatch')
    if len(controls)!=4: errors.append('Expected four exact prior controls')
    if len(cases)!=p['expected_cases'] or len({c['variant'] for c in cases})!=16: errors.append('Expected16unique cases')
    primary=[c for c in cases if c['sizing']==f"risk_{p['primary_risk_budget']:g}"]
    economic='PASS' if len(primary)==4 and all(c.get('periods',{}).get(period,{}).get('net_pnl',-1)>0 for c in primary for period in ['all','later_combined']) else 'FAIL'
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(12,5.5))
    for name,e in curves.items(): ax.plot(pd.to_datetime(e.timestamp,utc=True),e.equity-p['capital'],label=name,linewidth=.9)
    ax.axhline(0,color='#777',linewidth=.7)
    ax.set(title='MNQ sizing | adverse one-tick price fills, fees included\nFrozen rules; previously inspected history',ylabel='Marked net P&L (USD)')
    ax.grid(alpha=.2); ax.legend(); fig.tight_layout(); fig.savefig(out/'mnq-risk-sizing.png',dpi=150); plt.close(fig)
    status='complete' if not errors else 'partial_or_unverified'
    analysis=dict(generated_at=datetime.now(timezone.utc).isoformat(),status=status,protocol=p,
        completed_cases=sum(c['status']=='succeeded' for c in cases),cases=cases,exact_controls=controls,
        fractional_diagnostic=fractional,primary_economic_check=economic if status=='complete' else 'UNVERIFIED',audit=audit,errors=errors)
    reporter_hash=checksum(Path(__file__))
    snapshot=out/'analysis-source'/('report-'+reporter_hash[:16]+'.py')
    snapshot.parent.mkdir(parents=True,exist_ok=True)
    snapshot.write_bytes(Path(__file__).read_bytes())
    verification=dict(status=status,protocol_checksum=ph,source_hash=manifest['source_hash'],source=source,
        datasets=data_check,prior=prior,controls=controls,audit_checksum=checksum(out/'independent-audit.json') if audit else None,
        reporter_checksum=reporter_hash,reporter_snapshot=str(snapshot.relative_to(out)),errors=errors)
    pd.DataFrame(rows).to_csv(out/'all-results.csv',index=False)
    save(out/'verification.json',verification)
    analysis['output_checksums']={name:checksum(out/name) for name in ['all-results.csv','verification.json','mnq-risk-sizing.png']}
    save(out/'analysis.json',analysis)
    (out/'REPORT.md').write_text(report(analysis),encoding='utf-8')
    print(f'{status}: {analysis["completed_cases"]}/16; {len(controls)}/4 controls; economic {economic}')
    if args.require_complete and status!='complete': raise SystemExit(2)


if __name__=='__main__': main()
