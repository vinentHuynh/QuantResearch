"""Render the smaller-target campaign and separate continuation event study."""
from pathlib import Path
import html
import json
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'reports/mnq-open-fade-small-targets-2026-10-28'
PDF=ROOT/'output/pdf/mnq-smaller-targets-and-continuation.pdf'
S=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
C=json.loads((OUT/'continuation_summary.json').read_text(encoding='utf-8'))

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak
from pypdf import PdfReader

NAVY='#153549';TEAL='#187c73';INK='#263846';MUTED='#596c78';RULE='#dce5e8';WIDTH=532
styles={
 'title':ParagraphStyle('title',fontName='Helvetica-Bold',fontSize=24,leading=27,textColor=colors.HexColor(NAVY),spaceAfter=9),
 'sub':ParagraphStyle('sub',fontName='Helvetica',fontSize=10,leading=13,textColor=colors.HexColor(MUTED),spaceAfter=10),
 'h2':ParagraphStyle('h2',fontName='Helvetica-Bold',fontSize=12.2,leading=15.5,textColor=colors.HexColor(NAVY),spaceBefore=9,spaceAfter=5),
 'body':ParagraphStyle('body',fontName='Helvetica',fontSize=9.2,leading=12.7,textColor=colors.HexColor(INK),spaceAfter=7),
 'small':ParagraphStyle('small',fontName='Helvetica',fontSize=8,leading=10.7,textColor=colors.HexColor(MUTED),spaceAfter=6),
 'cell':ParagraphStyle('cell',fontName='Helvetica',fontSize=8,leading=10,textColor=colors.HexColor(INK)),
 'head':ParagraphStyle('head',fontName='Helvetica-Bold',fontSize=7.9,leading=10,textColor=colors.white),
 'note':ParagraphStyle('note',fontName='Helvetica-Bold',fontSize=10,leading=14,textColor=colors.HexColor(NAVY)),
}
NAMES={'touch':'First touch','confirm':'Close back inside'}
SCENARIOS={'baseline':'Baseline','favorable_order':'Favorable-order bound','double_cost':'Doubled costs','entry_delay_1m':'Extra 1-minute delay'}
dev=[r for r in S['attempts'] if r['stage']=='development' and r['scenario']=='baseline']
assert len(dev)==48
assert all(r.get('prior_control_parity')=='passed' for r in dev if r['original_control'])
def num(x,digits=1):return 'n/a' if x is None else f'{x:,.{digits}f}'
def money(x,digits=0):return 'n/a' if x is None else ('-' if x<0 else '')+'$'+f'{abs(x):,.{digits}f}'
def pf(r):return 'n/a' if not r['trades'] else num(r['profit_factor'],3)
def pct(x):return num(x)+'%'
def one(rows,**filters):
    found=[r for r in rows if all(r[k]==v for k,v in filters.items())]
    assert len(found)==1,(filters,len(found))
    return found[0]
def case(mode,trigger,target,horizon=60):return one(dev,mode=mode,trigger=trigger,target=target,horizon=horizon)
def cont(d,h=120,barrier='balanced_20',period='all_2019_2026'):
    return one(C['summary'],threshold_points=d,horizon_minutes=h,barrier_definition=barrier,period=period)
def bounds(r):return f'{r["continuation_certain_pct"]:.1f}-{r["continuation_possible_pct"]:.1f}%'
def ci(r):
    return 'Suppressed: sparse' if r['continuation_certain_ci_low_pct'] is None else f'{r["continuation_certain_ci_low_pct"]:.1f}-{r["continuation_certain_ci_high_pct"]:.1f}%'

pages=[];current=None
def page(title,subtitle):
    global current
    current={'title':title,'subtitle':subtitle,'blocks':[]};pages.append(current)
def p(text,small=False):current['blocks'].append(('p',text,small))
def h(text):current['blocks'].append(('h',text))
def note(text):current['blocks'].append(('note',text))
def table(headers,rows,widths=None):current['blocks'].append(('table',headers,rows,widths))

