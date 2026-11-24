"""Actual first-minute-range chop examples; illustrative selection, not trades."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import textwrap

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'research/campaigns/mnq-opening-retracement-2026-10-28'
OUT=ROOT/'reports/mnq-first-candle-chop-2026-10-28'
spec=importlib.util.spec_from_file_location('prior_bounds',SOURCE/'analysis.py')
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
BG='#101a23'; PANEL='#16232e'; INK='#edf4f7'; MUTED='#9fb2c1'
GREEN='#38bd9f'; RED='#ed737b'; BLUE='#72b5fb'; GOLD='#ffc46b'
TITLES={'up':'Repeated low tests, then an upward break',
        'down':'Early bounces, then the first low gives way',
        'unresolved':'Repeated bounces; no two-close break by 09:45'}


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def tm(i): return f'09:{30+int(i):02d}' if i is not None else None


def describe(bars):
    low,high=float(bars[0,2]),float(bars[0,1]); width=high-low
    if width<10: return None
    mid=(low+high)/2; zone=low+.2*width
    decision=None; side='unresolved'; first_break_bar=None
    for i in range(2,15):
        a,b=bars[i-1,3],bars[i,3]
        if a>high and b>high: side='up'
        elif a<low and b<low: side='down'
        else: continue
        first_break_bar=i-1; decision=i+1; break
    end=first_break_bar if decision is not None else 15
    cycles=[]; i=1
    while i<end:
        # A bar spanning the lower fifth overlaps the illustrative area.
        # Requiring the midpoint in a LATER minute avoids guessing wick order.
        if bars[i,2]<=zone and bars[i,1]>=low:
            j=next((j for j in range(i+1,end) if bars[j,1]>=mid),None)
            if j is None: break
            cycles.append({'visit_index':i,'bounce_index':j,'visit_minute_et':tm(i),'bounce_minute_et':tm(j)})
            i=j+1
        else: i+=1
    if len(cycles)<2: return None
    held=None if side=='unresolved' else bool(np.all(bars[decision-1:,3]>high) if side=='up' else np.all(bars[decision-1:,3]<low))
    return {'first_low':low,'first_high':high,'first_range_points':width,
            'midpoint':mid,'lower_zone_low':low,'lower_zone_high':zone,
            'category':side,'decision_clock_index':decision,'decision_known_et':tm(decision),
            'outside_close_bar_indices':([] if decision is None else [decision-2,decision-1]),
            'cycles':cycles,'remaining_closes_stayed_outside':held}


def select_examples(sessions):
    groups={k:[] for k in TITLES}
    for date,bars in sessions.items():
        result=describe(bars)
        if result and (result['category']=='unresolved' or result['remaining_closes_stayed_outside']):
            groups[result['category']].append((date,result))
    choices=[]
    for side,rows in groups.items():
        eligible=[x for x in rows if len(x[1]['cycles'])>=3] if side=='unresolved' else rows
        if not eligible: eligible=rows
        assert eligible
        date,result=max(eligible,key=lambda x:x[0])
        choices.append((date,result))
    return choices,{k:len(v) for k,v in groups.items()}


def metadata(date,r):
    result={**r,'date':date,'id':f"{r['category']}-{date}",'title':TITLES[r['category']],
            'reference_candle':'09:30–09:31 ET','reference_known_et':'09:31',
            'first_candle_minutes':1,'illustrative_lower_zone_fraction':.2}
    key=result['id']; result.update(png=f'images/{key}.png',svg=f'images/{key}.svg',data_csv=f'data/{key}.csv')
    visits=', '.join(c['visit_minute_et'] for c in r['cycles'])
    bounces=', '.join(c['bounce_minute_et'] for c in r['cycles'])
    result['narrative']=f"Lower-zone visits: {visits}. The corresponding later midpoint reaches occur in the {bounces} minutes."
    result['break_note']=(f"Two closes {'above the first high' if r['category']=='up' else 'below the first low'} are known by {r['decision_known_et']}. Later closes also remain outside; that persistence is only known retrospectively."
                          if r['decision_known_et'] else 'No two consecutive closes outside the first-candle range occur before the 09:45 cutoff. That does not guarantee the next move stays in the range.')
    return result


def draw_panel(ax,info,bars,m,compact=False):
    fs=10 if compact else 12
    ax.set_facecolor(PANEL); ax.grid(axis='y',color='#31424d',lw=.65,alpha=.7,zorder=0)
    ax.axvspan(0,1,color=BLUE,alpha=.12,zorder=1)
    window_end=m['decision_clock_index'] or 15
    ax.fill_between([1,window_end],m['lower_zone_low'],m['lower_zone_high'],color=GREEN,alpha=.17,zorder=1)
    ax.hlines([m['first_low'],m['first_high']],1,15,color=BLUE,ls=(0,(5,3)),lw=1.3,zorder=2)
    ax.hlines(m['midpoint'],1,15,color=GOLD,ls=(0,(2,3)),lw=1.3,zorder=2)
    ax.axvline(1,color=BLUE,ls=':',lw=1)
    if m['decision_clock_index'] is not None:
        boundary=m['decision_clock_index']
        ax.axvspan(boundary,15,color=GOLD,alpha=.07,zorder=1)
        ax.axvline(boundary,color=GOLD,lw=1.4,zorder=2)
        label=f"2 closes {'above' if m['category']=='up' else 'below'}\nknown {tm(boundary)}"
        ax.text(boundary+.10,.94,label,transform=ax.get_xaxis_transform(),color=GOLD,fontsize=fs-2,va='top')
    for i,(o,h,l,c) in enumerate(bars):
        color=GREEN if c>=o else RED
        ax.vlines(i+.5,l,h,color=color,lw=1.6,zorder=3)
        if c==o: ax.hlines(o,i+.2,i+.8,color=color,lw=1.6,zorder=4)
        else: ax.add_patch(Rectangle((i+.2,min(o,c)),.6,abs(c-o),facecolor=color,edgecolor=GOLD if i==0 else color,lw=1.6 if i==0 else .8,zorder=4))
    for k,cycle in enumerate(m['cycles'],1):
        vi,bi=cycle['visit_index'],cycle['bounce_index']
        ax.axvspan(vi,vi+1,color=GREEN,alpha=.055,zorder=1)
        ax.plot([vi+.06,vi+.94],[.98,.98],transform=ax.get_xaxis_transform(),color=GREEN,lw=3)
        ax.text(vi+.5,.967,f'LOW {k}',transform=ax.get_xaxis_transform(),ha='center',va='top',color=GREEN,fontsize=fs-2,fontweight='bold')
        ax.plot([bi+.06,bi+.94],[.88,.88],transform=ax.get_xaxis_transform(),color=GOLD,lw=3)
        ax.text(bi+.5,.866,f'MID {k}',transform=ax.get_xaxis_transform(),ha='center',va='top',color=GOLD,fontsize=fs-2,fontweight='bold')
    ax.axvline(15,color=MUTED,lw=1)
    lo=min(bars[:,2]); hi=max(bars[:,1]); pad=max((hi-lo)*.24,10)
    ax.set_ylim(lo-pad*.18,hi+pad)
    ax.set_xlim(-.25,15.45)
    ax.set_xticks([0,3,6,9,12,15],['09:30','09:33','09:36','09:39','09:42','09:45'])
    ax.tick_params(axis='both',labelsize=fs-1,colors=INK,length=0,pad=7)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x,p:f'{x:,.0f}'))
    ax.yaxis.set_major_locator(MaxNLocator(7))
    ax.set_ylabel('MNQ price',color=MUTED,fontsize=fs-1,labelpad=8)
    ax.set_xlabel('New York time · one-minute candles',color=MUTED,fontsize=fs-1,labelpad=9)
    for spine in ax.spines.values(): spine.set_visible(False)
    info.axis('off'); info.text(0,.98,m['date'],color=INK,fontsize=fs+4,fontweight='bold',va='top')
    info.text(0,.87,'First candle: 09:30–09:31',color=BLUE,fontsize=fs,fontweight='bold')
    fields=[('First high',m['first_high'],BLUE),('Midpoint reference',m['midpoint'],GOLD),
            ('Lower-zone top',m['lower_zone_high'],GREEN),('First low',m['first_low'],BLUE)]
    y=.73
    for label,value,color in fields:
        info.text(0,y,label,color=color,fontsize=fs-1)
        info.text(.98,y,f'{value:,.2f}',color=color,fontsize=fs,fontweight='bold',ha='right')
        y-=.10
    info.text(0,.27,'LOW → MID pairs',color=INK,fontsize=fs,fontweight='bold')
    for k,cycle in enumerate(m['cycles']):
        info.text(0,.20-k*.075,f"{k+1}.  {cycle['visit_minute_et']}  →  {cycle['bounce_minute_et']}",color=MUTED,fontsize=fs)
    info.text(0,-.045,'Green zone = lower fifth of first range\nWhole-minute markers, not fills',color=MUTED,fontsize=fs-2,linespacing=1.6,va='top')


def single(bars,m):
    fig=plt.figure(figsize=(15,8.3),facecolor=BG)
    gs=fig.add_gridspec(1,2,left=.075,right=.965,bottom=.27,top=.79,width_ratios=[3.7,1.35],wspace=.14)
    fig.text(.075,.94,m['title'],color=INK,fontsize=23,fontweight='bold')
    fig.text(.075,.88,'Actual MNQ candles · first-candle low is the reference · later revisits show the pattern you described',color=MUTED,fontsize=12)
    draw_panel(fig.add_subplot(gs[0]),fig.add_subplot(gs[1]),bars,m)
    fig.text(.075,.145,'\n'.join(textwrap.wrap(m['narrative'],145)),color=INK,fontsize=11,va='top',linespacing=1.4)
    fig.text(.075,.086,'\n'.join(textwrap.wrap(m['break_note'],155)),color=MUTED,fontsize=10,va='top',linespacing=1.4)
    fig.text(.075,.018,'Reference levels are known at 09:31. Zone and two-close marker are illustration choices, not tested trading rules. No entry candle-close requirement is implied.',color=MUTED,fontsize=9)
    fig.savefig(OUT/m['png'],dpi=155,facecolor=BG);fig.savefig(OUT/m['svg'],facecolor=BG);plt.close(fig)


def overview(examples,sessions):
    fig=plt.figure(figsize=(15.5,17.4),facecolor=BG)
    gs=fig.add_gridspec(3,2,left=.075,right=.965,bottom=.115,top=.90,width_ratios=[3.7,1.35],wspace=.14,hspace=.44)
    fig.text(.075,.969,'Chop around the first candle’s low',color=INK,fontsize=28,fontweight='bold')
    fig.text(.075,.938,'Real MNQ sessions · first candle = 09:30–09:31 Eastern · later LOW → MID pairs are marked',color=MUTED,fontsize=12)
    for i,m in enumerate(examples):
        ax=fig.add_subplot(gs[i,0]);info=fig.add_subplot(gs[i,1])
        draw_panel(ax,info,sessions[m['date']],m,compact=True)
        ax.set_title(f"{i+1}. {m['title']}",loc='left',color=INK,fontsize=16,fontweight='bold',pad=17)
    fig.text(.075,.037,'These selected examples show the intended pattern, not a measured trading edge.\nThe first candle’s finished range is known only at 09:31. The later two-close break is an illustrative marker, not a validated decision rule.',color=MUTED,fontsize=10.5,linespacing=1.5)
    fig.savefig(OUT/'chop-overview.png',dpi=150,facecolor=BG);fig.savefig(OUT/'chop-overview.svg',facecolor=BG);plt.close(fig)


def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'data').mkdir(exist_ok=True);(OUT/'images').mkdir(exist_ok=True)
    protocol=json.loads((SOURCE/'protocol.json').read_text()); sessions,_,preview=prior.load_sessions(protocol)
    selected,counts=select_examples(sessions)
    examples=[]
    for date,r in selected:
        m=metadata(date,r);bars=sessions[date]
        frame=pd.DataFrame(bars,columns=['open','high','low','close'])
        frame.insert(0,'timestamp_et',pd.date_range(date+' 09:30',periods=15,freq='min',tz='America/New_York').map(lambda x:x.isoformat()))
        frame.to_csv(OUT/m['data_csv'],index=False);m['data_csv_sha256']=sha(OUT/m['data_csv'])
        single(bars,m); examples.append(m)
    overview(examples,sessions)
    result={'title':'First-candle low: real opening chop examples','date_created':'2026-10-28',
            'user_confirmed_reference':'First one-minute candle, 09:30–09:31 Eastern',
            'reference_known_et':'09:31','window':'09:30–09:44 observed bars; 09:45 cutoff',
            'overview_png':'chop-overview.png','overview_svg':'chop-overview.svg','examples':examples,
            'visual_selection':{'zone':'Bottom 20% of completed first-minute range; visual guide only.',
                                'cycle':'Observed bar overlaps lower zone; a strictly later bar reaches the midpoint with its high. The next cycle starts after that bounce bar.',
                                'break':'First two consecutive completed minute closes strictly above first high or below first low. Marker only becomes known at end of second candle.',
                                'sample_selection':'At least two cycles finish before either outside-close candle, first range >=10 points for visibility. Choose latest up/down example whose later closes remain outside. For unresolved, prefer >=3 cycles, then latest date. Future persistence is used only to choose clear historical illustrations.',
                                'eligible_counts_for_audit_only':counts},
            'data_source':{'path':protocol['data_path'],'sha256':protocol['data_sha256'],'complete_sessions':preview['included_sessions']},
            'limitations':['Not a backtest, trade ledger or frequency estimate. No proposed stop or executed entry is shown.',
                           'The first candle low is unavailable until 09:31; these are later revisits, not purchases at a hindsight first-candle low.',
                           'A later-minute midpoint reach proves a later price move, not an executable fill or a profitable trade.',
                           'The lower fifth and two-close marker are illustrative definitions, not user-approved or validated trading rules.',
                           'Chop and later persistence are selected in hindsight; they were not known at the first low test.',
                           'No entry waits for its current candle to close. A future break detector would need separate validation.',
                           'Midpoint and zone boundaries are mathematical references and can fall between tradable ticks.']}
    (OUT/'examples.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'selected':[{k:m[k] for k in ('date','category','cycles','decision_known_et')} for m in examples],'audit_counts':counts}))


if __name__=='__main__':main()
