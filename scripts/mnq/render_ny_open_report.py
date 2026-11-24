"""Render the frozen MNQ opening study into a portable PDF and HTML report.

Run --charts with the project Python, then run normally with the bundled PDF Python.
"""
from pathlib import Path
import base64
import html
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'reports/mnq-ny-open-2026-10-28'
PDF = ROOT / 'output/pdf/mnq-new-york-open-report.pdf'
S = json.loads((OUT / 'summary.json').read_text(encoding='utf-8'))


def pick(name, **filters):
    rows = [r for r in S[name] if all(r[k] == v for k, v in filters.items())]
    assert len(rows) == 1, (name, filters, len(rows))
    return rows[0]


def out(w, h, sample='all_nonflat', period='all'):
    return pick('outcome_summary', window=w, horizon=h, sample=sample, period=period)


def num(x, digits=1):
    return f'{x:,.{digits}f}'


def pct(x):
    return f'{x:.1f}%'


def pair(r, metric, digits=1):
    return f'{num(r[metric+"_mean"], digits)} / {num(r[metric+"_median"], digits)}'


if '--charts' in sys.argv:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10,
                         'axes.spines.top':False, 'axes.spines.right':False,
                         'axes.spines.left':False, 'axes.spines.bottom':False})
    fig, ax = plt.subplots(figsize=(8.1, 2.6))
    x = np.arange(3)
    for offset, period, color, label in [(-.19,'all','#1b3d53','May 2019 - Sep 2026'),(.19,'2024 onward','#198a80','Jan 2024 - Sep 2026')]:
        vals = [pick('opening_summary',period=period,window=w)['range_pts_median'] for w in [5,10,15]]
        bars=ax.bar(x+offset, vals, .34, color=color, label=label)
        for b,v in zip(bars,vals): ax.text(b.get_x()+b.get_width()/2, v+2, f'{v:g}',ha='center',fontsize=10)
    ax.set_xticks(x, ['First 5 min','First 10 min','First 15 min'])
    ax.set_ylabel('Median high-low range (points)')
    ax.set_ylim(0,115)
    ax.grid(axis='y', alpha=.12)
    ax.set_axisbelow(True)
    ax.legend(loc='upper left',ncol=2,frameon=False,fontsize=9)
    fig.tight_layout(pad=1)
    fig.savefig(OUT/'opening_ranges.png',dpi=180,bbox_inches='tight',facecolor='white')
    fig.savefig(OUT/'opening_ranges.svg',bbox_inches='tight',facecolor='white')
    plt.close(fig)
    print(OUT/'opening_ranges.png')
    raise SystemExit

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, KeepTogether
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader

NAVY = '#153549'
TEAL = '#187c73'
INK = '#263846'
MUTED = '#596c78'
PALE = '#edf5f4'
RULE = '#dce5e8'
PAGE_W, PAGE_H = 612, 792
WIDTH = 532

styles = {
    'title': ParagraphStyle('title',fontName='Helvetica-Bold',fontSize=25,leading=28,textColor=colors.HexColor(NAVY),spaceAfter=10),
    'sub': ParagraphStyle('sub',fontName='Helvetica',fontSize=10.3,leading=14,textColor=colors.HexColor(MUTED),spaceAfter=10),
    'h2': ParagraphStyle('h2',fontName='Helvetica-Bold',fontSize=12.5,leading=16,textColor=colors.HexColor(NAVY),spaceBefore=9,spaceAfter=6),
    'body': ParagraphStyle('body',fontName='Helvetica',fontSize=9.3,leading=13,textColor=colors.HexColor(INK),spaceAfter=7),
    'small': ParagraphStyle('small',fontName='Helvetica',fontSize=8,leading=11,textColor=colors.HexColor(MUTED),spaceAfter=6),
    'cell': ParagraphStyle('cell',fontName='Helvetica',fontSize=8.4,leading=11,textColor=colors.HexColor(INK)),
    'head': ParagraphStyle('head',fontName='Helvetica-Bold',fontSize=8.3,leading=10.5,textColor=colors.white),
    'note': ParagraphStyle('note',fontName='Helvetica-Bold',fontSize=10,leading=14,textColor=colors.HexColor(NAVY),spaceAfter=0),
}

pages=[]
current=None


def page(title, subtitle):
    global current
    current={'title':title,'subtitle':subtitle,'blocks':[]}
    pages.append(current)