page('Smaller targets helped - to a point','MNQ opening fades and continuation thresholds | October 28, 2026')
note('A 15-point target improved the confirmed 80-point fade in development. It passed the baseline 2024 test, but failed the frozen cost and delay stress hurdles. A 5-point target won more often and still lost money.')
p('<b>Strategy test:</b> 2019-2023 development, followed by 2024 evaluation for the selected confirmation case only. <b>Separate continuation study:</b> all available history, May 2019-September 3, 2026. The continuation study does not reopen failed strategy testing in later years.')
h('Same entry and stop; change only the target')
p('The clearest comparison uses the previously examined <b>80-point trigger, close-back-inside entry, 40-point stop and one-hour limit</b>. All four targets have the same 156 development trades. Figures include $2.24 per filled round trip on one MNQ contract.')
table(['Target','Net win rate','Approx.\nbreak-even','Mean / trade','Net profit','Profit factor'],[
 [f'{t:g} pts'+(' *' if t==40 else ''),pct(r['win_pct']),pct(r['two_exit_breakeven_win_pct']),money(r['expectancy_dollars'],2),money(r['net_profit'],2),pf(r)]
 for t in [5,10,15,40] for r in [case('confirm',80,t)]
],[.8,1,1.05,1.1,1.15,1])
p('* Original target control. The 15-point case improved net profit by $455.00 versus the original 40-point target. Its one- and two-hour development results were identical; the frozen tie-break selected one hour. These results are not an independent validation.',True)
h('Why 90% winners can still lose')
p('A 5-point target on one MNQ earns $10 gross, or <b>$7.76 after modeled costs</b>. A full 40-point stop loses <b>$82.24</b> including costs. About 10.6 full winners are needed to offset one full stop. The required binary win rate is 91.38%, above the observed 90.38%.')
table(['Trigger / stop','5-point target','10-point target','15-point target','Original target'],[
 [f'{d} / {d//2} pts',pct((d/2+1.12)/(d/2+5)*100),pct((d/2+1.12)/(d/2+10)*100),pct((d/2+1.12)/(d/2+15)*100),pct((d/2+1.12)/d*100)]
 for d in [40,60,80]
],[1.25,1.1,1.15,1.15,1.15])
p('Approximate break-even win rates = (stop points + 1.12 cost points) / (stop points + target points). This arithmetic assumes only full targets and full stops; actual time exits and gaps can change the required rate.',True)
h('Is there a point where continuation becomes more likely?')
p('No tested threshold from <b>40 to 160 points</b> established a reliable continuation-majority flag. Minute-order ambiguity is substantial for the next 20-point move, and the larger-distance comparison does not show continuation probability rising steadily with the opening displacement. Details are on pages 5-6.')

for mode in ['touch','confirm']:
    rows=sorted([r for r in dev if r['mode']==mode],key=lambda r:(r['trigger'],r['target'],r['horizon']))
    eligible=sum(bool(r['eligible']) for r in rows)
    page(f'Development: {NAMES[mode].lower()}',
         'May 6, 2019 - December 31, 2023 | One MNQ | Conservative ordering | All 24 cases')
    p(f'<b>{eligible} of 24 cases met eligibility.</b> The unchanged hurdle is at least 150 trades, positive net profit and profit factor of at least 1.10. Stops remain 20/30/40 points for the 40/60/80-point triggers. Asterisks identify the original target controls.')
    table(['Trigger /\nstop pts','Target\npts','Hold','Trades','Net\nwin %','Mean /\ntrade','Net\nprofit','Profit\nfactor','Closed\ndrawdown'],[
      [f'{r["trigger"]} / {r["stop"]:g}',f'{r["target"]:g}'+('*' if r['original_control'] else ''),f'{r["horizon"]//60}h',str(r['trades']),num(r['win_pct']),money(r['expectancy_dollars'],2),money(r['net_profit']),pf(r),money(r['max_daily_closed_drawdown'])]
      for r in rows
    ],[1.05,.7,.55,.7,.75,.95,1,.8,1.05])
    p('Drawdown uses daily closed equity, not unrealized intratrade risk. Net win rate counts trades profitable after costs; it is not the frequency of an eventual recovery. The full exported attempts file also retains every favorable-order sensitivity result.',True)
    if mode=='touch':
        p('No first-touch case qualified. Minute OHLC does not reliably place a small favorable excursion before or after threshold entry; favorable-order results can differ sharply. Failure of the conservative screen is not proof that every feasible tick path loses.',True)
    else:
        p('Only the 80-point trigger with a 15-point target qualified, at both holding limits. Equal development results selected the shorter one-hour limit. No smaller target or different stop was introduced after seeing 2024 results.',True)

