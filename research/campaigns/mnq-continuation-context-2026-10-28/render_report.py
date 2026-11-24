"""Render the bounded continuation-context evidence and primary-source review.

Use project Python with --charts, then bundled PDF Python without arguments.
Requires completed contextual outputs; never estimates missing study results.
"""
from pathlib import Path
import csv
import html
import json
import math
import re
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'reports/mnq-continuation-context-2026-10-28'
PDF=ROOT/'output/pdf/mnq-continuation-research.pdf'

def read_csv(name):
    with (OUT/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def number(x):
    if x in ['',None]:return None
    value=float(x)
    return value if math.isfinite(value) else None
def yes(x):return x is True or str(x).lower() in ['true','1','1.0']
def num(x,digits=1):
    x=number(x)
    return 'n/a' if x is None else f'{x:,.{digits}f}'
def count(x):return num(x,0)
def percent(x):return 'n/a' if number(x) is None else num(x)+'%'
def bounds(r):
    if number(r['continuation_certain_pct']) is None:return 'n/a'
    return num(r['continuation_certain_pct'])+'-'+num(r['continuation_possible_pct'])+'%'
def contrast_bounds(r):
    if number(r['lower_difference_pp']) is None:return 'n/a'
    return f'{number(r["lower_difference_pp"]):+.1f} to {number(r["upper_difference_pp"]):+.1f}'
def one(rows,**filters):
    matches=[r for r in rows if all(str(r[k])==str(v) for k,v in filters.items())]
    assert len(matches)==1,(filters,len(matches))
    return matches[0]

needed=['context_summary.csv','baseline_summary.csv','fixed_contrasts.csv','yearly_ranges.csv','verification.json']
if not all((OUT/n).exists() for n in needed):
    raise SystemExit('Context outputs are not complete; no report generated.')
contexts=read_csv('context_summary.csv')
base=read_csv('baseline_summary.csv')
contrasts=read_csv('fixed_contrasts.csv')
years=read_csv('yearly_ranges.csv')
literature=json.loads((HERE/'literature.json').read_text(encoding='utf-8'))
verification=json.loads((OUT/'verification.json').read_text(encoding='utf-8'))
primary=[r for r in contexts if number(r['horizon_minutes'])==60 and r['barrier_definition']=='balanced_20']
assert len(primary)==36

if '--charts' in sys.argv:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    vals=[number(r['range_pts_median']) for r in years]
    labels=[str(r['year'])+('*' if yes(r['partial_year']) else '') for r in years]
    fig,ax=plt.subplots(figsize=(8.1,2.6))
    bars=ax.bar(labels,vals,color=['#153549']*(len(vals)-1)+['#187c73'],width=.63)
    for b,v in zip(bars,vals):
        ax.text(b.get_x()+b.get_width()/2,v+3,f'{v:.1f}',ha='center',fontsize=10)
    ax.set_ylabel('Median 15-minute high-low range\n(index points)',fontsize=9)
    ax.set_ylim(0,max(vals)*1.24)
    ax.tick_params(axis='both',labelsize=9,length=0)
    for s in ax.spines.values():s.set_visible(False)
    ax.set_axisbelow(True);ax.grid(axis='y',alpha=.13)
    fig.tight_layout(pad=.9)
    fig.savefig(OUT/'yearly_range_context.png',dpi=180,bbox_inches='tight',facecolor='white')
    fig.savefig(OUT/'yearly_range_context.svg',bbox_inches='tight',facecolor='white')
    plt.close(fig)
    print(OUT/'yearly_range_context.png')
    raise SystemExit

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,Image
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader
import base64

NAVY='#153549';TEAL='#187c73';INK='#263846';MUTED='#596c78';RULE='#dce5e8';WIDTH=532
styles={
 'title':ParagraphStyle('title',fontName='Helvetica-Bold',fontSize=23,leading=26,textColor=colors.HexColor(NAVY),spaceAfter=8),
 'sub':ParagraphStyle('sub',fontName='Helvetica',fontSize=9.8,leading=12.5,textColor=colors.HexColor(MUTED),spaceAfter=9),
 'h2':ParagraphStyle('h2',fontName='Helvetica-Bold',fontSize=12,leading=15,textColor=colors.HexColor(NAVY),spaceBefore=8,spaceAfter=5),
 'body':ParagraphStyle('body',fontName='Helvetica',fontSize=9.1,leading=12.4,textColor=colors.HexColor(INK),spaceAfter=6),
 'small':ParagraphStyle('small',fontName='Helvetica',fontSize=7.9,leading=10.5,textColor=colors.HexColor(MUTED),spaceAfter=6),
 'cell':ParagraphStyle('cell',fontName='Helvetica',fontSize=7.8,leading=10,textColor=colors.HexColor(INK)),
 'head':ParagraphStyle('head',fontName='Helvetica-Bold',fontSize=7.7,leading=9.7,textColor=colors.white),
 'note':ParagraphStyle('note',fontName='Helvetica-Bold',fontSize=9.8,leading=13.5,textColor=colors.HexColor(NAVY)),
}
pages=[];current=None
def page(title,subtitle):
    global current
    current={'title':title,'subtitle':subtitle,'blocks':[]};pages.append(current)
def p(text,small=False):current['blocks'].append(('p',text,small))
def h(text):current['blocks'].append(('h',text))
def note(text):current['blocks'].append(('note',text))
def table(headers,rows,widths=None):current['blocks'].append(('table',headers,rows,widths))
def chart(path):current['blocks'].append(('chart',str(path)))

FAMILIES={
 'hit_time': [('09:30-09:34','09:30-09:34'),('09:35-09:39','09:35-09:39'),('09:40-09:44','09:40-09:44')],
 'relative_stretch':[('below_0.75x','Below 0.75x'),('0.75_to_below_1.25x','0.75 to <1.25x'),('at_least_1.25x','At least 1.25x')],
}
passed={(r['threshold_points'],r['context_family'],r['context_bin']) for r in primary if yes(r['primary_two_period_majority_pass'])}
paired_sufficient=0
for d in [40,60,80]:
    for family,bins in FAMILIES.items():
        for label,_ in bins:
            pair=[one(primary,period=period,threshold_points=d,context_family=family,context_bin=label) for period in ['development','chronological_check']]
            paired_sufficient+=int(all(yes(r['sample_sufficient']) for r in pair))

page('MNQ continuation: testing the context','First touch during the New York open | Research update | October 28, 2026')
if not passed:
    note('No tested point-and-context combination supported a continuation-majority finding in both chronological periods. Neither the average opening range nor a larger point stretch establishes a reliable continuation threshold.')
else:
    note(f'{len(passed)} of 18 predeclared context combinations passed the two-period continuation-majority rule. These are descriptive associations, not an executable strategy or a universal point threshold.')
p('The question is specific: after the first 40-, 60- or 80-point move from the 9:30 cash open, reached before 9:45, does price travel <b>another 20 points in that direction before moving 20 points back</b>? The primary limit is one hour from the first-touch minute; two-hour and full-distance races are supplemental.')
h('Two contexts, both available without waiting for a close')
table(['Context','What is known at the first touch','Fixed comparison'],[
 ['Time to reach the level','The minute containing the first threshold hit','09:30-09:34 / 09:35-09:39 / 09:40-09:44'],
 ['Stretch relative to prior volatility','Trigger distance divided by the median 15-minute range of the previous 20 eligible sessions','Below 0.75x / 0.75 to <1.25x / at least 1.25x']
],[1.2,2.6,2.1])
p('The volatility reference excludes the current day and is available before 9:30. It does not use today\'s completed opening range, candle close or final-day volatility. The first 20 eligible sessions are warmup only for this context.',True)
h('A fixed point distance changes meaning across years')
chart(OUT/'yearly_range_context.png')
p('<b>The median opening 15-minute high-low range was 28.75 points in 2019 and 141.0 points in the available 2026 sample.</b> A range measures total fluctuation, not a predicted one-direction move. Annual values are retrospective context; the tested entry covariate uses only the previous 20 sessions.',True)
p('* Partial years: 2019 begins May 6; 2026 ends September 3. The sample contains 1,841 complete cash sessions and no October 2026 prices. The prior fade-strategy failures remain preserved; this research does not validate that strategy.',True)

page('All 18 predeclared context cells','Primary test: another 20 points versus a 20-point pullback, within one hour')
note('Ranges reflect uncertainty about the order of moves inside a minute.<br/>They are not confidence intervals. The "Order unclear" columns show how often the candle data cannot resolve the outcome.')
for family,bins in FAMILIES.items():
    h('Time of first touch' if family=='hit_time' else 'Trigger / previous-20-session median opening range')
    rows=[]
    for d in [40,60,80]:
        for label,display in bins:
            a=one(primary,period='development',threshold_points=d,context_family=family,context_bin=label)
            b=one(primary,period='chronological_check',threshold_points=d,context_family=family,context_bin=label)
            rows.append([str(d),display,count(a['n']),bounds(a),percent(a['outcome_ambiguous_pct']),count(b['n']),bounds(b),percent(b['outcome_ambiguous_pct'])])
    table(['Trigger','Context','2019-23\ncases','Continuation\nbounds','Order\nunclear','2024-26\ncases','Continuation\nbounds','Order\nunclear'],rows,[.55,1.25,.7,1.15,.7,.7,1.15,.7])
p(f'<b>{len(passed)} of 18 context combinations passed the two-period majority rule.</b> {paired_sufficient} of 18 had the required sample size in both periods. A claim required at least 100 events and 12 occupied months in each period, plus a multiplicity-adjusted lower bound for certain continuation above 50% in both periods.')
p('The adjustment covers 18 primary comparisons using a one-sided 0.05/18 threshold. Samples that are too small or have too many empty bootstrap draws do not qualify. Changing the amount of ordering ambiguity is not automatically a change in market behavior.',True)

page('Do faster or larger relative pushes differ?','Six fixed contrasts | Same one-hour, equal-20-point primary outcome')
p('These contrasts were specified before the new context outcomes: <b>early minus late touch</b>, and <b>large minus small relative stretch</b>, separately at 40, 60 and 80 points. The range of a difference is [certain A - possible B, possible A - certain B]. A range spanning zero does not identify which context has the higher rate.')
rows=[]
for family,label in [('hit_time','Early - late'),('relative_stretch','Large - small')]:
    for d in [40,60,80]:
        a=one(contrasts,period='development',threshold_points=d,context_family=family)
        b=one(contrasts,period='chronological_check',threshold_points=d,context_family=family)
        availability='Both' if yes(a['intervals_available']) and yes(b['intervals_available']) else '2019-23 only' if yes(a['intervals_available']) else '2024-26 only' if yes(b['intervals_available']) else 'Suppressed'
        rows.append([str(d),label,f'{count(a["A_n"])} / {count(a["B_n"])}',contrast_bounds(a),f'{count(b["A_n"])} / {count(b["B_n"])}',contrast_bounds(b),availability])
table(['Trigger','Contrast\nA - B','2019-23\ncases A / B','Difference\nbounds, pp','2024-26\ncases A / B','Difference\nbounds, pp','Sampling\nintervals'],rows,[.55,1,.95,1.35,.95,1.35,1])
p('Early = 09:30-09:34; late = 09:40-09:44. Large = at least 1.25x the prior range; small = below 0.75x. Certain means continuation under both ordering policies; possible means continuation under either. Differences are percentage points (pp), not percent returns. Intervals for each difference-bound endpoint are separate sampling statistics, retained in the full export. These contrasts have no additional selection or pass flag.',True)
h('Interpret the evidence at the correct level')
p('<b>Point stretch is not a turning point.</b> The tested levels are overlapping observations of the same days. The study does not estimate one average number where price should switch from reversal to continuation.')
p('<b>Volatility normalization remains a hypothesis.</b> The lagged range avoids using future information, but a causal input is not automatically a useful predictor. Upper possible-continuation bounds are not a basis for ranking or choosing a threshold.')
p('<b>Published momentum and reversal findings can coexist.</b> They study different instruments, opening gaps, time windows and return measures. A positive average late-day return does not establish an immediate-entry, equal-barrier success probability.')
h('What remains unresolved')
p('Minute OHLC does not reveal every trade\'s order. Finer trade-event data would reduce price-path ambiguity, while a separate, fixed execution model would still be required to test actual fills and costs. No paid market data was acquired for this study.')
p('The two periods are May 2019-December 2023 and January 2024-September 3, 2026. Both had already appeared in prior descriptive research; the later period is not a globally unseen holdout or prospective evidence.',True)

page('What the primary literature supports','Four source checks | Related evidence, not a validated MNQ point cutoff')
h('1. Opening information can predict a different part of the day')
p('<link href="https://www.sciencedirect.com/science/article/pii/S0304405X18301351" color="#187c73">Gao, Han, Li and Zhou (2018), Market intraday momentum</link> studies SPY and finds that the return from the <b>previous close through 10:00</b> predicts the 15:30-16:00 return. This includes overnight information and is known only at 10:00. It does not test a modern MNQ first-touch entry before 9:45 or the next one-to-two-hour equal-barrier race.')
h('2. An opening gap is different from a move after the open')
p('<link href="https://www.sciencedirect.com/science/article/abs/pii/S0378426604000949" color="#187c73">Grant, Wolf and Yu (2005), Intraday price reversals</link> examines older S&amp;P 500 futures and reports brief initial continuation after large opening gaps, followed by reversal. Cost adjustments weaken the trading evidence. A gap relative to yesterday\'s close is observable at the open, but it is a different predictor from today\'s post-9:30 stretch.')
h('3. A full-day volatility regime cannot filter an opening entry')
p('<link href="https://umu.diva-portal.org/smash/get/diva2%3A732318/FULLTEXT02.pdf" color="#187c73">Lundstrom, Day trading returns across volatility states</link> finds different historical opening-breakout returns across realized-volatility groups. The groups use the same day\'s open-to-close move, with its high-low range as a check. Both require hindsight at the open. This motivates testing lagged volatility context; it does not establish an available-at-open filter.')
h('4. A hindsight reversal percentage is not an immediate-entry win rate')
p('<link href="https://arxiv.org/abs/2605.11423v3" color="#187c73">Mesfin (2026), MNQ volatility-volume-gap classifier</link> is a preprint, not established as peer-reviewed. Its full opening feature is unavailable until 10:00. The reported reversal statistic uses repeated windows from 40 unique days and hindsight-selected peaks; all eight directional configurations fail its validation tests. It supplies no immediate-entry MNQ point cutoff.')
h('Local methodology and limitations')
p('The context analysis uses the saved first-touch events, source hashes and 1,841 complete MNQ cash sessions. It retains ambiguous and unresolved outcomes, all fixed cells, and the three missing-minute exclusions: March 9, 12 and 16, 2020. No bars are filled; removing disruption days can understate tail risk.')
p('Sampling intervals use 20,000 seeded calendar-month cluster draws, including zero-event months and shared resampling across related groups. Primary claims require sufficient samples in both periods and the specified 18-comparison adjustment. The original vendor request remains unverified, and the two context families are tested separately without new bins or intersections.')
p('The companion folder contains the frozen protocol, enriched events, complete context/contrast tables, annual range context, verification and literature memo. This is descriptive research: no new executable strategy, official workbench run, stage promotion or live-trading approval is claimed.',True)

def escape_amp(s):return re.sub(r'&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z][A-Za-z0-9]+;)','&amp;',s)
def para(s,style='body'):return Paragraph(escape_amp(s).replace('\n','<br/>'),styles[style])
def tab(headers,rows,widths):
    widths=[WIDTH/len(headers)]*len(headers) if widths is None else [WIDTH*w/sum(widths) for w in widths]
    vals=[[para(html.escape(str(x)),'head') for x in headers]]+[[para(html.escape(str(x)),'cell') for x in r] for r in rows]
    t=Table(vals,colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor(NAVY)),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f1f5f6')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),3.5),('BOTTOMPADDING',(0,0),(-1,-1),3.5),('LINEBELOW',(0,-1),(-1,-1),.5,colors.HexColor(RULE))]))
    return t
def decorate(c,d):
    c.setFillColor(colors.HexColor(TEAL));c.rect(40,756,32,4,fill=1,stroke=0)
    c.setFont('Helvetica-Bold',8);c.setFillColor(colors.HexColor(MUTED));c.drawString(80,756,'MNQ / CONTINUATION CONTEXT RESEARCH')
    c.setStrokeColor(colors.HexColor(RULE));c.line(40,36,572,36)
    c.setFont('Helvetica',7);c.drawString(40,23,'Descriptive historical research | Data through September 3, 2026 | All times Eastern')
    c.drawRightString(572,23,f'{d.page} / {len(pages)}')
story=[]
for i,pg in enumerate(pages):
    if i:story.append(PageBreak())
    story += [para(pg['title'],'title'),para(pg['subtitle'],'sub')]
    for b in pg['blocks']:
        if b[0]=='p':story.append(para(b[1],'small' if b[2] else 'body'))
        elif b[0]=='h':story.append(para(b[1],'h2'))
        elif b[0]=='table':story += [tab(*b[1:]),Spacer(1,7)]
        elif b[0]=='chart':
            iw,ih=ImageReader(b[1]).getSize()
            story += [Image(b[1],width=WIDTH,height=WIDTH*ih/iw),Spacer(1,5)]
        elif b[0]=='note':
            t=Table([[para(b[1],'note')]],colWidths=[WIDTH],hAlign='LEFT')
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#edf5f4')),('BOX',(0,0),(-1,-1),.5,colors.HexColor('#cee4df')),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9)]))
            story += [t,Spacer(1,8)]
PDF.parent.mkdir(parents=True,exist_ok=True)
doc=SimpleDocTemplate(str(PDF),pagesize=(612,792),leftMargin=34,rightMargin=34,topMargin=50,bottomMargin=48,title='MNQ Continuation Context Research',author='Strategy Workbench Research')
doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
reader=PdfReader(PDF)
assert len(reader.pages)==len(pages),f'Layout overflow: {len(reader.pages)} pages; expected {len(pages)}'

def webtext(s):
    s=re.sub(r'<link href="([^"]+)" color="[^"]+">',r'<a href="\1">',s)
    return escape_amp(s).replace('</link>','</a>').replace('\n','<br>')
sections=[]
for i,pg in enumerate(pages):
    parts=[f'<section id="section-{i+1}"><div class="eyebrow">{i+1:02d} / MNQ CONTINUATION RESEARCH</div><h1>{pg["title"]}</h1><p class="subtitle">{pg["subtitle"]}</p>']
    for b in pg['blocks']:
        if b[0]=='p':parts.append(f'<p class="{"small" if b[2] else "body"}">{webtext(b[1])}</p>')
        elif b[0]=='h':parts.append(f'<h2>{b[1]}</h2>')
        elif b[0]=='note':parts.append(f'<aside>{b[1]}</aside>')
        elif b[0]=='chart':
            encoded=base64.b64encode(Path(b[1]).read_bytes()).decode()
            parts.append(f'<img class="chart" src="data:image/png;base64,{encoded}" alt="Median opening fifteen-minute range by year, 2019 through the September 2026 sample.">')
        elif b[0]=='table':
            headers=''.join(f'<th scope="col">{html.escape(str(x)).replace(chr(10),"<br>")}</th>' for x in b[1])
            rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(x)).replace(chr(10),"<br>")}</td>' for x in row)+'</tr>' for row in b[2])
            parts.append(f'<div class="table-wrap"><table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div>')
    parts.append('</section>');sections.append(''.join(parts))
