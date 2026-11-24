"""Render the frozen MNQ Keltner study: .venv --charts; bundled Python --pdf."""
from pathlib import Path
import argparse
import json
import math
from html import escape
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'artifacts/mnq-keltner-2026-10-26'
OUT = ROOT / 'reports/mnq-keltner-2026-10-26'
CHARTS = OUT / 'charts'
PDF = OUT / 'MNQ_Keltner_Statistical_Report.pdf'
LABELS = ['0-0.25', '0.25-0.5', '0.5-1', '1+']
COLORS = {'wick_only':'#167F82', 'close_outside':'#C76A4E'}
NAMES = {'wick_only':'Wick only', 'close_outside':'Close outside'}


def load():
    names = ['primary','size','session','side','year','horizon','cohort','trend']
    return {k:pd.read_csv(DATA / f'{k}_summary.csv') for k in names}


def pct(x, digits=1):
    return '-' if pd.isna(x) else f'{100*x:.{digits}f}%'


def num(x, digits=2):
    return '-' if pd.isna(x) else f'{x:.{digits}f}'


def integer(x):
    return '-' if pd.isna(x) else f'{int(x):,}'


def pp(x):
    return '-' if pd.isna(x) else f'{100*x:+.1f}'


def ci(lo, hi, scale=100):
    digits=1 if scale==100 else 3
    return '-' if pd.isna(lo) or pd.isna(hi) else f'{scale*lo:.{digits}f} to {scale*hi:.{digits}f}'


def truth(x):
    return x is True or str(x).lower()=='true'


