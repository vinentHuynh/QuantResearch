"""Frozen MNQ KC descriptive and confirmatory statistics; no parameter search."""
from pathlib import Path
import hashlib
import json
import math
import shutil
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'artifacts/mnq-keltner-2026-10-26'
HERE = Path(__file__).resolve().parent
SEED = 261026
REPS = 2000
SIZE_LABELS = ['0-0.25', '0.25-0.5', '0.5-1', '1+']


class Blocks:
    def __init__(self, days):
        self.days = sorted(set(str(x)[:10] for x in days if pd.notna(x)))
        self.lookup = {d: i // 5 for i, d in enumerate(self.days)}
        self.g = max(self.lookup.values()) + 1
        rng = np.random.default_rng(SEED)
        self.weights = rng.multinomial(self.g, np.ones(self.g) / self.g, size=REPS).astype(float)

    def totals(self, days, vals):
        codes = np.array([self.lookup[str(x)[:10]] for x in days], dtype=int)
        v = np.asarray(vals, float)
        return (np.bincount(codes, weights=v, minlength=self.g),
                np.bincount(codes, minlength=self.g).astype(float))

    def draws(self, days, vals):
        y, n = self.totals(days, vals)
        denom = self.weights @ n
        return np.divide(self.weights @ y, denom, out=np.full(REPS, np.nan), where=denom > 0)

    def ci(self, days, vals):
        if len(vals) < 20 or len(set(days)) < 10:
            return (np.nan, np.nan)
        return tuple(np.nanquantile(self.draws(days, vals), [.025, .975]))

    def p_half(self, days, vals):
        if len(vals) < 20:
            return np.nan
        y, n = self.totals(days, vals)
        active = n > 0
        g = int(active.sum())
        if g < 10:
            return np.nan
        p = y.sum() / n.sum()
        se = math.sqrt(g / (g - 1) * np.sum((y - p * n) ** 2) / n.sum() ** 2)
        return math.erfc(abs(p - .5) / se / math.sqrt(2)) if se else np.nan


def summarize(d, blocks, horizon=60, barrier='05', controls=True):
    col = f'outcome_{barrier}_{horizon}'
    o = d[col]
    decisive = o.isin(['reversion', 'continuation'])
    v = d.loc[decisive]
    ys = (v[col] == 'reversion').astype(float)
    r = {'events': len(d), 'complete': int((o != 'incomplete').sum()),
         'reversion': int((o == 'reversion').sum()), 'continuation': int((o == 'continuation').sum()),
         'unresolved': int((o == 'unresolved').sum()), 'ambiguous': int((o == 'ambiguous').sum()),
         'incomplete': int((o == 'incomplete').sum()), 'decisive': len(v),
         'days': d.day.nunique(), 'decisive_days': v.day.nunique(),
         'p_reversion': float(ys.mean()) if len(v) else np.nan}
    r['p_ci_low'], r['p_ci_high'] = blocks.ci(v.day, ys)
    r['p_two_sided'] = blocks.p_half(v.day, ys)
    r['sufficient'] = len(v) >= 100 and v.day.nunique() >= 50
    n = r['complete']
    r['reversion_all_complete'] = r['reversion'] / n if n else np.nan
    touched = r['decisive'] + r['ambiguous']
    r['ambiguity_bound_low'] = r['reversion'] / touched if touched else np.nan
    r['ambiguity_bound_high'] = (r['reversion'] + r['ambiguous']) / touched if touched else np.nan
    rc = f'ret_atr_{horizon}'
    ret = d.loc[d[rc].notna()]
    a = ret[rc]
    r.update(return_n=len(a), return_mean_atr=a.mean(), return_median_atr=a.median(),
             return_p10_atr=a.quantile(.1), return_p90_atr=a.quantile(.9),
             return_mean_points=ret[f'ret_points_{horizon}'].mean(),
             return_reversion_p=float((a < 0).sum() / (a != 0).sum()) if (a != 0).any() else np.nan)
    r['return_mean_ci_low'], r['return_mean_ci_high'] = blocks.ci(ret.day, a)
    for feat in ['extreme_extension_atr', 'extreme_extension_points', 'close_extension_atr',
                 'range_atr', 'range_points', 'outer_wick_atr', 'outer_wick_points', 'outer_wick_fraction']:
        r[feat + '_median'] = d[feat].median()
    for field in [f'ema_touch_{horizon}', f'band_return_{horizon}']:
        r[field + '_rate'] = pd.to_numeric(d[field], errors='coerce').mean()
    for field in [f'mfe_reversion_atr_{horizon}', f'mfe_continuation_atr_{horizon}']:
        if field in d:
            for q in [.1, .5, .9]:
                r[field + f'_p{int(q*100)}'] = d[field].quantile(q)
    r.update(matched_events=0, paired_decisive=0, unique_controls=0,
             paired_event_p=np.nan, paired_control_p=np.nan, control_difference=np.nan,
             control_diff_ci_low=np.nan, control_diff_ci_high=np.nan)
    ccol = 'control_' + col
    if controls and ccol in d:
        r['matched_events'] = int(d.control_timestamp.notna().sum())
        r['unique_controls'] = d.control_timestamp.nunique()
        paired = d.loc[decisive & d[ccol].isin(['reversion', 'continuation']) & d.control_day.notna()]
        r['paired_decisive'] = len(paired)
        if len(paired):
            e = (paired[col] == 'reversion').astype(float)
            c = (paired[ccol] == 'reversion').astype(float)
            r.update(paired_event_p=e.mean(), paired_control_p=c.mean(), control_difference=e.mean()-c.mean())
            if len(paired) >= 20 and paired.day.nunique() >= 10 and paired.control_day.nunique() >= 10:
                diffs = blocks.draws(paired.day, e) - blocks.draws(paired.control_day, c)
                r['control_diff_ci_low'], r['control_diff_ci_high'] = np.nanquantile(diffs, [.025, .975])
    return r


def holm(p):
    p = np.nan_to_num(np.array(p, float), nan=1)
    idx = np.argsort(p)
    adj = np.maximum.accumulate(p[idx] * np.arange(len(p), 0, -1))
    result = np.zeros(len(p))
    result[idx] = np.minimum(adj, 1)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__), OUT / 'analyze.py')
    frames = []
    for tf in [5, 15]:
        d = pd.read_parquet(OUT / f'events_{tf}m.parquet')
        d['timeframe'] = tf
        d['day'] = d.day.astype(str).str[:10]
        d['control_day'] = d.control_day.where(d.control_day.notna(), None)
        frames.append(d)
    all_data = pd.concat(frames, ignore_index=True)
    all_data['year'] = all_data.day.str[:4].astype(int)
    for feat in ['extreme_extension', 'close_extension', 'outer_wick', 'wick_portion_outside']:
        all_data[feat+'_bin'] = pd.cut(all_data[feat+'_atr'], [0,.25,.5,1,np.inf], right=False, labels=SIZE_LABELS)
    all_data['range_bin'] = pd.cut(all_data.range_atr,[0,1,1.5,2,np.inf],right=False,labels=['<1','1-1.5','1.5-2','2+'])
    all_data['wick_fraction_bin'] = pd.cut(all_data.outer_wick_fraction,[0,.25,.5,.75,1.000001],right=False,labels=['<25%','25-50%','50-75%','75-100%'])
    all_data['body_fraction_bin'] = pd.cut(all_data.body_fraction,[0,.25,.5,.75,1.000001],right=False,labels=['<25%','25-50%','50-75%','75-100%'])
    all_data['lag_extension_bin'] = pd.cut(all_data.extreme_extension_points / all_data.prebar_atr,[0,.25,.5,1,np.inf],right=False,labels=SIZE_LABELS)
    all_data['trend_bin'] = pd.cut(all_data.prebar_ema_slope_atr,[-np.inf,0,.5,1,np.inf],right=False,labels=['against (<0)','flat/weak (0-0.5)','moderate (0.5-1)','strong (1+)'])
    blocks = {}
    calendar_path = OUT / 'calendar.json'
    calendar = json.loads(calendar_path.read_text(encoding='utf-8')) if calendar_path.exists() else None
    for split in ['development','validation','test','all']:
        part = all_data if split == 'all' else all_data[all_data.split == split]
        days = list(part.day) + list(part.control_day.dropna())
        if calendar is not None:
            dates = [d for values in calendar.values() for d in values] if split == 'all' else calendar[split]
            days += dates
        blocks[split] = Blocks(days)
    tables = {x: [] for x in ['primary','size','session','side','year','horizon','cohort','trend','open_state']}
    for tf in [5,15]:
        tfdata = all_data[all_data.timeframe == tf]
        primary = tfdata[tfdata.episode_start]
        for split in ['development','validation','test','all']:
            part = primary if split == 'all' else primary[primary.split == split]
            b = blocks[split]
            for typ in ['wick_only','close_outside']:
                sub = part[part.type == typ]
                for label in ['all'] + SIZE_LABELS:
                    cell = sub if label=='all' else sub[sub.extreme_extension_bin == label]
                    tables['primary'].append(dict(timeframe=tf,split=split,type=typ,bin=label,**summarize(cell,b)))
                if split in ['test','all']:
                    for field in ['close_extension_bin','outer_wick_bin','wick_portion_outside_bin','range_bin','wick_fraction_bin','body_fraction_bin','lag_extension_bin']:
                        if field=='close_extension_bin' and typ=='wick_only':
                            continue
                        for label in all_data[field].cat.categories:
                            cell=sub[sub[field]==label]
                            tables['size'].append(dict(timeframe=tf,split=split,type=typ,feature=field,bin=label,**summarize(cell,b)))
                    for field, table in [('time_bucket','session'),('side','side'),('trend_bin','trend'),('open_outside','open_state')]:
                        for label in sorted(sub[field].dropna().unique()):
                            for h in ([15,60,120] if table=='session' else [60]):
                                tables[table].append(dict(timeframe=tf,split=split,type=typ,bin=label,horizon=h,**summarize(sub[sub[field]==label],b,h)))
                    for h in [15,60,120]:
                        for barrier in ['05','10']:
                            tables['horizon'].append(dict(timeframe=tf,split=split,type=typ,horizon=h,barrier=barrier,**summarize(sub,b,h,barrier)))
                print(f'Analyzed {tf}m {split} {typ}',flush=True)
        for year in sorted(primary.year.unique()):
            for typ in ['wick_only','close_outside']:
                sub=primary[(primary.year==year)&(primary.type==typ)]
                tables['year'].append(dict(timeframe=tf,year=year,type=typ,**summarize(sub,blocks['all'])))
        for cohort, mask in [('all_bars',np.ones(len(tfdata),bool)),('episode_start',tfdata.episode_start),('first_close',tfdata.first_close_outside)]:
            for split in ['test','all']:
                for typ in ['wick_only','close_outside']:
                    if cohort=='first_close' and typ=='wick_only': continue
                    sub=tfdata[mask & (tfdata.type==typ)]
                    if split!='all': sub=sub[sub.split==split]
                    tables['cohort'].append(dict(timeframe=tf,split=split,type=typ,cohort=cohort,**summarize(sub,blocks[split])))
    tables={k:pd.DataFrame(v) for k,v in tables.items()}
    p=tables['primary']
    test=(p.split=='test')&(p.bin!='all')
    p.loc[test,'holm_p']=holm(p.loc[test,'p_two_sided'])
    p['stable_direction']=False
    p['directional_claim']=False
    p['control_supported']=False
    for i,row in p.loc[test].iterrows():
        prev=p[(p.timeframe==row.timeframe)&(p.type==row.type)&(p.bin==row['bin'])&p.split.isin(['development','validation'])]
        s=np.sign(row.p_reversion-.5)
        stable=bool(len(prev)==2 and (np.sign(prev.p_reversion-.5)==s).all())
        control_ok=(row.control_diff_ci_low>0 if s>0 else row.control_diff_ci_high<0)
        p.loc[i,'stable_direction']=stable
        p.loc[i,'directional_claim']=bool(stable and row.sufficient and row.holm_p<.05 and (row.p_ci_low>.5 or row.p_ci_high<.5))
        p.loc[i,'control_supported']=bool(control_ok)
    for name,df in tables.items():
        df.to_csv(OUT/f'{name}_summary.csv',index=False)
    # Complete chronological, row-level audit exports; no suppression of losing/sparse cells.
    for tf in [5,15]:
        all_data[all_data.timeframe==tf].to_csv(OUT/f'events_{tf}m.csv.gz',index=False,compression='gzip')
    result={
        'total_breach_bars':len(all_data),'episode_starts':int(all_data.episode_start.sum()),
        'test_cells':16,'directional_claims':int(p.loc[test,'directional_claim'].sum()),
        'control_supported_directional_claims':int((p.loc[test,'directional_claim']&p.loc[test,'control_supported']).sum()),
        'primary_test':json.loads(p.loc[test].to_json(orient='records')),
        'protocol_sha256':hashlib.sha256((HERE/'protocol.json').read_bytes()).hexdigest(),
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'bootstrap_reps':REPS,'seed':SEED,
        'block_counts':{k:v.g for k,v in blocks.items()},
        'calendar_source':'full observed source trading dates' if calendar is not None else 'union event/control dates',
        'inference_notes':'Five-day non-overlapping block bootstrap; reused controls assigned their original-day weight. Matched contrast uses pairs decisive in BOTH arms. Pointwise intervals, normal-approximation cluster tests with Holm over 16 primary cells. Historical evaluation only.'}
    (OUT/'statistical_result.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='primary_test'},indent=2))


if __name__=='__main__':
    main()