page('2024 exposed the fragility','Selected on earlier data: confirmed 80-point trigger / 15-point target / 40-point stop / one hour')
note('The selected strategy remained slightly profitable under both stresses, but missed the predeclared profit-factor requirement. This is a failed robustness gate, not a claim that every stress scenario lost money.')
evals=[r for r in S['attempts'] if r['stage']=='evaluation_2024']
table(['2024 scenario','Trades','Net\nwin rate','Mean /\ntrade','Net profit','Profit\nfactor','Closed\ndrawdown','Gate'],[
 [SCENARIOS[r['scenario']],str(r['trades']),pct(r['win_pct']),money(r['expectancy_dollars'],2),money(r['net_profit'],2),pf(r),money(r['max_daily_closed_drawdown'],2),'Bound' if r['scenario']=='favorable_order' else 'Fail' if r.get('evaluation_failures') else 'Pass']
 for r in evals
],[1.6,.55,.75,.8,.95,.75,1.0,.55])
p('Each required scenario needed at least 30 trades, positive net profit and profit factor of at least 1.05. Baseline passed. Doubled costs reached 1.041 and an extra minute of entry delay reached 1.013, so both failed the profit-factor hurdle. The favorable-order result equals baseline for this configuration.',True)
h('The progression stops here')
table(['Entry style','Development','Later strategy evaluation','Disposition'],[
 ['First touch','No eligible case','Not run','Stopped at development'],
 ['Close back inside','80 / 15 / 40 / 1h selected','2024 baseline passed; stress failed','Stopped after 2024']
],[1.1,1.6,1.8,1.4])
p('<b>Not run:</b> 2025 or 2026 strategy folds, expanding reselection after 2024, nearby-target/trigger robustness, or prospective paper trading. The prior original-target failures remain preserved; this is the separately authorized smaller-target extension.')
h('How the selected case behaved by year')
selected=[r for r in S['yearly_breakdown'] if r['mode']=='confirm' and r['trigger']==80 and r['target']==15 and r['horizon']==60]
table(['Year','Role','Trades','Net profit','Mean / trade','Profit factor'],[
 [str(r['year']), 'Evaluation' if r['year']==2024 else 'Development',str(r['trades']),money(r['net_profit'],2),money(r['expectancy_dollars'],2),pf(r)]
 for r in selected
],[.65,1.2,.65,1.1,1.1,1])
p('Most development profit came from 2020 and 2021. The 2022 and 2023 margins were thin before the separate 2024 stress test. Annual breakdowns are descriptive, not additional selection tests.',True)
h('Research status')
p('The 15-point target is the strongest candidate from this bounded extension. It has not passed the required cost and timing checks; later-year strategy performance remains untested.')

page('Continuation after the first threshold','Separate descriptive study | May 6, 2019 - September 3, 2026 | 1,841 complete sessions')
note('The ranges below are feasible minute-order bounds, NOT confidence intervals. The lower endpoint is continuation certain under both ordering policies; the upper endpoint includes cases where continuation could have occurred first.')
p('For each threshold, find the first move that reaches it during 9:30-9:44. From that level, compare <b>another 20 points in the same direction</b> with <b>20 points back</b>. For an 80-point upward push from 20,000, the race starts at 20,080: 20,100 versus 20,060. The first direction stays locked.')
table(['First displacement','Hit sessions','Share of\ncash sessions','Continuation first\nwithin 1h','Continuation first\nwithin 2h','Ambiguous\nwithin 2h'],[
 [f'{d} pts',str(r2['n']),pct(r2['threshold_reached_pct']),bounds(r1),bounds(r2),pct(r2['outcome_ambiguous_pct'])]
 for d in [40,60,80,100,120,160] for r1 in [cont(d,60)] for r2 in [cont(d,120)]
],[1.1,.8,1.05,1.5,1.5,1])
p('Every threshold-hit session remains in the denominator, including ambiguous and unresolved outcomes. Threshold cohorts overlap. These are first-touch events, not the earlier report\'s completed 5-, 10-, or 15-minute opening-window cohorts.',True)
h('Statistical uncertainty is separate from the path bounds')
table(['Threshold','Certain continuation\nwithin 2h','95% sampling interval\nfor that certain rate','Continuation-majority\nflag'],[
 [f'{d} pts',pct(r['continuation_certain_pct']),ci(r),'No'+(' - sparse' if r['sparse_evidence'] else '')]
 for d in [40,60,80,100,120,160] for r in [cont(d)]
],[.9,1.5,1.8,1.5])
p('The fixed majority rule required at least 100 events, at least 10 occupied months, and the 95% lower interval for certain continuation above 50%. No level met it. The 160-point cohort has only 71 events, so its sampling interval is suppressed.',True)
h('What can and cannot be concluded')
p('These data do not identify a reliable point at which a further 20-point continuation becomes more likely than a 20-point pullback. Wide bounds, especially at large thresholds, prevent a precise probability claim. A failed majority flag also does not establish a profitable fade: costs, target/stop asymmetry and execution still matter.')