def p(text, small=False):
    current['blocks'].append(('p',text,small))


def h(text):
    current['blocks'].append(('h',text))


def note(text):
    current['blocks'].append(('note',text))


def table(headers, rows, widths=None):
    current['blocks'].append(('table',headers,rows,widths))


def chart(path):
    current['blocks'].append(('chart',str(path)))


page('MNQ at the New York open',
     'Opening movement, reversal and continuation | Research report | October 28, 2026')
note('A return to the open is common across all openings. After a large directional push, it is much less reliable - and often comes after a further move against the fade.')
p('<b>Sample:</b> 1,841 complete cash sessions, May 6, 2019 through September 3, 2026. The opening reference is 9:30 a.m. Eastern (8:30 a.m. Chicago). No October 2026 price data is included.')
h('How much does price fluctuate?')
table(['Opening window','High-low range\nMean / median','Absolute net move\nMean / median','Range\n90th percentile'],[
    [f'{w} minutes',pair(r,'range_pts'),pair(r,'abs_net_pts'),num(r['range_pts_p90'])]
    for w in [5,10,15] for r in [pick('opening_summary',period='all',window=w)]
],[1.15,1.45,1.5,1.2])
p('All values above are index points. <b>Range</b> is the opening high minus low. <b>Absolute net move</b> is the distance from the 9:30 open to the completed window close. A wide range can still finish close to the open.', True)
chart(OUT/'opening_ranges.png')
h('What this means for the idea')
p('<b>For a clear directional push:</b> the two-hour return-to-open rate was 60.2% after 5 minutes, 51.5% after 10 minutes, and 41.7% after 15 minutes. Clean continuation occurred in 22.5%, 26.1%, and 27.0%, respectively. The definition of a directional push is fixed on page 3.')
p('<b>The evidence does not establish a blanket fade edge.</b> The competing-boundary comparison generally reached an equally sized extension first more often than it returned first. A trade decision still needs a defined entry, stop, target, costs, and an independent evaluation.')

page('Recovery versus continuation','All nonflat openings | One and two hours after each completed opening window')
h('What counts as recovery or continuation?')
p('Let <b>A</b> be the absolute opening net move. <b>Half recovery</b> retraces half of A toward the open. <b>Full recovery</b> returns to or passes the 9:30 opening price. <b>Equal extension</b> travels another A beyond the checkpoint in the original direction.')
p('<b>Clean continuation</b> reaches that equal extension, never gives back half of A, and finishes beyond the checkpoint in the original direction. It allows small pullbacks; it does not mean every minute moved the same way.')
table(['Window / limit','Sessions','Half\nrecovery','Full\nrecovery','Equal\nextension','Clean\ncontinuation'],[
    [f'{w}m / {horizon//60}h',f'{r["n"]:,}',pct(r['half_retrace_pct']),pct(r['full_retrace_pct']),pct(r['extension_pct']),pct(r['clean_continuation_pct'])]
    for w in [5,10,15] for horizon in [60,120] for r in [out(w,horizon)]
],[1.2,.75,1,1,1,1.15])
p('Percentages use every nonflat opening in the row. Full recovery and equal extension can both occur, so these columns do not add to 100%. Clean continuation is a subset of equal extension, not the opposite of recovery. Later pullbacks can disqualify a one-hour clean continuation at the two-hour deadline.', True)
h('When clean continuation happens, how far does it go?')
table(['Window / limit','Clean cases','Peak extra move\nMedian / P90','Move at deadline\nMedian / P90'],[
    [f'{w}m / {horizon//60}h',str(r['clean_continuation_n']),f'{num(r["clean_fade_adverse_pts_median"])} / {num(r["clean_fade_adverse_pts_p90"])}',f'{num(r["clean_continuation_fixed_end_markout_pts_median"])} / {num(r["clean_continuation_fixed_end_markout_pts_p90"])}']
    for w in [5,10,15] for horizon in [60,120] for r in [out(w,horizon)]
],[1.2,.85,1.7,1.7])
p('Distances are extra points from the checkpoint, in the original direction, among clean cases only. These are hindsight descriptions, not moves that can be assumed at entry.', True)
h('Your expiration limits')
table(['Opening window ends','One-hour expiry','Two-hour expiry'],[
    ['9:35 a.m.','10:35 a.m.','11:35 a.m.'],['9:40 a.m.','10:40 a.m.','11:40 a.m.'],['9:45 a.m.','10:45 a.m.','11:45 a.m.']
])
p('All times Eastern. Only bars before the stated expiry are included; no later recovery is credited.',True)