def charts():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.titlesize':11,
                         'axes.labelsize':10,'axes.spines.top':False,'axes.spines.right':False,
                         'axes.edgecolor':'#C4CED6','axes.labelcolor':'#293D4C','text.color':'#172E40',
                         'xtick.color':'#52616C','ytick.color':'#52616C','grid.color':'#E5EBEF',
                         'savefig.facecolor':'white','figure.facecolor':'white'})
    CHARTS.mkdir(parents=True,exist_ok=True)
    t=load()

    def finish(fig,name):
        fig.savefig(CHARTS/name,dpi=180,bbox_inches='tight',pad_inches=.15)
        plt.close(fig)

    for tf in [5,15]:
        fig,axs=plt.subplots(1,2,figsize=(9.8,3.15),sharey=True,layout='constrained')
        for ax,typ in zip(axs,['wick_only','close_outside']):
            for split,col,ls in [('development','#A1ABB3',':'),('validation','#668C9D','--'),('test',COLORS[typ],'-')]:
                d=t['primary'][(t['primary'].timeframe==tf)&(t['primary'].type==typ)&(t['primary'].split==split)&(t['primary']['bin']!='all')].set_index('bin').reindex(LABELS)
                y=d.p_reversion.to_numpy(float)
                if split=='test':
                    low=np.maximum(0,y-d.p_ci_low.to_numpy(float)); high=np.maximum(0,d.p_ci_high.to_numpy(float)-y)
                    ax.errorbar(np.arange(4),y,yerr=[low,high],fmt='o-',color=col,capsize=3,lw=2,label='2025-2026 test')
                else:
                    ax.plot(np.arange(4),y,color=col,ls=ls,marker='.',lw=1.5,label=split.title())
            ax.axhline(.5,color='#8A99A4',lw=1)
            ax.set(xticks=np.arange(4),xticklabels=LABELS,title=NAMES[typ],xlabel='Extreme extension beyond channel (ATR)')
            ax.yaxis.set_major_formatter(PercentFormatter(1,decimals=0));ax.grid(axis='y',alpha=.6)
            ax.set_ylim(.25,.8)
        axs[0].set_ylabel('Reversion-first share of decisive events')
        axs[0].legend(fontsize=8,loc='lower left',frameon=False)
        finish(fig,f'primary_{tf}m.png')

    def anatomy_heat(feature,labels,name):
        fig,ax=plt.subplots(figsize=(9.4,2.8),layout='constrained')
        vals=[]; counts=[]; sufficient=[]; rlabels=[]
        for tf in [5,15]:
            for typ in ['wick_only','close_outside']:
                s=t['size'][(t['size'].timeframe==tf)&(t['size'].type==typ)&(t['size'].split=='test')&(t['size'].feature==feature)].set_index('bin').reindex(labels)
                vals.append(s.p_reversion.to_numpy(float));counts.append(s.decisive.to_numpy(float))
                sufficient.append(s.sufficient.map(truth).to_numpy(bool))
                rlabels.append(f'{tf}m | {NAMES[typ]}')
        vals=np.array(vals);counts=np.array(counts);sufficient=np.array(sufficient)
        cmap=plt.get_cmap('RdYlGn').copy();cmap.set_bad('#E8EDF1')
        ax.imshow(np.where(sufficient,vals,np.nan),aspect='auto',cmap=cmap,vmin=.35,vmax=.65)
        for i in range(4):
            for j in range(len(labels)):
                text='No events' if not np.isfinite(vals[i,j]) else f'{vals[i,j]*100:.1f}%\nn={int(counts[i,j]):,}'+(' (sparse)' if not sufficient[i,j] else '')
                ax.text(j,i,text,ha='center',va='center',fontsize=10,color='#193445')
        ax.set(xticks=np.arange(len(labels)),xticklabels=labels,yticks=np.arange(4),yticklabels=rlabels)
        ax.tick_params(length=0);ax.spines[['left','bottom']].set_visible(False)
        finish(fig,name)

    anatomy_heat('range_bin',['<1','1-1.5','1.5-2','2+'],'range_heat.png')
    anatomy_heat('outer_wick_bin',LABELS,'wick_heat.png')
    anatomy_heat('wick_fraction_bin',['<25%','25-50%','50-75%','75-100%'],'wick_fraction_heat.png')
    if 'wick_portion_outside_bin' in set(t['size'].feature):
        anatomy_heat('wick_portion_outside_bin',LABELS,'outside_wick_heat.png')

    fig,axs=plt.subplots(1,2,figsize=(9.8,3.15),sharey=True,layout='constrained')
    for ax,tf in zip(axs,[5,15]):
        for typ in ['wick_only','close_outside']:
            for barrier,ls in [(5,'-'),(10,'--')]:
                h=t['horizon'][(t['horizon'].timeframe==tf)&(t['horizon'].type==typ)&(t['horizon'].split=='test')&(t['horizon'].barrier.astype(int)==barrier)].sort_values('horizon')
                ax.plot(h.horizon,h.p_reversion,ls=ls,marker='o',color=COLORS[typ],label=f'{NAMES[typ]}, {barrier/10:g} ATR')
        ax.set(title=f'{tf}-minute signal candles',xticks=[15,60,120],xlabel='Outcome horizon (minutes)')
        ax.axhline(.5,color='#8A99A4',lw=1);ax.yaxis.set_major_formatter(PercentFormatter(1,decimals=0));ax.grid(axis='y',alpha=.6)
    axs[0].set_ylabel('Reversion-first share');axs[0].legend(fontsize=8,frameon=False)
    finish(fig,'horizons.png')

    fig,axs=plt.subplots(1,2,figsize=(9.8,3.2),sharey=True,layout='constrained')
    sessions=['overnight','opening','midday','afternoon','post_cash']
    for ax,tf in zip(axs,[5,15]):
        for k,typ in enumerate(['wick_only','close_outside']):
            s=t['session'][(t['session'].timeframe==tf)&(t['session'].type==typ)&(t['session'].split=='test')&(t['session'].horizon==60)].set_index('bin').reindex(sessions)
            y=s.p_reversion.to_numpy(float)
            ax.errorbar(np.arange(5)+(k-.5)*.12,y,yerr=[np.maximum(0,y-s.p_ci_low),np.maximum(0,s.p_ci_high-y)],fmt='o',capsize=3,color=COLORS[typ],label=NAMES[typ])
        ax.set(title=f'{tf}-minute candles',xticks=np.arange(5),xticklabels=['Overnight','Opening','Midday','Afternoon','Post-cash'])
        ax.tick_params(axis='x',rotation=25);ax.axhline(.5,color='#8A99A4',lw=1);ax.yaxis.set_major_formatter(PercentFormatter(1,decimals=0));ax.grid(axis='y',alpha=.6)
    axs[0].set_ylabel('Reversion-first share');axs[0].legend(fontsize=8,frameon=False)
    finish(fig,'sessions.png')

    fig,axs=plt.subplots(1,2,figsize=(9.8,3.2),sharey=True,layout='constrained')
    for ax,tf in zip(axs,[5,15]):
        for typ in ['wick_only','close_outside']:
            s=t['year'][(t['year'].timeframe==tf)&(t['year'].type==typ)].sort_values('year')
            ax.plot(s.year,s.p_reversion,marker='o',color=COLORS[typ],label=NAMES[typ])
        ax.set(title=f'{tf}-minute candles',xticks=list(range(2019,2027)))
        ax.tick_params(axis='x',rotation=45);ax.axhline(.5,color='#8A99A4',lw=1);ax.yaxis.set_major_formatter(PercentFormatter(1,decimals=0));ax.grid(axis='y',alpha=.6)
    axs[0].set_ylabel('Reversion-first share');axs[0].legend(fontsize=8,frameon=False)
    finish(fig,'years.png')

    # A deliberately numeric, schematic example, not a selected historical winner.
    fig,ax=plt.subplots(figsize=(9.4,2.8),layout='constrained')
    upper=100
    for x,o,c,h,l,label in [(0,95,98,108,92,'Wick-only example'),(2,96,105,111,94,'Close-outside example')]:
        ax.vlines(x,l,h,color='#223E50',lw=2)
        from matplotlib.patches import Rectangle
        ax.add_patch(Rectangle((x-.18,min(o,c)),.36,abs(c-o),facecolor='#B9DCD8',edgecolor='#167F82',lw=1.5))
        ax.text(x,l-2,label,ha='center',va='top',fontsize=10)
        ax.annotate('',(x+.4,h),(x+.4,upper),arrowprops={'arrowstyle':'<->','color':'#C76A4E'})
        ax.text(x+.48,(h+upper)/2,'Extreme\nextension',va='center',fontsize=9)
        ax.annotate('',(x-.4,h),(x-.4,max(o,c)),arrowprops={'arrowstyle':'<->','color':'#167F82'})
        ax.text(x-.48,(h+max(o,c))/2,'Full outer\nwick',ha='right',va='center',fontsize=9)
    ax.axhline(upper,color='#477A9A',lw=1.5,ls='--')
    ax.text(2.75,upper,'Upper channel',va='center',fontsize=10,color='#477A9A')
    ax.set(xlim=(-1.1,3.7),ylim=(87,114));ax.axis('off')
    finish(fig,'anatomy.png')
    print(f'Charts written to {CHARTS}')