page('Larger moves do not give a clean cutoff','Double the opening displacement versus return to the cash opening price')
p('The secondary comparison uses larger, equal distances: after reaching D points from the open, does price travel another D points in the same direction before giving back D points to the open? Larger barriers reduce some within-minute ambiguity but answer a different question from the 20/20 race.')
table(['First displacement','Cases','Another D first\nwithin 1h','Another D first\nwithin 2h','Full-return-first\nbounds within 2h'],[
 [f'{d} pts',str(r2['n']),bounds(r1),bounds(r2),f'{r2["retracement_certain_pct"]:.1f}-{r2["retracement_possible_pct"]:.1f}%']
 for d in [40,60,80,100,120,160] for r1 in [cont(d,60,'balanced_initial_move')] for r2 in [cont(d,120,'balanced_initial_move')]
],[1.1,.7,1.5,1.5,1.6])
p('Bounds are feasible order ranges, not sampling confidence intervals or complementary point estimates. Unknown ordering and unreached boundaries prevent a simple sum to 100%. The 160-point cohort remains sparse.',True)
h('Recent-period check: the same full-distance race')
table(['Threshold','All-history\n2h bounds','2024 onward\ncases / 2h bounds','2026 only\ncases / 2h bounds'],[
 [f'{d} pts',bounds(allr),f'{rec["n"]} / {bounds(rec)}',f'{yr["n"]} / {bounds(yr)}']
 for d in [40,60,80,100,120,160]
 for allr in [cont(d,120,'balanced_initial_move')]
 for rec in [cont(d,120,'balanced_initial_move','2024_onward')]
 for yr in [cont(d,120,'balanced_initial_move','2026_only')]
],[1,1.4,1.9,1.9])
p('2026 ends September 3; it is not a full year or an October market estimate. Recent higher point volatility changes who reaches each threshold. The smaller event counts at high thresholds make a sharp cutoff particularly difficult to support.',True)
h('Finishing farther away is not one-way continuation')
table(['Threshold','Cases with known\nfirst direction','Farther in the initial direction\nat the two-hour deadline'],[
 [f'{d} pts',str(r['terminal_direction_known_n']),pct(r['deadline_beyond_threshold_pct_of_direction_known'])]
 for d in [40,60,80,100,120,160] for r in [cont(d)]
],[1,1.8,2.7])
p('Price may reverse or pull back before finishing farther in the initial direction. This endpoint metric is not a first-passage rate, has no formal majority flag here, and excludes ambiguous initial directions (three cases at 40 points). The threshold cohorts overlap.',True)