page('After a clear directional push','A fixed descriptive filter that more closely matches the proposed setup')
note('Directional push = at least 20 points from the open, with the net move at least 60% of the opening high-low range.')
p('This definition was fixed before scoring. It is an exploratory description of a pronounced push, not a tuned trading rule. A push up would be faded with a short; a push down would be faded with a long.')
table(['Window / limit','Cases','Half\nrecovery','Full recovery\n95% interval','Equal\nextension','Clean\ncontinuation'],[
    [f'{w}m / {horizon//60}h',str(r['n']),pct(r['half_retrace_pct']),f'{pct(r["full_retrace_pct"])}\n{r["full_retrace_ci95"][0]:.1f}-{r["full_retrace_ci95"][1]:.1f}%',pct(r['extension_pct']),pct(r['clean_continuation_pct'])]
    for w in [5,10,15] for horizon in [60,120] for r in [out(w,horizon,'directional_push')]
],[1.05,.65,.9,1.55,1,1.15])
p('The 95% intervals use a calendar-month cluster bootstrap. They describe sampling uncertainty, not a forecast or protection against data/regime changes.',True)
h('Upward and downward pushes are both included')
table(['Window / direction','Cases','Return within 1h','Return within 2h','Clean within 2h'],[
    [f'{w}m / {direction}',str(r2['n']),pct(r1['full_retrace_pct']),pct(r2['full_retrace_pct']),pct(r2['clean_continuation_pct'])]
    for w in [5,10,15] for direction in ['up','down']
    for r1 in [pick('direction_summary',period='all',sample='directional_push',window=w,horizon=60,direction=direction)]
    for r2 in [pick('direction_summary',period='all',sample='directional_push',window=w,horizon=120,direction=direction)]
],[1.4,.7,1.3,1.3,1.3])
h('The key difference from the all-opening result')
p('By the 15-minute checkpoint, a pronounced push returned to the opening price within two hours in only <b>41.7%</b> of cases. Across all nonflat 15-minute openings, the comparable rate was <b>66.0%</b>. The high overall recovery rate partly reflects small, easily retraced opening moves.')
p('Waiting longer produces a different setup and a different starting price. The 5-, 10-, and 15-minute rows reuse the same days and should not be treated as independent experiments.',True)

page('Which boundary is reached first?','Return to the open versus another equally sized extension')
p('At the checkpoint, the opening price is A points away in the fade direction. The extension boundary is A points away in the continuation direction. This compares equal distances. It is a price-path comparison, not a realized win rate or backtest.')
h('Directional pushes: first result within your limit')
table(['Window / limit','Recovery first','Extension first','Ambiguous','Neither reached'],[
    [f'{w}m / {horizon//60}h',pct(r['reversion_first_pct']),pct(r['extension_first_pct']),pct(r['ambiguous_pct']),pct(r['neither_pct'])]
    for w in [5,10,15] for horizon in [60,120] for r in [out(w,horizon,'directional_push')]
],[1.2,1.3,1.3,1.05,1.4])
p('Each row sums to 100% before rounding. The 15-minute, two-hour case was recovery-first on 37.1% of pushes, extension-first on 43.8%, with neither reached on 19.1%.',True)
h('Opening move size changes the recovery question')
table(['Initial net move\n(points)','5m cases','5m return\nwithin 2h','10m cases','10m return\nwithin 2h','15m cases','15m return\nwithin 2h'],[
    [b]+[v for w in [5,10,15] for r in [pick('size_summary',period='all',window=w,horizon=120,size_bin=b)] for v in [str(r['n']),pct(r['full_retrace_pct'])]]
    for b in ['0-<10','10-<20','20-<40','40-<80','80+']
],[1.2,.7,1.1,.7,1.1,.7,1.1])
p('These size bands include every nonflat opening, regardless of directional efficiency. They are not additional entry rules. A fixed point threshold represents different volatility conditions across years.',True)
h('Why intraminute ordering matters')
table(['All nonflat openings','Recovery first\nwithin 2h','Extension first\nwithin 2h','Ambiguous\nsame minute','Neither'],[
    [f'{w} minutes',pct(r['reversion_first_pct']),pct(r['extension_first_pct']),pct(r['ambiguous_pct']),pct(r['neither_pct'])]
    for w in [5,10,15] for r in [out(w,120)]
],[1.2,1.3,1.3,1.25,.8])
p('Small opening moves can put both boundaries inside a single minute. The bar open is checked first; otherwise an unknown within-minute order stays ambiguous. The clearer-push subset had no such ties. A gap past a level counts as reached or passed, not a verified fill.',True)