def make_pdf():
    from reportlab.pdfgen import canvas
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,Image,KeepTogether
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.enums import TA_LEFT,TA_RIGHT
    from reportlab.lib.colors import HexColor,white
    from reportlab.lib.utils import ImageReader
    OUT.mkdir(parents=True,exist_ok=True)
    t=load(); result=json.loads((DATA/'statistical_result.json').read_text())
    p=t['primary']; primary=p[(p.split=='test')&(p['bin']!='all')]
    overview=p[(p.split=='test')&(p['bin']=='all')].sort_values(['timeframe','type'],ascending=[True,False])
    navy=HexColor('#17384D');teal=HexColor('#167F82');muted=HexColor('#607380');light=HexColor('#EDF4F6')
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ReportTitle',fontName='Helvetica-Bold',fontSize=27,leading=31,textColor=navy,spaceAfter=13))
    styles.add(ParagraphStyle(name='ReportSub',fontName='Helvetica',fontSize=12,leading=17,textColor=muted,spaceAfter=14))
    styles.add(ParagraphStyle(name='Section',fontName='Helvetica-Bold',fontSize=21,leading=25,textColor=navy,spaceAfter=12))
    styles.add(ParagraphStyle(name='Lead',fontName='Helvetica-Bold',fontSize=12,leading=17,textColor=navy,spaceAfter=10))
    styles.add(ParagraphStyle(name='BodyR',fontName='Helvetica',fontSize=9.5,leading=14,textColor=navy,spaceAfter=9))
    styles.add(ParagraphStyle(name='SmallR',fontName='Helvetica',fontSize=8,leading=11,textColor=muted,spaceAfter=7))
    styles.add(ParagraphStyle(name='CellR',fontName='Helvetica',fontSize=8.1,leading=10.5,textColor=navy))
    styles.add(ParagraphStyle(name='HeaderR',fontName='Helvetica-Bold',fontSize=8.1,leading=10.5,textColor=white))
    styles.add(ParagraphStyle(name='Eyebrow',fontName='Helvetica-Bold',fontSize=8.5,leading=11,textColor=teal,spaceAfter=10))
    story=[]
    def txt(s,style='BodyR'):
        return Paragraph(s,styles[style])
    def para(s,style='BodyR'):
        story.append(txt(s,style))
    def title(n,s,sub=None):
        if story:story.append(PageBreak())
        para(f'MNQ KELTNER STUDY  /  {n:02d}','Eyebrow');para(s,'Section')
        if sub:para(sub,'BodyR')
    def table(rows,widths=None,fs=8.1):
        cells=[]
        for i,row in enumerate(rows):
            cells.append([txt(str(c),'HeaderR' if i==0 else 'CellR') for c in row])
        tab=Table(cells,colWidths=widths,repeatRows=1,hAlign='LEFT')
        tab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),navy),('VALIGN',(0,0),(-1,-1),'TOP'),
                                 ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                                 ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
                                 ('ROWBACKGROUNDS',(0,1),(-1,-1),[white,light]),
                                 ('LINEBELOW',(0,0),(-1,0),.6,navy)]))
        story.append(tab);story.append(Spacer(1,10))
    def chart(name,maxh=245):
        path=CHARTS/name
        if not path.exists():return
        w,h=ImageReader(str(path)).getSize();rw=516;rh=rw*h/w
        if rh>maxh:rw*=maxh/rh;rh=maxh
        story.append(Image(str(path),width=rw,height=rh,hAlign='CENTER'));story.append(Spacer(1,9))
    def take(df,**kw):
        for k,v in kw.items():df=df[df[k]==v]
        return df
    def first(df):return df.iloc[0]

    para('RESEARCH REPORT  /  OCTOBER 26, 2026','Eyebrow')
    para('MNQ beyond the<br/>Keltner channel','ReportTitle')
    para('Candle range, wick size and extension depth<br/>5-minute and 15-minute bars across all sessions','ReportSub')
    claims=result['directional_claims'];supported=result['control_supported_directional_claims']
    headline='No confirmed extension sweet spot' if supported==0 else f'{supported} extension cells meet the frozen evidence rule'
    para(headline,'Lead')
    para(f'The fixed study tested 16 extension cells. {claims} met the directional rule across development, validation and test. The control comparison also failed an overlap diagnostic: removing contaminated pairs left no clear advantage. A higher conditional hit share does not establish profit after costs.')
    rows=[['Signal','Test decisive n','Reversion first','95% interval']]
    for _,r in overview.iterrows():rows.append([f'{r.timeframe}m {NAMES[r.type]}',integer(r.decisive),pct(r.p_reversion),ci(r.p_ci_low,r.p_ci_high)+'%'])
    table(rows,[146,99,115,156])
    para('What these percentages mean','Lead')
    para('After the candle closes, measure from the next minute\'s open. Does price travel 0.5 signal ATR back toward the channel before traveling 0.5 ATR farther away, within 60 minutes? The headline percentage includes only events with a clear first arrival. Unresolved, ambiguous and incomplete cases remain separately reported.')
    c5=first(take(overview,timeframe=5,type='close_outside'));c15=first(take(overview,timeframe=15,type='close_outside'))
    para(f'Channel return is common, but not an equal-distance edge. Close-outside signals reached or passed the frozen band within an hour in {pct(c5.band_return_60_rate)} of complete 5m cases and {pct(c15.band_return_60_rate)} of 15m cases. The symmetric reversion-first rates above remained close to 50%.','SmallR')
    h=first(take(t['horizon'],timeframe=5,type='wick_only',split='test',horizon=60)[lambda d:d.barrier.astype(int)==10])
    para(f'A secondary pattern is worth distinguishing: with wider 1-ATR barriers, 5m wick-only episodes continued first {pct(1-h.p_reversion)} of the time (95% interval {ci(1-h.p_ci_high,1-h.p_ci_low)}%, n={integer(h.decisive)}). This is horizon/distance sensitivity, not a validated candle-size sweet spot.','SmallR')
    para(f'Coverage: May 5, 2019 to September 3, 2026. The reserved test period is January 2025 onward. The ledger contains {integer(result["total_breach_bars"])} qualifying breach candles and {integer(result["episode_starts"])} fresh episode starts across both timeframes. These counts are observations, not independent trials.','SmallR')
    para('Sizing in this report means candle size and wick size. No account-size or position-sizing model is included.','SmallR')

    title(2,'Exactly what was measured')
    table([['Component','Definition'],['Center line','EMA of close, length 20'],['Channel width','2.25 x simple mean of the last 20 true ranges'],['ATR timing','Includes the completed signal candle; no open-bar signals'],['Wick-only event','High above upper band or low below lower band; close inside both bands. Open may be outside (a reclaimed close).'],['Close-outside event','Close strictly beyond one band'],['Fresh episode','Previous candle did not breach its own same-side band'],['Direction','Upper breach: reversion is down. Lower breach: reversion is up.']],[126,390])
    chart('anatomy.png',185)
    para('Extension and wick length are different measurements. Extreme extension is the distance from the band to the candle extreme. Full outer wick runs from the body to that extreme. On a close-outside candle, part of the extension can be body. The portion of wick outside the band is recorded separately.','SmallR')
    para('For an illustrative 20-point ATR, the extension buckets are 0-5, 5-10, 10-20 and 20+ points. A 1.5-ATR candle has a 30-point high-low range. The same number of points can mean very different sizes in quiet and volatile sessions.','SmallR')

    title(3,'Data, chronology and exclusions')
    table([['Item','Observed or declared'],['Data','2,585,941 actual MNQ minute bars; symbol MNQ.v.0'],['Coverage','2019-05-05 22:03 UTC through 2026-09-03 23:59 UTC'],['Contracts','30 instrument IDs; 29 roll transitions'],['Development','May 2019-December 2022'],['Validation','January 2023-December 2024'],['Test','January 2025-September 3, 2026'],['Cleanliness','No duplicate timestamps, invalid OHLC, nonfinite/off-tick prices or negative volume in independent audit'],['Gaps','5,913 gaps longer than one minute, including closures and no-trade minutes']],[123,393])
    para('Only completed, full signal candles qualify. Indicators use observed full-session chart bars, reset at each contract change, then warm up for 100 bars. Every forward horizon requires contiguous minute observations, the same contract and no split-boundary crossing. A valid short horizon is retained even when a longer horizon is incomplete.')
    rows=[['Test episode group','Eligible signals','Complete 60m','Incomplete','Ambiguous / unresolved']]
    for _,r in overview.iterrows():rows.append([f'{r.timeframe}m {NAMES[r.type]}',integer(r.events),integer(r.complete),integer(r.incomplete),f'{integer(r.ambiguous)} / {integer(r.unresolved)}'])
    table(rows,[140,83,87,77,129])
    para('Same-minute ambiguity is excluded from the headline denominator. Assigning every ambiguous event against or for reversion gives empirical bounds of '+ '; '.join(f'{r.timeframe}m {NAMES[r.type]}: {ci(r.ambiguity_bound_low,r.ambiguity_bound_high)}%' for _,r in overview.iterrows())+'. These bounds are not confidence intervals.','SmallR')
    para('Provenance limit: this is an existing local cache whose original vendor request and acquisition receipt were not reconstructed. Prices are continuous and unadjusted. Roll resets avoid gap-driven signals, but can differ from a continuously adjusted chart. No holiday-calendar completeness certification is made.','SmallR')
    para('The dataset has been used in other research. The later periods are held apart within this experiment; they are not certified globally unseen and are not prospective paper trading.','SmallR')

    for page,tf in [(4,5),(5,15)]:
        title(page,f'{tf}-minute candles: extension depth','Primary endpoint: 0.5 ATR in either direction, 60-minute horizon, fresh episode starts. The chart compares all three chronological periods; error bars show test-period 95% intervals.')
        chart(f'primary_{tf}m.png',218)
        rows=[['Type / ATR beyond band','Decisive n','Reversion','95% CI','Holm p','Rule']]
        for typ in ['wick_only','close_outside']:
            for label in LABELS:
                r=first(take(primary,timeframe=tf,type=typ,bin=label))
                label_status='Pass' if truth(r.directional_claim) else ('Sparse' if not truth(r.sufficient) else 'No pass')
                rows.append([f'{NAMES[typ]} | {label}',integer(r.decisive),pct(r.p_reversion),ci(r.p_ci_low,r.p_ci_high),num(r.holm_p,3),label_status])
        table(rows,[154,72,75,99,57,59])
        para('Rule: at least 100 decisive events on 50 distinct dates; same side of 50% in all three periods; test interval excludes 50%; Holm-adjusted p &lt; 0.05 across all 16 primary cells. A pass here still needs matched-control support before being called a supported extension cell.','SmallR')
        para('Bins include the left endpoint and exclude the right. "1+" means at least one ATR beyond the band. The test is conditional on a decisive first passage and does not show a trade win rate.','SmallR')
        if tf==15:
            r=first(take(primary,timeframe=15,type='close_outside',bin='1+'))
            para(f'The largest close-outside extensions show {pct(1-r.p_reversion)} continuation first (n={integer(r.decisive)}), but the adjusted p-value is {num(r.holm_p,3)}. That is an exploratory candidate, not a confirmed sweet spot.','SmallR')

    title(6,'Control comparison: a failed diagnostic','The original control rule used earlier nonbreach candles matched on timeframe, direction, session, pre-signal trend and volatility. Independent review found that some control outcome windows included the later selected breach candle itself.')
    para('Why the original comparison is contaminated','Lead')
    para('Selecting a later breach can select the price movement inside an earlier control window. That can mechanically make the control look more continuation-prone. The original positive reversion differences are retained in the exports but do not provide reliable corroboration.')
    diagnostic=pd.read_csv(DATA/'control_overlap_sensitivity.csv')
    diagnostic=diagnostic[diagnostic.split=='test']
    rows=[['Signal','Controls overlapping signal','Original difference (pp)','After exclusion (pp)','95% interval after exclusion']]
    for tf in [5,15]:
        for typ in ['wick_only','close_outside']:
            r=first(take(diagnostic,timeframe=tf,type=typ))
            rows.append([f'{tf}m {NAMES[typ]}',pct(r.overlap_rate),pp(r.original_difference),pp(r.nonoverlap_difference),ci(r.nonoverlap_difference_ci_low,r.nonoverlap_difference_ci_high)])
    table(rows,[124,94,99,92,107])
    para('Every overlap-excluded interval includes zero','Lead')
    para('This check removes overlapping pairs from the existing frozen matches, with no rematching or parameter change. Both arms must have decisive outcomes. It is a post-protocol diagnostic, not a new confirmation test, and its population differs from the original comparison.')
    rows=[['Signal','Remaining decisive pairs','Event reversion','Control reversion']]
    for _,r in diagnostic.iterrows():
        rows.append([f'{r.timeframe}m {NAMES[r.type]}',integer(r.nonoverlap_paired_decisive_n),pct(r.nonoverlap_event_reversion_rate),pct(r.nonoverlap_control_reversion_rate)])
    table(rows,[155,127,117,117])
    para('One shared draw resamples five-trading-day blocks. Event and control arms receive weights from their own original dates, so all copies of a reused control share the same weight. Positive differences favor reversion relative to the control. Matching still covers selected observed context only; it does not establish a causal effect.','SmallR')

    title(7,'Candle range and outer-wick size','Test-period fresh episodes. Each cell shows the conditional reversion-first percentage and decisive count. Gray cells fail the minimum 100 events / 50 dates rule. These secondary slices are exploratory.')
    para('Total candle range, in ATR','Lead');chart('range_heat.png',205)
    para('Full outer wick, in ATR','Lead');chart('wick_heat.png',205)
    para('The large candle and large wick bins do not isolate independent effects. Candle range, closing position, wick length and extension are correlated. A pattern in this page needs later confirmation rather than a new tuned filter on the same test data.','SmallR')

    title(8,'Wick proportions and interpretation','A wick-only event has already returned inside the channel before it is identified. That movement is not counted as a future successful reversion. All measured outcomes begin afterward.')
    para('Outer wick as a share of total candle range','Lead');chart('wick_fraction_heat.png',215)
    if (CHARTS/'outside_wick_heat.png').exists():
        para('Only the wick portion outside the channel, in ATR','Lead');chart('outside_wick_heat.png',215)
    else:
        rows=[['Signal','Median outer wick (ATR)','Median range (ATR)','Median extension (points)']]
        for _,r in overview.iterrows():rows.append([f'{r.timeframe}m {NAMES[r.type]}',num(r.outer_wick_atr_median),num(r.range_atr_median),num(r.extreme_extension_points_median)])
        table(rows,[145,123,123,125])
    para('How far the close itself is outside the channel','Lead')
    rows=[['Close-outside signal']+LABELS]
    for tf in [5,15]:
        cells=[]
        for label in LABELS:
            r=first(take(t['size'],timeframe=tf,split='test',type='close_outside',feature='close_extension_bin',bin=label))
            cells.append(f'{pct(r.p_reversion)}<br/>n={integer(r.decisive)}')
        rows.append([f'{tf}m']+cells)
    table(rows,[128,97,97,97,97])
    para('The main ATR includes the signal candle. An unusually large candle can widen its own channel and reduce its ATR-normalized size. The export includes an alternate size classification using the prior candle\'s ATR; it is a denominator sensitivity, not a different primary indicator.','SmallR')

    title(9,'Time and travel distance','A signal can behave differently over 15 minutes and two hours. The same elapsed-time horizons are used for both chart timeframes.')
    chart('horizons.png',215)
    rows=[['Signal','Barrier','15m reversion / n','60m reversion / n','120m reversion / n']]
    for tf in [5,15]:
        for typ in ['wick_only','close_outside']:
            for barrier in [5,10]:
                cells=[]
                for h in [15,60,120]:
                    r=first(take(t['horizon'],timeframe=tf,type=typ,split='test',horizon=h)[lambda d:d.barrier.astype(int)==barrier])
                    cells.append(f'{pct(r.p_reversion)} / {integer(r.decisive)}')
                rows.append([f'{tf}m {NAMES[typ]}',f'{barrier/10:g} ATR']+cells)
    table(rows,[124,62,110,110,110])
    para('The 5m wick-only 1-ATR result leans toward continuation, while the 0.5-ATR result is near even. Similar signs across overlapping horizons are not independent replications. This is a possible distance-dependent behavior to test later, not evidence for a particular wick-size filter.','SmallR')
    para('The denominator changes with horizon: a longer observation window can resolve more paths, but it can also be incomplete near maintenance breaks or missing data. Comparisons therefore use related, not perfectly identical, populations. Neither barrier setting includes spread, commission or an executable stop/target simulation.','SmallR')

    title(10,'Returns and actual travel','Signed returns are positive for continuation and negative for reversion. They measure the close 60 minutes after entry, regardless of which barrier was touched first.')
    rows=[['Signal','Mean return (ATR)','95% mean interval','Median','10th / 90th percentile']]
    for _,r in overview.iterrows():rows.append([f'{r.timeframe}m {NAMES[r.type]}',num(r.return_mean_atr),ci(r.return_mean_ci_low,r.return_mean_ci_high,1),num(r.return_median_atr),f'{num(r.return_p10_atr)} / {num(r.return_p90_atr)}'])
    table(rows,[141,94,111,65,105])
    rows=[['Signal','Mean points','Terminal reversion','Frozen EMA contact','Frozen band return']]
    for _,r in overview.iterrows():rows.append([f'{r.timeframe}m {NAMES[r.type]}',num(r.return_mean_points),pct(r.return_reversion_p),pct(r['ema_touch_60_rate']),pct(r['band_return_60_rate']) if r.type=='close_outside' else 'Not applicable'])
    table(rows,[141,78,99,99,99])
    para('Terminal reversion means the end-of-horizon price moved back toward the channel from the next open. Frozen-level contacts use the EMA or breached band at confirmation and count reach/pass, including a next-open gap or an entry price already beyond the level. They are not necessarily later traded touches. Wick-only band return is not applicable.')
    rows=[['Signal','Reversion excursion p50 / p90','Continuation excursion p50 / p90']]
    for _,r in overview.iterrows():
        a='mfe_reversion_atr_60';b='mfe_continuation_atr_60'
        rows.append([f'{r.timeframe}m {NAMES[r.type]}',f'{num(r.get(a+"_p50",np.nan))} / {num(r.get(a+"_p90",np.nan))}',f'{num(r.get(b+"_p50",np.nan))} / {num(r.get(b+"_p90",np.nan))}'])
    table(rows,[160,178,178])
    para('Excursions are maximum travel from entry in each direction during the full 60 minutes, in signal ATR units. Both directions may travel far within the same window. These are not stop-loss recommendations and do not determine the order of intraminute prices.','SmallR')

    title(11,'All sessions, shown separately','Session bucket follows the signal candle\'s opening time in America/Chicago. Indicators continue across the full trading session; they are not recalculated on a regular-hours-only chart.')
    chart('sessions.png',180)
    rows=[['Chicago bucket','Hours','5m wick / close n','15m wick / close n','60m completeness*']]
    defs=[('overnight','17:00-08:30'),('opening','08:30-10:00'),('midday','10:00-13:00'),('afternoon','13:00-15:00'),('post_cash','15:00-16:00')]
    for bucket,hours in defs:
        d=take(t['session'],split='test',bin=bucket,horizon=60);ns=[]
        for tf in [5,15]:
            a=take(d,timeframe=tf,type='wick_only');b=take(d,timeframe=tf,type='close_outside')
            ns.append(f'{integer(a.decisive.sum())} / {integer(b.decisive.sum())}')
        rate=d.complete.sum()/d.events.sum() if d.events.sum() else np.nan
        rows.append([bucket.replace('_',' ').title(),hours]+ns+[pct(rate)])
    table(rows,[96,91,113,113,103])
    para('* Completeness is all qualifying fresh episode signals with a full contiguous 60-minute future, pooled across both timeframes and event types. It is not a hit rate. The 16:00-17:00 maintenance break prevents a full 60-minute window for post-cash signals. Shorter-horizon descriptive results are retained where available.','SmallR')
    post=take(t['session'],split='test',bin='post_cash',horizon=15)
    para('Post-cash, 15-minute horizon: '+ '; '.join(f'{r.timeframe}m {NAMES[r.type]} {pct(r.p_reversion)} (n={integer(r.decisive)})' for _,r in post.iterrows())+'. These small samples are exploratory.','SmallR')

    title(12,'Stability and repeated breaches','Yearly percentages describe all available history. The first and final years are partial. The test years must not be treated as another opportunity to choose a winning rule.')
    chart('years.png',215)
    rows=[['Signal','Upper breach reversion / n','Lower breach reversion / n']]
    for tf in [5,15]:
        for typ in ['wick_only','close_outside']:
            vals=[]
            for side in [1,-1]:
                r=first(take(t['side'],timeframe=tf,type=typ,split='test')[lambda d:d['bin'].astype(int)==side])
                vals.append(f'{pct(r.p_reversion)} / {integer(r.decisive)}')
            rows.append([f'{tf}m {NAMES[typ]}']+vals)
    table(rows,[150,183,183])
    rows=[['Signal','Fresh episodes','All breach candles','First outside close']]
    for tf in [5,15]:
        for typ in ['wick_only','close_outside']:
            vals=[]
            for cohort in ['episode_start','all_bars','first_close']:
                d=take(t['cohort'],timeframe=tf,type=typ,split='test',cohort=cohort)
                vals.append('-' if d.empty else f'{pct(d.iloc[0].p_reversion)} (n={integer(d.iloc[0].decisive)})')
            rows.append([f'{tf}m {NAMES[typ]}']+vals)
    table(rows,[130,128,129,129])
    para('Successive candles outside a band are not independent new bets. A first outside close can occur after one or more wick breaches; it is a different cohort from the first excursion. Repeated-bar results are descriptive only.','SmallR')

    title(13,'Evidence limits and reproducibility')
    para('What this study can support','Lead')
    para('It estimates historical conditional price-path behavior for the exact indicator and declared candle anatomy. It distinguishes extension depth, wick size, total candle range, direction, session and horizon. It does not infer a universal optimal wick or prove that any entry/exit system earns money.')
    para('What remains uncertain','Lead')
    para('Minute OHLC cannot reconstruct the order of two prices reached inside the same minute. Missing-minute filters change session coverage. Nearby candles and two timeframes share prices. Five-day blocks do not prove independence over longer regimes. The original matched-control windows overlapped selected event movement; the labeled exclusion diagnostic found no clear advantage. Secondary slices have pointwise intervals without full search-wide correction. Original cache acquisition is not fully verified.')
    para('Frozen decision rule','Lead')
    para(f'{claims} of 16 primary cells met the chronology, sample, interval and multiplicity rule. The control diagnostic does not rescue a size claim. The study stops with that result. Any refined combination of range, wick, time and extension should be frozen and evaluated on genuinely new data.')
    table([['File group','Purpose'],['primary_summary.csv','All 16 size cells, all periods, uncertainty, Holm tests and controls'],['size / session / side / year summaries','Full marginal anatomy, session and stability tables'],['horizon / cohort / trend summaries','Travel distance/time, repeated-event and prebar-trend sensitivity'],['events_5m.csv.gz; events_15m.csv.gz','Complete event and control ledgers, including exclusions'],['protocol.json; build_events.py; analyze.py','Frozen design and reproducible research code'],['audit.json; statistical_result.json','Source/quality checks and statistical outcome record']],[202,314])
    para('Artifacts: artifacts/mnq-keltner-2026-10-26/<br/>Research source: research/campaigns/mnq-keltner-2026-10-26/','SmallR')
    para('Independent numerical QA reconstructed 359 sampled market candles and 2,154 first-passage classifications, plus 528 synthetic scalar checks. All reconciled. This is sampled verification, not an exhaustive second-engine replay.','SmallR')
    para('Primary references','Lead')
    para('<link href="https://www.adamhgrimes.com/indicators/" color="#167F82">Adam Grimes: Indicators</link> and <link href="https://www.adamhgrimes.com/reader-question-what-is-kpos/" color="#167F82">What is KPos?</link> describe the channel framework. This study follows the user-provided SMA-ATR formula exactly. <link href="https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html" color="#167F82">CME: MNQ specifications</link> confirms the instrument. All statistical findings come from the local frozen dataset, not these web references.','SmallR')

    def footer(c,doc):
        c.saveState();c.setStrokeColor(HexColor('#DCE6EB'));c.line(48,43,564,43)
        c.setFont('Helvetica',8);c.setFillColor(muted)
        c.drawString(48,29,'MNQ Keltner statistical study | Historical price behavior')
        c.drawRightString(564,29,str(doc.page));c.restoreState()
    doc=SimpleDocTemplate(str(PDF),pagesize=(612,792),rightMargin=48,leftMargin=48,topMargin=42,bottomMargin=57,
                          title='MNQ Keltner Channel Statistical Report',author='Strategy Workbench research',subject='Candle and wick size, reversion and continuation')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    print(PDF)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--charts',action='store_true');parser.add_argument('--pdf',action='store_true')
    args=parser.parse_args()
    if args.charts:charts()
    if args.pdf:make_pdf()