page('Rules, lineage and limits','A new bounded extension preserves the original failed campaign')
h('What changed and what stayed fixed')
p('The new grid contains <b>36 smaller-target cases</b> (5, 10 and 15 points) plus <b>12 repeated original-target controls</b>. It retains 40/60/80-point triggers, 20/30/40-point stops, both entry styles, 60/120-minute limits, one contract and the first 15-minute entry window. The original controls reproduced their prior daily outcomes exactly.')
p('First touch fades the first upper or lower threshold. Confirmation waits for a completed one-minute close strictly back inside that first breached level and enters at the next minute open. Brackets are anchored to the fill. Entries at or after 9:45 are rejected. One trade per session; no new side, averaging down, trailing stop or size escalation.')
p('Exit at the opening quote 60 or 120 minutes after the entry minute starts. For intraminute touches this can be up to one minute early. A working bracket has priority at a deadline opening gap; that minute\'s later high/low is excluded. Stops gap to adverse opening prices, while targets get no favorable gap improvement.')
h('Execution, cost and selection assumptions')
p('Baseline costs are $2.24 per round trip: $1.24 commission plus one 0.25-point tick per side ($1 total). Doubled costs are $4.48. These are illustrative, not verified brokerage quotes. The delay scenario adds one minute to entry and re-anchors target and stop, while retaining the 9:45 cutoff.')
p('Eligibility required 150 trades, positive net and profit factor 1.10. Eligible candidates were ranked by net profit / maximum daily closed-equity drawdown. The chosen case faced an annual later-period test requiring 30 trades, positive net and profit factor 1.05 under every required scenario. Testing stopped on the first failure. No official workbench stage was awarded.')
h('Data and uncertainty')
p('The checksum-verified MNQ.v.0 cache supports 1,841 complete cash sessions from May 6, 2019 through September 3, 2026. Cash holidays are excluded and no contract switches occur in the included morning windows. The original vendor request and acquisition receipt remain unverified.')
p('March 9, 12 and 16, 2020 are excluded for missing minutes; no bars are filled. These disruption-day exclusions can understate tail risk. Continuation sampling intervals use 2,000 seeded whole-calendar-month bootstrap draws, including zero-event months. Intervals are pointwise, not corrected for multiple comparisons, and are suppressed with fewer than 100 events or 10 occupied months.')
p('All years were previously inspected descriptively. The continuation analysis uses that history separately and never alters strategy parameters. Neither the chronological strategy evaluation nor the continuation rates are prospective evidence. Minute-order bounds cannot substitute for tick-level execution validation.')
h('Supporting evidence and sources')
p('The companion folder preserves every attempted configuration, conservative/favorable ledgers, selection/failure decisions, original-control parity checks, source snapshots, tests, continuation events, yearly/direction tables and artifact checksums. Calculations and exported ledgers were independently checked. This is a standalone research replay, not a brokerage or live TradingView implementation.',True)
p('<link href="https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html" color="#187c73">CME Group: MNQ specifications</link> - $2 per index point; 0.25-point tick ($0.50).<br/><link href="https://databento.com/docs/schemas/ohlcv" color="#187c73">Databento OHLCV schema</link> - bar-start timestamps and no-trade gaps.<br/><link href="https://www.nyse.com/markets/hours-calendars" color="#187c73">NYSE hours and holidays</link> - cash-session reference.',True)

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
    c.setFont('Helvetica-Bold',8);c.setFillColor(colors.HexColor(MUTED));c.drawString(80,756,'MNQ / SMALLER TARGETS AND CONTINUATION')
    c.setStrokeColor(colors.HexColor(RULE));c.line(40,36,572,36)
    c.setFont('Helvetica',7);c.drawString(40,23,'Historical research | One MNQ contract | All times Eastern | October 28, 2026')
    c.drawRightString(572,23,f'{d.page} / {len(pages)}')
story=[]
for i,pg in enumerate(pages):
    if i:story.append(PageBreak())
    story += [para(pg['title'],'title'),para(pg['subtitle'],'sub')]
    for b in pg['blocks']:
        if b[0]=='p':story.append(para(b[1],'small' if b[2] else 'body'))
        elif b[0]=='h':story.append(para(b[1],'h2'))
        elif b[0]=='table':story += [tab(*b[1:]),Spacer(1,7)]
        elif b[0]=='note':
            t=Table([[para(b[1],'note')]],colWidths=[WIDTH],hAlign='LEFT')
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#edf5f4')),('BOX',(0,0),(-1,-1),.5,colors.HexColor('#cee4df')),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9)]))
            story += [t,Spacer(1,8)]
PDF.parent.mkdir(parents=True,exist_ok=True)
doc=SimpleDocTemplate(str(PDF),pagesize=(612,792),leftMargin=34,rightMargin=34,topMargin=50,bottomMargin=48,title='MNQ Smaller Targets and Continuation',author='Strategy Workbench Research')
doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
reader=PdfReader(PDF)
assert len(reader.pages)==len(pages),f'Layout overflow: {len(reader.pages)} pages; expected {len(pages)}'

def webtext(s):
    s=re.sub(r'<link href="([^"]+)" color="[^"]+">',r'<a href="\1">',s)
    return escape_amp(s).replace('</link>','</a>').replace('\n','<br>')