page('The risk while waiting for recovery','Directional pushes | Adverse points measured from the checkpoint')
note('An eventual recovery does not show how much adverse movement a fade had to withstand. Successful recoveries and failures need separate denominators.')
h('Among pushes that did return to the open')
table(['Window / limit','Recovered\ncases','Adverse before return\nMedian lower-upper','Adverse before return\nP90 lower-upper','Return time\nMedian min'],[
    [f'{w}m / {horizon//60}h',str(r['recovered_n']),f'{num(r["adverse_before_return_lower_pts_median"])}-{num(r["adverse_before_return_upper_pts_median"])}',f'{num(r["adverse_before_return_lower_pts_p90"])}-{num(r["adverse_before_return_upper_pts_p90"])}',num(r['return_minute_upper_median'])]
    for w in [5,10,15] for horizon in [60,120] for r in [out(w,horizon,'directional_push')]
],[1.1,.8,1.65,1.65,1.05])
p('Lower/upper values bound unknown ordering inside the recovery minute. They can coincide after aggregation. The lower bound includes prior bars and the recovery bar open; the upper also allows its adverse extreme unless the open already passed the recovery level. Return time is measured to the end of the first crossing minute.',True)
h('Among pushes that did not return before expiry')
table(['Window / limit','Failed\ncases','Maximum adverse move\nMedian / P90','All-push fixed-end fade\nMean / median points'],[
    [f'{w}m / {horizon//60}h',str(r['failed_n']),f'{num(r["failed_fade_adverse_pts_median"])} / {num(r["failed_fade_adverse_pts_p90"])}',pair(r,'fade_fixed_end_markout_pts')]
    for w in [5,10,15] for horizon in [60,120] for r in [out(w,horizon,'directional_push')]
],[1.15,.75,1.85,1.85])
p('<b>Read the last column separately:</b> it uses all directional pushes, not only failures. It is the signed price change from checkpoint to deadline for a hypothetical fade, without a target, stop, commissions, slippage, or an executable entry assumption. Negative values favor continuation over that fixed interval.',True)
h('Practical interpretation')
p('In the 5-minute setup, the two-hour nonrecoveries had a median adverse move of <b>117.8 points</b>; the 90th percentile was <b>253.7 points</b>. A 60.2% eventual recovery rate therefore cannot be read as a 60.2% profitable trade rate.')
p('One MNQ contract is $2 per index point: a 50-point move is $100 of price exposure before costs. The report does not prescribe a stop or position size. A defined exit policy is needed before translating these paths into strategy returns.',True)

page('The recent market is larger in points','January 2024 through September 3, 2026 | 671 complete sessions')
h('Recent opening ranges and net movement')
table(['Window','Range points\nMean / median','Absolute net points\nMean / median','Range median\nAll / recent bps'],[
    [f'{w} minutes',pair(r,'range_pts'),pair(r,'abs_net_pts'),f'{num(old["range_bps_median"])} / {num(r["range_bps_median"])}']
    for w in [5,10,15] for r in [pick('opening_summary',period='2024 onward',window=w)] for old in [pick('opening_summary',period='all',window=w)]
],[1.1,1.5,1.6,1.5])
p('The median 15-minute range rose from 72.8 points over the full sample to 94.0 points in 2024 onward. Relative to the opening index level, it fell from 46.9 to 41.1 basis points. One basis point is 0.01% of the opening price.',True)
h('Opening median range by year')
table(['Year','Sessions','First 5m','First 10m','First 15m'],[
    [str(year)+('*' if year in [2019,2026] else ''),str(r5['n']),num(r5['range_pts_median']),num(r10['range_pts_median']),num(r15['range_pts_median'])]
    for year in range(2019,2027)
    for r5 in [pick('yearly_opening',year=year,window=5)]
    for r10 in [pick('yearly_opening',year=year,window=10)]
    for r15 in [pick('yearly_opening',year=year,window=15)]
],[1,.9,1.1,1.1,1.1])
p('* Partial years: 2019 begins May 6; 2026 ends September 3. The 2026 median 15-minute range was 141.0 points. None of these figures is an estimate of the October 28 market.',True)
h('Recent directional pushes')
table(['Window','Cases','Return\nwithin 1h','Return\nwithin 2h','Clean\nwithin 2h','2h fade markout\nMean / median'],[
    [f'{w} minutes',str(r2['n']),pct(r1['full_retrace_pct']),pct(r2['full_retrace_pct']),pct(r2['clean_continuation_pct']),pair(r2,'fade_fixed_end_markout_pts')]
    for w in [5,10,15] for r1 in [out(w,60,'directional_push','2024 onward')] for r2 in [out(w,120,'directional_push','2024 onward')]
],[1,.65,1,1,1,1.5])
p('The recent directional-push results do not strengthen the blanket fade idea. These are overlapping descriptive views of already observed history, not fresh validation or a selected holdout.',True)

