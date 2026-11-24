"""Illustrate already-scored MNQ first-stretch events with actual minute bars."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'research/campaigns/mnq-opening-retracement-2026-10-28'
PRIOR = ROOT/'reports/mnq-opening-retracement-2026-10-28'
OUT = ROOT/'reports/mnq-opening-retracement-charts-2026-10-28'
SPEC = importlib.util.spec_from_file_location('opening_retracement', SOURCE/'analysis.py')
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)

INK = '#173544'
MUTED = '#647985'
TEAL = '#0c8478'
RED = '#cf4e57'
BLUE = '#306bc1'
CATS = {'retracement_first': 'Retracement before stop',
        'continuation_only': 'Stop reached; no 10-point retracement',
        'stop_then_retracement': 'Stop first, retracement later',
        'ambiguous': 'The candle order is unresolved'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def minute(i):
    return f'09:{30+int(i):02d}' if i is not None else None


def observed_hits(bars, row):
    idx = int(row.touch_minute_index)
    direction = 1 if row.first_direction == 'up' else -1
    origin = float(bars[0,0])
    signed = [analysis.signed_bar(bar,origin,direction) for bar in bars]
    target, stop = row.threshold_points-10, row.threshold_points*1.5
    # For the nine clear examples, the favorable extreme is absent in the
    # trigger candle. Thus these hit intervals cannot predate the trigger.
    t = next((i for i in range(idx,15) if signed[i][2] <= target),None)
    s = next((i for i in range(idx,15) if signed[i][1] >= stop),None)
    return t,s,signed[idx][2] > target


def select_examples(events,sessions):
    selected, counts = [], []
    for d in (40,60,80):
        group=events[(events.threshold_points==d)&(events.retracement_points==10)&events.triggered&~events.direction_ambiguous]
        for cat in ('retracement_first','continuation_only','stop_then_retracement'):
            if cat=='retracement_first': pool=group[group.retracement_first_certain==1]
            elif cat=='continuation_only': pool=group[(group.continuation_first_certain==1)&(group.any_retracement_possible==0)]
            else: pool=group[(group.continuation_first_certain==1)&(group.any_retracement_certain==1)]
            readable=[]
            for row in pool.itertuples():
                ti,si,clean=observed_hits(sessions[row.date],row)
                if row.touch_minute_index>0 and clean:
                    # Favor temporally separated outcome bars for explanation.
                    distinct=(ti is not None and ti>row.touch_minute_index and (si is None or ti<si)) if cat=='retracement_first' else (si is not None and si>row.touch_minute_index and (ti is None if cat=='continuation_only' else ti>si))
                    readable.append((row,ti,si,distinct))
            assert readable, (d,cat)
            choices=[x for x in readable if x[3]] or readable
            chosen=max(choices,key=lambda x:x[0].date)
            selected.append((cat,*chosen[:3]))
            counts.append({'distance':d,'category':cat,'known_direction_candidates':len(pool),
                           'readable_candidates':len(readable),'distinct_minute_candidates':sum(x[3] for x in readable),
                           'selected_date':chosen[0].date})
    ambiguous=events[(events.threshold_points==40)&(events.retracement_points==10)&events.triggered&~events.direction_ambiguous
                     &(events.touch_minute_index>0)&(events.any_retracement_certain==1)
                     &(events.retracement_first_possible==1)&(events.continuation_first_possible==1)]
    row=next(ambiguous.sort_values('date',ascending=False).itertuples())
    ti,si,_=observed_hits(sessions[row.date],row)
    selected.append(('ambiguous',row,ti,si))
    return selected,counts


def example_metadata(category,row,ti,si,bars):
    d=int(row.threshold_points); sign=1 if row.first_direction=='up' else -1
    origin=float(bars[0,0]); entry=origin+sign*d; stop=origin+sign*d*1.5
    targets={str(t):origin+sign*(d-t) for t in (5,10,15)}
    idx=int(row.touch_minute_index)
    key=f'd{d}-{category}-{row.date}'
    first_target=(ti if category!='ambiguous' else None)
    if category=='retracement_first':
        narrative=f"The {row.first_direction} stretch occurs in the {minute(idx)} minute. Price reaches the 10-point retracement in the {minute(ti)} minute before the stop level."
        if si is not None:
            narrative+=f" The stop level is only reached later, in the {minute(si)} minute."
    elif category=='continuation_only':
        narrative=f"The {row.first_direction} stretch occurs in the {minute(idx)} minute. The stop level is reached in the {minute(si)} minute, and the 10-point retracement never occurs before 09:45."
    elif category=='stop_then_retracement':
        narrative=f"The stop level is reached in the {minute(si)} minute; the 10-point retracement follows in the {minute(ti)} minute. That later retracement comes after the stop."
    else:
        narrative=f"A downward stretch occurs in the {minute(idx)} minute. A 10-point retracement before 09:45 is certain, but the candles do not establish whether it happened before the stop. The trigger candle's favorable extreme may be earlier than the trigger."
    return {'id':key,'date':row.date,'category':category,'title':CATS[category],
            'stretch_points':d,'stop_points':d/2,'classification_target_points':10,
            'first_direction':row.first_direction,'fade_side':'short' if sign==1 else 'long',
            'opening_price':origin,'stretch_level':entry,'stop_level':stop,'target_levels':targets,
            'trigger_minute_index':idx,'trigger_minute_et':minute(idx),
            'first_10pt_retracement_minute_index':first_target,'first_10pt_retracement_minute_et':minute(first_target),
            'first_stop_minute_index':si,'first_stop_minute_et':minute(si),
            'order_certain':category!='ambiguous','narrative':narrative,
            'png':f'images/{key}.png','svg':f'images/{key}.svg','data_csv':f'data/{key}.csv',
            'ledger_flags':{k:int(getattr(row,k)) for k in ('any_retracement_certain','any_retracement_possible','retracement_first_certain','retracement_first_possible','continuation_first_certain','continuation_first_possible')}}


def draw_panel(ax,info,bars,meta,*,compact=False):
    size=10 if compact else 12
    ax.set_facecolor('white')
    ax.grid(axis='y',color='#dce5e9',linewidth=.7,zorder=0)
    for i,(o,h,l,c) in enumerate(bars):
        color=TEAL if c>=o else RED
        ax.vlines(i+.5,l,h,color=color,linewidth=1.5,zorder=3)
        if c == o:
            ax.hlines(o,i+.20,i+.80,color=color,linewidth=1.6,zorder=4)
        else:
            ax.add_patch(Rectangle((i+.20,min(o,c)),.60,abs(c-o),facecolor=color,edgecolor=color,linewidth=.8,zorder=4))
    start=meta['trigger_minute_index']
    ax.axvspan(start,start+1,facecolor=BLUE,alpha=.09,zorder=1)
    ax.axhline(meta['opening_price'],color=MUTED,linestyle=(0,(2,3)),linewidth=1,zorder=2)
    ax.hlines(meta['stretch_level'],0,15,color=BLUE,linestyle=(0,(5,3)),linewidth=1.3,zorder=2)
    ax.hlines(meta['stop_level'],start,15,color=RED,linestyle=(0,(5,3)),linewidth=1.7,zorder=2)
    lo,hi=sorted((meta['target_levels']['5'],meta['target_levels']['15']))
    ax.fill_between([start,15],lo,hi,color=TEAL,alpha=.07,zorder=1)
    for t in ('5','10','15'):
        ax.hlines(meta['target_levels'][t],start,15,color=TEAL,
                  linewidth=1.8 if t=='10' else .9,linestyle='-' if t=='10' else (0,(2,3)),alpha=1 if t=='10' else .65,zorder=2)
    ax.axvline(15,color=INK,linewidth=1.4)
    # Small bands annotate whole observed minutes, never an invented event time.
    intervals=[(start,'STRETCH',BLUE)]
    if meta['order_certain']:
        ti,si=meta['first_10pt_retracement_minute_index'],meta['first_stop_minute_index']
        if ti is not None: intervals.append((ti,'10 PT',TEAL))
        if si is not None: intervals.append((si,'STOP',RED))
    for j,(idx,label,color) in enumerate(intervals):
        track=.975-.052*j
        ax.plot([idx+.05,idx+.95],[track,track],transform=ax.get_xaxis_transform(),color=color,linewidth=3,clip_on=False)
        ax.text(idx+.5,track-.012,label,transform=ax.get_xaxis_transform(),ha='center',va='top',fontsize=size-2,color=color,fontweight='bold')
    all_values=list(bars[:,1])+list(bars[:,2])+[meta['stop_level'],meta['opening_price'],*meta['target_levels'].values()]
    lo,hi=min(all_values),max(all_values); pad=max((hi-lo)*.17,8)
    ax.set_ylim(lo-pad*.4,hi+pad)
    ax.set_xlim(-.25,15.25)
    ax.set_xticks([0,3,6,9,12,15],['09:30','09:33','09:36','09:39','09:42','09:45'])
    ax.tick_params(axis='both',labelsize=size-1,length=0,pad=7,colors=INK)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x,pos:f'{x:,.0f}'))
    ax.yaxis.set_major_locator(MaxNLocator(7))
    ax.set_xlabel('New York time · each candle spans one minute',fontsize=size-1,color=MUTED,labelpad=10)
    ax.set_ylabel('MNQ price',fontsize=size-1,color=MUTED,labelpad=10)
    for s in ax.spines.values(): s.set_visible(False)
    info.axis('off')
    info.text(0,.97,meta['date'],fontsize=size+3,fontweight='bold',color=INK,va='top')
    info.text(0,.88,f"{meta['stretch_points']}-point stretch · {meta['fade_side'].upper()} fade",fontsize=size,color=BLUE,fontweight='bold')
    fields=[('9:30 open',meta['opening_price'],MUTED),('Stretch / nominal entry',meta['stretch_level'],BLUE),
            ('5-point retracement',meta['target_levels']['5'],TEAL),('10-point retracement',meta['target_levels']['10'],TEAL),
            ('15-point retracement',meta['target_levels']['15'],TEAL),(f"Stop · {meta['stop_points']:g} points",meta['stop_level'],RED)]
    y=.75
    for label,value,color in fields:
        info.text(0,y,label,fontsize=size-1,color=color,va='top')
        info.text(.97,y,f'{value:,.2f}',fontsize=size,color=color,fontweight='bold',ha='right',va='top')
        y-=.085
    info.text(0,.19,'Cutoff 09:45 ET',fontsize=size,fontweight='bold',color=INK)
    info.text(0,.10,'Blue band = trigger minute\nOutcome label uses 10-point target\nLevels are references, not verified fills',fontsize=size-2,color=MUTED,linespacing=1.6,va='top')


def render_single(bars,meta):
    fig=plt.figure(figsize=(14.6,7.6),facecolor='#f4f7f8')
    gs=fig.add_gridspec(1,2,left=.075,right=.965,bottom=.24,top=.79,width_ratios=[3.7,1.35],wspace=.13)
    fig.text(.075,.93,meta['title'],fontsize=23,fontweight='bold',color=INK)
    fig.text(.075,.87,f"MNQ · actual one-minute OHLC · {meta['stretch_points']}-point stretch / {meta['stop_points']:g}-point stop",fontsize=12,color=MUTED)
    draw_panel(fig.add_subplot(gs[0]),fig.add_subplot(gs[1]),bars,meta)
    # Keep narrative and provenance outside the plotting region.
    import textwrap
    fig.text(.075,.12,'\n'.join(textwrap.wrap(meta['narrative'],145)),fontsize=11,color=INK,linespacing=1.5,va='top')
    fig.text(.075,.025,'Observed 09:30–09:44 candles only. The 09:45 line marks the cutoff, not a price observation. Selected example, not a frequency estimate.',fontsize=9,color=MUTED)
    fig.savefig(OUT/meta['png'],dpi=160,facecolor=fig.get_facecolor())
    fig.savefig(OUT/meta['svg'],facecolor=fig.get_facecolor())
    plt.close(fig)


def render_overview(examples,sessions):
    chosen=[next(x for x in examples if x['stretch_points']==d and x['category']==cat) for d,cat in
            [(40,'retracement_first'),(60,'continuation_only'),(80,'stop_then_retracement')]]
    fig=plt.figure(figsize=(15.5,16.8),facecolor='#f4f7f8')
    gs=fig.add_gridspec(3,2,left=.075,right=.97,bottom=.115,top=.91,width_ratios=[3.7,1.35],wspace=.13,hspace=.42)
    fig.text(.075,.969,'Three real MNQ opening scenarios',fontsize=28,fontweight='bold',color=INK)
    fig.text(.075,.938,'10-point target determines the scenario · 5- and 15-point targets are also shown · all times Eastern',fontsize=12,color=MUTED)
    for j,meta in enumerate(chosen):
        ax=fig.add_subplot(gs[j,0]); info=fig.add_subplot(gs[j,1])
        draw_panel(ax,info,sessions[meta['date']],meta,compact=True)
        ax.set_title(f"{j+1}. {meta['title']}",loc='left',fontsize=17,fontweight='bold',color=INK,pad=15)
    fig.text(.075,.034,'Actual one-minute candles, not an invented price path. Nominal levels are not verified trade fills.\nThese selected examples explain sequence; the gallery includes every stretch size plus an uncertain-order example.',fontsize=11,color=MUTED,linespacing=1.5)
    fig.savefig(OUT/'scenario-overview.png',dpi=150,facecolor=fig.get_facecolor())
    fig.savefig(OUT/'scenario-overview.svg',facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'images').mkdir(exist_ok=True); (OUT/'data').mkdir(exist_ok=True)
    prior_review=json.loads((PRIOR/'independent_review.json').read_text())
    assert digest(SOURCE/'analysis.py')==prior_review['source_sha256']
    assert digest(SOURCE/'protocol.json')==prior_review['protocol_sha256']
    protocol=json.loads((SOURCE/'protocol.json').read_text())
    sessions,_,preview=analysis.load_sessions(protocol)
    events=pd.read_csv(PRIOR/'events.csv')
    selected,counts=select_examples(events,sessions)
    examples=[]
    for category,row,ti,si in selected:
        bars=sessions[row.date]
        independently_replayed=analysis.analyze_day(bars,int(row.threshold_points),10)
        for key in ('any_retracement_certain','any_retracement_possible','retracement_first_certain','continuation_first_certain'):
            assert independently_replayed[key]==int(getattr(row,key))
        meta=example_metadata(category,row,ti,si,bars)
        frame=pd.DataFrame(bars,columns=['open','high','low','close'])
        frame.insert(0,'timestamp_et',pd.date_range(row.date+' 09:30',periods=15,freq='min',tz='America/New_York').map(lambda t:t.isoformat()))
        frame.to_csv(OUT/meta['data_csv'],index=False)
        meta['data_csv_sha256']=digest(OUT/meta['data_csv'])
        render_single(bars,meta)
        examples.append(meta)
    render_overview(examples,sessions)
    result={'title':'MNQ opening retracements — real session charts','date_created':'2026-10-28',
            'classification_target_points':10,'reference_targets_points':[5,10,15],
            'selection_rule':'For each fixed stretch/category, choose the latest known-direction session with trigger after 09:30 and no 10-point favorable extreme in the trigger bar. Prefer separate trigger/outcome minutes when available. Add the latest known-direction D40 case with certain retracement but uncertain target/stop order.',
            'selection_counts':counts,'examples':examples,'overview_png':'scenario-overview.png',
            'data_source':{'path':protocol['data_path'],'sha256':protocol['data_sha256'],'event_ledger_sha256':digest(PRIOR/'events.csv'),
                           'source_analysis_sha256':digest(SOURCE/'analysis.py'),'complete_sessions':preview['included_sessions']},
            'limitations':['Selected illustrations, not a random sample or frequency estimate.','All outcome labels refer to the 10-point target only; other target lines are references.','Nominal stretch and stop levels are not verified execution prices.','Candles cover 09:30 through 09:44; 09:45 cutoff has no inferred price.','No second-by-second order is invented within a candle.','No trend filter or repeated-entry strategy is tested.']}
    (OUT/'examples.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'examples':[{k:e[k] for k in ('id','date','category','stretch_points','fade_side','trigger_minute_et','first_10pt_retracement_minute_et','first_stop_minute_et')} for e in examples],'selection_counts':counts}))


if __name__=='__main__': main()