sections=[]
for i,pg in enumerate(pages):
    parts=[f'<section id="section-{i+1}"><div class="eyebrow">{i+1:02d} / MNQ TARGETS AND CONTINUATION</div><h1>{pg["title"]}</h1><p class="subtitle">{pg["subtitle"]}</p>']
    for b in pg['blocks']:
        if b[0]=='p':parts.append(f'<p class="{"small" if b[2] else "body"}">{webtext(b[1])}</p>')
        elif b[0]=='h':parts.append(f'<h2>{b[1]}</h2>')
        elif b[0]=='note':parts.append(f'<aside>{b[1]}</aside>')
        elif b[0]=='table':
            headers=''.join(f'<th scope="col">{html.escape(str(x)).replace(chr(10),"<br>")}</th>' for x in b[1])
            rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(x)).replace(chr(10),"<br>")}</td>' for x in row)+'</tr>' for row in b[2])
            parts.append(f'<div class="table-wrap"><table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div>')
    parts.append('</section>');sections.append(''.join(parts))
nav=''.join(f'<a href="#section-{i+1}">{i+1}. {html.escape(pg["title"])}</a>' for i,pg in enumerate(pages))
css='''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#edf2f4;color:#263846;font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}header{background:#153549;color:white;padding:25px max(25px,calc((100vw - 1240px)/2));display:flex;align-items:center;justify-content:space-between;gap:20px}header strong{font-size:19px}header span{font-size:13px;opacity:.8}button{border:1px solid #6d8d9d;background:transparent;color:white;padding:9px 16px;border-radius:6px;cursor:pointer}.layout{max-width:1240px;margin:28px auto;display:grid;grid-template-columns:230px minmax(0,1fr);gap:24px;padding:0 20px}nav{position:sticky;top:22px;height:max-content;font-size:13px}nav a{display:block;padding:9px 11px;margin-bottom:5px;text-decoration:none;color:#153549;border-radius:5px}nav a:hover{background:#dbe8e9}nav p{font-size:12px;color:#596c78;padding:12px}section{background:white;border:1px solid #dce5e8;box-shadow:0 6px 18px #1c36400a;border-radius:10px;padding:34px;margin-bottom:24px;scroll-margin-top:20px}.eyebrow{font-size:11px;font-weight:750;letter-spacing:.12em;color:#187c73}h1{font-size:29px;line-height:1.2;color:#153549;margin:12px 0 14px}h2{font-size:18px;line-height:1.35;color:#153549;margin:25px 0 12px}.subtitle{font-size:13px;color:#596c78;margin-bottom:24px}p{margin:12px 0}.small{font-size:12px;color:#596c78;line-height:1.6}aside{background:#edf5f4;border-left:4px solid #187c73;padding:18px 20px;font-weight:650;color:#153549;margin:19px 0}.table-wrap{overflow-x:auto;margin:13px 0}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:13px}th{background:#153549;color:white;text-align:left;font-size:12px;line-height:1.3;vertical-align:bottom}th,td{padding:9px 7px}td{vertical-align:top;border-bottom:1px solid #dce5e8}tr:nth-child(even) td{background:#f2f6f7}a{color:#187c73}footer{text-align:center;font-size:12px;color:#596c78;padding:10px 20px 35px}@media(max-width:850px){.layout{display:block}nav{position:static;display:flex;overflow-x:auto;gap:8px;margin-bottom:20px}nav a{white-space:nowrap;background:#dfe9eb;font-size:12px}nav p{display:none}section{padding:22px}h1{font-size:25px}header{padding:20px}header span{display:none}.table-wrap table{min-width:650px}}@media print{body{background:white;font-size:10pt}header,nav,button,footer{display:none}.layout{display:block;margin:0;padding:0}section{box-shadow:none;border:0;padding:0;break-after:page;margin:0}h1{font-size:22pt}h2{font-size:13pt}table{font-size:9pt}th,td{padding:5px}.small,.subtitle{font-size:8pt}aside{padding:9px}@page{size:letter;margin:14mm}}'''
document='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MNQ Smaller Targets and Continuation</title><style>'+css+'</style></head><body><header><div><strong>MNQ / Smaller Targets and Continuation</strong><br><span>Opening-fade extension and separate continuation study | October 28, 2026</span></div><button onclick="window.print()">Print report</button></header><div class="layout"><nav>'+nav+'<p>36 new target cases.<br>12 original controls.<br>Six continuation thresholds.<br>All times Eastern.</p></nav><main>'+''.join(sections)+'</main></div><footer>Standalone historical research. Strategy results and descriptive continuation evidence have separate roles.</footer></body></html>'
(OUT/'report.html').write_text(document,encoding='utf-8')
print(json.dumps({'pdf':str(PDF),'pages':len(reader.pages),'html':str(OUT/'report.html')},indent=2))