page('Definitions, checks and limits','Reproducible historical evidence | No strategy profitability claim')
h('Opening excursions in both directions')
table(['Window','Maximum rise from open\nMean / median points','Maximum fall from open\nMean / median points','Signed net move\nMean / median'],[
    [f'{w} minutes',pair(r,'up_excursion_pts'),pair(r,'down_excursion_pts'),pair(r,'net_pts')]
    for w in [5,10,15] for r in [pick('opening_summary',period='all',window=w)]
],[1,1.65,1.65,1.4])
p('The rise and fall are excursions within the same opening window; their medians need not sum to the median high-low range. Signed averages can cancel opposing moves, which is why the report emphasizes range and absolute net displacement.',True)
h('Sample and calculation checks')
p('<b>Data:</b> the registered, checksum-verified MNQ.v.0 continuous one-minute cache contains 2,585,941 rows. It is actual MNQ history beginning at the May 2019 launch, not earlier NQ history relabeled as MNQ. Original vendor request and acquisition receipt remain unverified.')
p('<b>Cash calendar:</b> 1,844 scheduled sessions were identified using exchange_calendars 4.13.2 XNYS, which correctly excludes the January 9, 2025 closure. Early-close sessions stay in the sample because every studied deadline is before 1 p.m. The same 1,841 complete sessions underlie each window.')
p('<b>Excluded:</b> March 9, 12, and 16, 2020 have 14, 13, and 14 missing minutes in the common window. No bars were filled. These disruption-day exclusions can understate tail risk. Futures trading on cash holidays is excluded.')
p('<b>Time and rolls:</b> timestamps label the start of each minute. The 5-minute window uses 9:30-9:34 bars; its future begins at 9:35. Daylight saving follows America/New_York. No contract switch occurs in an included 9:30-11:45 window. Intraday differences use unadjusted prices.')
p('<b>Verification:</b> synthetic paths checked direction symmetry, boundary ordering, gaps, ties and cutoff rules; sampled actual events were independently recomputed. All 5,523 opening records and 11,016 follow-up records reconciled. Flat openings remain in movement statistics but are excluded from directional outcomes.')
h('Uncertainty and what remains untested')
p('Reported intervals use 2,000 seeded calendar-month bootstrap samples and are pointwise, without multiple-comparison adjustment. The three windows overlap; no threshold was optimized and no period is presented as a fresh holdout. Future news, liquidity, execution, slippage, fees and trading halts are not simulated. A complete trade rule and subsequent independent evaluation are needed to test a tradable edge.')
h('Sources and supporting files')
p('<link href="https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html" color="#187c73">CME Group: MNQ contract specifications</link> - $2 per point; 0.25-point minimum tick ($0.50).<br/><link href="https://www.nyse.com/markets/hours-calendars" color="#187c73">NYSE: hours and holidays</link> - U.S. cash opening reference and session calendar.<br/><link href="https://databento.com/docs/schemas/ohlcv" color="#187c73">Databento: OHLCV schema</link> - bar-start timestamps and absent no-trade intervals.',True)
p('All result tables are computed from the local dataset. The companion folder includes the full event ledger, opening-session metrics, annual and size/direction summaries, excluded dates, frozen protocol, data manifest and machine-readable results. Dataset SHA-256 begins d75574620d4455b9; the full value is retained in summary.json.',True)