nav=''.join(f'<a href="#section-{i+1}">{i+1}. {html.escape(pg["title"])}</a>' for i,pg in enumerate(pages))
css='''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#edf2f4;color:#263846;font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}header{background:#153549;color:white;padding:25px max(25px,calc((100vw - 1240px)/2));display:flex;align-items:center;justify-content:space-between;gap:20px}header strong{font-size:19px}header span{font-size:13px;opacity:.8}button{border:1px solid #6d8d9d;background:transparent;color:white;padding:9px 16px;border-radius:6px;cursor:pointer}.layout{max-width:1240px;margin:28px auto;display:grid;grid-template-columns:230px minmax(0,1fr);gap:24px;padding:0 20px}nav{position:sticky;top:22px;height:max-content;font-size:13px}nav a{display:block;padding:9px 11px;margin-bottom:5px;text-decoration:none;color:#153549;border-radius:5px}nav a:hover{background:#dbe8e9}nav p{font-size:12px;color:#596c78;padding:12px}section{background:white;border:1px solid #dce5e8;box-shadow:0 6px 18px #1c36400a;border-radius:10px;padding:34px;margin-bottom:24px;scroll-margin-top:20px}.eyebrow{font-size:11px;font-weight:750;letter-spacing:.12em;color:#187c73}h1{font-size:29px;line-height:1.2;color:#153549;margin:12px 0 14px}h2{font-size:18px;line-height:1.35;color:#153549;margin:25px 0 12px}.subtitle{font-size:13px;color:#596c78;margin-bottom:24px}p{margin:12px 0}.small{font-size:12px;color:#596c78;line-height:1.6}aside{background:#edf5f4;border-left:4px solid #187c73;padding:18px 20px;font-weight:650;color:#153549;margin:19px 0}.table-wrap{overflow-x:auto;margin:13px 0}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:13px}th{background:#153549;color:white;text-align:left;font-size:12px;line-height:1.3;vertical-align:bottom}th,td{padding:9px 7px}td{vertical-align:top;border-bottom:1px solid #dce5e8}tr:nth-child(even) td{background:#f2f6f7}.chart{width:100%;height:auto}a{color:#187c73}footer{text-align:center;font-size:12px;color:#596c78;padding:10px 20px 35px}@media(max-width:850px){.layout{display:block}nav{position:static;display:flex;overflow-x:auto;gap:8px;margin-bottom:20px}nav a{white-space:nowrap;background:#dfe9eb;font-size:12px}nav p{display:none}section{padding:22px}h1{font-size:25px}header{padding:20px}header span{display:none}.table-wrap table{min-width:650px}}@media print{body{background:white;font-size:10pt}header,nav,button,footer{display:none}.layout{display:block;margin:0;padding:0}section{box-shadow:none;border:0;padding:0;break-after:page;margin:0}h1{font-size:22pt}h2{font-size:13pt}table{font-size:9pt}th,td{padding:5px}.small,.subtitle{font-size:8pt}aside{padding:9px}.chart{max-height:180px;object-fit:contain}@page{size:letter;margin:14mm}}'''
document='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MNQ Continuation Context Research</title><style>'+css+'</style></head><body><header><div><strong>MNQ / Continuation Context Research</strong><br><span>Time to first touch and prior volatility context | October 28, 2026</span></div><button onclick="window.print()">Print report</button></header><div class="layout"><nav>'+nav+'<p>18 fixed context cells.<br>Two chronological periods.<br>Four primary-source checks.<br>All times Eastern.</p></nav><main>'+''.join(sections)+'</main></div><footer>Descriptive historical research. Context associations do not establish an executable trading edge.</footer></body></html>'
(OUT/'report.html').write_text(document,encoding='utf-8')
print(json.dumps({'pdf':str(PDF),'pages':len(reader.pages),'html':str(OUT/'report.html'),'supported_context_cells':len(passed),'sufficient_pairs':paired_sufficient},indent=2))
