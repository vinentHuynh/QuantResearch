"""Exact opening five-minute wick/body frequency in available 2026 MNQ data."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'reports/mnq-first-5m-wicks-ytd-2026-10-28'
PRIOR=ROOT/'research/campaigns/mnq-opening-retracement-2026-10-28/protocol.json'
AS_OF='2026-10-28'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    prior=json.loads(PRIOR.read_text())
    source=Path(prior['data_path'])
    assert sha(source)==prior['data_sha256']
    assert sha(prior['calendar_path'])==prior['calendar_sha256']
    OUT.mkdir(parents=True,exist_ok=True)
    definition={'instrument':'MNQ.v.0','requested_period':['2026-01-01',AS_OF],
                'candle':'09:30 inclusive to 09:35 exclusive, America/New_York',
                'aggregation':'First open, maximum high, minimum low, last close across exactly five observed minute bars.',
                'body':'abs(close-open)','upper_wick':'high-max(open,close)',
                'lower_wick':'min(open,close)-low','match':'upper_wick > body AND lower_wick > body; strict, separately on each side.',
                'doji':'Include zero-body candles only when both wicks are positive; also report excluding all dojis.',
                'quality':'NYSE cash-session calendar; complete five-minute window, one instrument, valid finite tick-aligned OHLC; no imputation.',
                'interpretation':'Candle-shape frequency, not a forecast or trading win rate. Completed shape is known at 09:35.',
                'data_path':str(source),'data_sha256':prior['data_sha256'],
                'calendar_path':prior['calendar_path'],'calendar_sha256':prior['calendar_sha256']}
    (OUT/'definition.json').write_text(json.dumps(definition,indent=2)+'\n',encoding='utf-8')
    raw=pd.read_parquet(source,columns=['open','high','low','close','instrument_id','symbol'])
    assert raw.index.is_monotonic_increasing and not raw.index.has_duplicates
    assert set(raw.symbol.unique())=={'MNQ.v.0'}
    local=raw.tz_convert('America/New_York')
    last_local_date=local.index.max().strftime('%Y-%m-%d')
    endpoint=min(AS_OF,last_local_date)
    dates=pd.read_csv(prior['calendar_path']).cash_session
    dates=dates[dates.between('2026-01-01',endpoint)].tolist()
    window=local[(local.index.year==2026)].between_time('09:30','09:34').copy()
    window['date']=window.index.strftime('%Y-%m-%d')
    groups=dict(tuple(window.groupby('date')))
    records=[];excluded=[]
    for date in dates:
        frame=groups.get(date,window.iloc[:0])
        expected=pd.date_range(date+' 09:30',periods=5,freq='min',tz='America/New_York')
        missing=expected.difference(frame.index)
        if len(missing) or frame.instrument_id.nunique()!=1:
            excluded.append({'date':date,'reason':'missing minutes' if len(missing) else 'contract change','missing_minutes':len(missing)})
            continue
        assert frame.index.equals(expected.rename(frame.index.name))
        values=frame[['open','high','low','close']].to_numpy(dtype=float)
        assert np.isfinite(values).all() and (values>0).all()
        assert np.allclose(values*4,np.round(values*4),atol=1e-8,rtol=0)
        assert (values[:,1]>=values[:,[0,2,3]].max(axis=1)).all()
        assert (values[:,2]<=values[:,[0,1,3]].min(axis=1)).all()
        # Integer ticks make strict equality and zero-body handling exact.
        ticks=np.rint(values*4).astype(np.int64)
        o,h,l,c=int(ticks[0,0]),int(ticks[:,1].max()),int(ticks[:,2].min()),int(ticks[-1,3])
        body=abs(c-o);upper=h-max(o,c);lower=min(o,c)-l
        records.append({'date':date,'month':date[:7],'open':o/4,'high':h/4,'low':l/4,'close':c/4,
                        'body_points':body/4,'upper_wick_points':upper/4,'lower_wick_points':lower/4,
                        'range_points':(h-l)/4,'upper_longer':upper>body,'lower_longer':lower>body,
                        'both_wicks_longer':upper>body and lower>body,'doji':body==0,
                        'body_direction':'bullish' if c>o else 'bearish' if c<o else 'doji',
                        'instrument_id':int(frame.instrument_id.iloc[0]),'observed_minutes':len(frame)})
    daily=pd.DataFrame(records)
    daily.to_csv(OUT/'sessions.csv',index=False)
    matches=daily[daily.both_wicks_longer]
    matches.to_csv(OUT/'matching_sessions.csv',index=False)
    pd.DataFrame(excluded,columns=['date','reason','missing_minutes']).to_csv(OUT/'excluded_sessions.csv',index=False)
    monthly=daily.groupby('month').agg(sessions=('date','size'),matches=('both_wicks_longer','sum'),dojis=('doji','sum'))
    monthly['percentage']=100*monthly.matches/monthly.sessions
    monthly.to_csv(OUT/'monthly.csv')
    non_doji=daily[~daily.doji]
    result={'requested_as_of':AS_OF,'available_from':daily.date.min(),'available_through':daily.date.max(),
            'source_last_local_date':last_local_date,'full_ytd_through_requested_date':last_local_date>=AS_OF,
            'eligible_cash_sessions':len(dates),'included_sessions':len(daily),'excluded_sessions':excluded,
            'matching_sessions':len(matches),'percentage':100*len(matches)/len(daily),
            'doji_sessions':int(daily.doji.sum()),'matching_doji_sessions':int(matches.doji.sum()),
            'excluding_dojis':{'sessions':len(non_doji),'matches':int(non_doji.both_wicks_longer.sum()),'percentage':100*non_doji.both_wicks_longer.mean()},
            'body_direction_of_matches':{k:int(v) for k,v in matches.body_direction.value_counts().items()},
            'monthly':monthly.reset_index().to_dict('records'),'matching_dates':matches.date.tolist(),
            'rule':definition['match'],'definition_sha256':sha(OUT/'definition.json'),
            'analysis_sha256':sha(Path(__file__)),'data_sha256':sha(source),'calendar_sha256':prior['calendar_sha256']}
    (OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