def para(s, style='body'):
    return Paragraph(s.replace('\n','<br/>'), styles[style])


def table_flow(headers, rows, widths):
    ws = [WIDTH/len(headers)]*len(headers) if widths is None else [WIDTH*w/sum(widths) for w in widths]
    data=[[para(html.escape(str(x)), 'head') for x in headers]]+[[para(html.escape(str(x)), 'cell') for x in row] for row in rows]
    t=Table(data,colWidths=ws,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor(NAVY)),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f1f5f6')]),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
        ('LINEBELOW',(0,-1),(-1,-1),.5,colors.HexColor(RULE)),
    ]))
    return t


def decorate(canvas,doc):
    canvas.setFillColor(colors.HexColor(TEAL))
    canvas.rect(40,756,32,4,fill=1,stroke=0)
    canvas.setFont('Helvetica-Bold',8)
    canvas.setFillColor(colors.HexColor(MUTED))
    canvas.drawString(80,756,'MNQ  /  NEW YORK OPEN')
    canvas.setStrokeColor(colors.HexColor(RULE))
    canvas.line(40,36,572,36)
    canvas.setFont('Helvetica',7)
    canvas.drawString(40,23,'Historical research | Data through September 3, 2026 | All times Eastern')
    canvas.drawRightString(572,23,f'{doc.page} / {len(pages)}')


story=[]
for i,page_data in enumerate(pages):
    if i: story.append(PageBreak())
    story += [para(page_data['title'],'title'),para(page_data['subtitle'],'sub')]
    for block in page_data['blocks']:
        kind=block[0]
        if kind=='p': story.append(para(block[1],'small' if block[2] else 'body'))
        elif kind=='h': story.append(para(block[1],'h2'))
        elif kind=='note':
            t=Table([[para(block[1],'note')]],colWidths=[WIDTH])
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor(PALE)),('BOX',(0,0),(-1,-1),.5,colors.HexColor('#cee4df')),('LEFTPADDING',(0,0),(-1,-1),11),('RIGHTPADDING',(0,0),(-1,-1),11),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
            story += [t,Spacer(1,9)]
        elif kind=='table': story += [table_flow(*block[1:]),Spacer(1,7)]
        elif kind=='chart':
            img=ImageReader(block[1]);iw,ih=img.getSize()
            story += [Image(block[1],width=WIDTH,height=WIDTH*ih/iw),Spacer(1,5)]

PDF.parent.mkdir(parents=True,exist_ok=True)
doc=SimpleDocTemplate(str(PDF),pagesize=(PAGE_W,PAGE_H),leftMargin=40,rightMargin=40,topMargin=50,bottomMargin=48,
                      title='MNQ New York Open: Movement, Recovery and Continuation',author='Strategy Workbench Research')
doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
reader=PdfReader(PDF)
assert len(reader.pages)==len(pages),f'Layout spilled to {len(reader.pages)} pages; expected {len(pages)}'


def webtext(s):
    import re
    s=re.sub(r'<link href="([^"]+)" color="[^"]+">',r'<a href="\1">',s)
    return s.replace('</link>','</a>').replace('\n','<br>')


sections=[]
for i,pg in enumerate(pages):
    parts=[f'<section id="section-{i+1}"><div class="eyebrow">{i+1:02d} / MNQ OPENING STUDY</div><h1>{pg["title"]}</h1><p class="subtitle">{pg["subtitle"]}</p>']
    for b in pg['blocks']:
        if b[0]=='p': parts.append(f'<p class="{"small" if b[2] else "body"}">{webtext(b[1])}</p>')
        elif b[0]=='h': parts.append(f'<h2>{b[1]}</h2>')
        elif b[0]=='note': parts.append(f'<aside>{b[1]}</aside>')
        elif b[0]=='chart':
            encoded=base64.b64encode(Path(b[1]).read_bytes()).decode()
            parts.append(f'<img class="chart" src="data:image/png;base64,{encoded}" alt="Opening median ranges: 48.5, 62.5 and 72.75 points across history; 62.5, 81.25 and 94 points from 2024 onward.">')
        elif b[0]=='table':
            heads=''.join(f'<th scope="col">{html.escape(str(x)).replace(chr(10),"<br>")}</th>' for x in b[1])
            rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(x)).replace(chr(10),"<br>")}</td>' for x in row)+'</tr>' for row in b[2])
            parts.append(f'<div class="table-wrap"><table><thead><tr>{heads}</tr></thead><tbody>{rows}</tbody></table></div>')
    parts.append('</section>')
    sections.append(''.join(parts))
nav=''.join(f'<a href="#section-{i+1}">{i+1}. {html.escape(pg["title"])}</a>' for i,pg in enumerate(pages))
html_doc='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MNQ New York Open Report</title><style>
:root{--navy:#153549;--teal:#187c73;--ink:#263846;--muted:#596c78;--rule:#dce5e8}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#edf2f4;color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}header{background:var(--navy);color:white;padding:25px max(25px,calc((100vw - 1200px)/2));display:flex;align-items:center;justify-content:space-between;gap:20px}header strong{font-size:19px}header span{font-size:13px;opacity:.8}button{border:1px solid #6d8d9d;background:transparent;color:white;padding:9px 16px;border-radius:6px;cursor:pointer}.layout{max-width:1200px;margin:28px auto;display:grid;grid-template-columns:235px 1fr;gap:24px;padding:0 20px}nav{position:sticky;top:22px;height:max-content;font-size:13px}nav a{display:block;padding:9px 11px;margin-bottom:5px;text-decoration:none;color:var(--navy);border-radius:5px}nav a:hover{background:#dbe8e9}nav .data-note{padding:14px 11px;color:var(--muted);font-size:12px;border-top:1px solid var(--rule);margin-top:14px}section{background:white;border:1px solid var(--rule);box-shadow:0 6px 18px #1c36400a;border-radius:10px;padding:36px;margin-bottom:24px;scroll-margin-top:20px}.eyebrow{font-size:11px;font-weight:750;letter-spacing:.12em;color:var(--teal)}h1{font-size:29px;line-height:1.2;color:var(--navy);margin:12px 0 14px}h2{font-size:18px;line-height:1.35;color:var(--navy);margin:25px 0 12px}.subtitle{font-size:13px;color:var(--muted);margin-bottom:24px}p{margin:12px 0}.small{font-size:12px;color:var(--muted);line-height:1.6}aside{background:#edf5f4;border-left:4px solid var(--teal);padding:18px 20px;font-weight:650;color:var(--navy);margin:19px 0}.table-wrap{overflow-x:auto;margin:13px 0}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:13px}th{background:var(--navy);color:white;text-align:left;font-size:12px;line-height:1.3;vertical-align:bottom}th,td{padding:12px 9px}td{vertical-align:top;border-bottom:1px solid var(--rule)}tr:nth-child(even) td{background:#f2f6f7}.chart{width:100%;height:auto}a{color:var(--teal)}footer{text-align:center;font-size:12px;color:var(--muted);padding:10px 20px 35px}@media(max-width:850px){.layout{display:block}nav{position:static;display:flex;overflow-x:auto;gap:8px;margin-bottom:20px}nav a{white-space:nowrap;background:#dfe9eb;font-size:12px}nav .data-note{display:none}section{padding:22px}h1{font-size:25px}header{padding:20px}header span{display:none}}@media print{body{background:white;font-size:10pt}header,nav,button,footer{display:none}.layout{display:block;margin:0;padding:0}section{box-shadow:none;border:0;border-radius:0;padding:0;break-after:page;margin:0}h1{font-size:22pt}h2{font-size:13pt}table{font-size:9pt}th,td{padding:6px}.small,.subtitle{font-size:8pt}aside{padding:9px}.chart{max-height:170px;object-fit:contain}@page{size:letter;margin:14mm}}
</style></head><body><header><div><strong>MNQ / New York Open</strong><br><span>Historical research • Updated October 28, 2026 • Data through September 3, 2026</span></div><button onclick="window.print()">Print report</button></header><div class="layout"><nav>'''+nav+'''<div class="data-note">1,841 complete sessions.<br>One and two hours after each checkpoint.<br>All times Eastern.<br>Prices in index points unless marked otherwise.</div></nav><main>'''+''.join(sections)+'''</main></div><footer>Descriptive historical research. All result tables are computed from the checksum-verified local MNQ dataset.</footer></body></html>'''
(OUT/'report.html').write_text(html_doc,encoding='utf-8')
print(json.dumps({'pdf':str(PDF),'pages':len(reader.pages),'html':str(OUT/'report.html')},indent=2))
