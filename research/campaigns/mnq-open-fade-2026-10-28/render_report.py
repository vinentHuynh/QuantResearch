"""Portable report from the frozen, bounded MNQ fade campaign.

No results are created here. This renderer requires the completed summary.json.
"""
from pathlib import Path
import html
import json
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'reports/mnq-open-fade-2026-10-28'
PDF=ROOT/'output/pdf/mnq-opening-fade-strategy-test.pdf'
SUMMARY=OUT/'summary.json'
if not SUMMARY.exists():
    raise SystemExit('Waiting for the completed campaign summary; no report has been generated.')
S=json.loads(SUMMARY.read_text(encoding='utf-8'))
P=S['protocol']

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak
from pypdf import PdfReader

NAVY='#153549';TEAL='#187c73';INK='#263846';MUTED='#596c78';RULE='#dce5e8';WIDTH=532
styles={
 'title':ParagraphStyle('title',fontName='Helvetica-Bold',fontSize=24,leading=27,textColor=colors.HexColor(NAVY),spaceAfter=9),
 'sub':ParagraphStyle('sub',fontName='Helvetica',fontSize=10,leading=13,textColor=colors.HexColor(MUTED),spaceAfter=10),
 'h2':ParagraphStyle('h2',fontName='Helvetica-Bold',fontSize=12.2,leading=15.5,textColor=colors.HexColor(NAVY),spaceBefore=9,spaceAfter=5),
 'body':ParagraphStyle('body',fontName='Helvetica',fontSize=9.2,leading=12.8,textColor=colors.HexColor(INK),spaceAfter=7),
 'small':ParagraphStyle('small',fontName='Helvetica',fontSize=8,leading=10.8,textColor=colors.HexColor(MUTED),spaceAfter=6),
 'cell':ParagraphStyle('cell',fontName='Helvetica',fontSize=8.2,leading=10.5,textColor=colors.HexColor(INK)),
 'head':ParagraphStyle('head',fontName='Helvetica-Bold',fontSize=8,leading=10,textColor=colors.white),
 'note':ParagraphStyle('note',fontName='Helvetica-Bold',fontSize=10,leading=14,textColor=colors.HexColor(NAVY)),
}
NAMES={'touch':'First touch','confirm':'Close back inside'}
SCENARIOS={'baseline':'Baseline','favorable_order':'Favorable order bound','double_cost':'Doubled costs','entry_delay_1m':'Extra 1-minute delay'}
dev=sorted([r for r in S['attempts'] if r['stage']=='development' and r['scenario']=='baseline'],key=lambda r:(0 if r['mode']=='touch' else 1,r['trigger'],r['horizon']))
assert len(dev)==12
fav={(r['mode'],r['trigger'],r['horizon']):r for r in S['attempts'] if r['stage']=='development' and r['scenario']=='favorable_order'}
evals=[r for r in S['attempts'] if r['stage'].startswith('evaluation_')]
all_dev_failed=all(x['stage']=='development' and x['outcome']=='failed' for x in S['dispositions'])


def n(x,digits=1):
    return 'n/a' if x is None else f'{x:,.{digits}f}'


def money(x,digits=0):
    return 'n/a' if x is None else ('-' if x<0 else '')+'$'+f'{abs(x):,.{digits}f}'


def pf(r):
    if not r['trades']:
        return 'n/a'
    return 'no losses' if r['profit_factor'] is None and r.get('no_losing_trades') else n(r['profit_factor'],2)


pages=[];current=None
def page(title,subtitle):
    global current
    current={'title':title,'subtitle':subtitle,'blocks':[]};pages.append(current)
def p(text,small=False):current['blocks'].append(('p',text,small))
def h(text):current['blocks'].append(('h',text))
def note(text):current['blocks'].append(('note',text))
def table(headers,rows,widths=None):current['blocks'].append(('table',headers,rows,widths))


page('Testing the opening fade','MNQ | First touch versus a one-minute close back inside | October 28, 2026')
if all_dev_failed:
    note('Neither entry style passed the frozen development screen. Testing stopped before later-year strategy evaluation. This is a failure of the conservative test, with execution uncertainty shown separately.')
else:
    note('The two entry styles were screened separately, then advanced only while the frozen criteria passed. The table below shows each style\'s actual stopping point.')
table(['Entry style','Result','Last stage','Strategy outcomes tested through'],[
 [NAMES[d['mode']], 'Historical research pass' if d['outcome']=='historical_research_pass' else 'Stopped - criteria failed',d['stage'].replace('_',' '),d['tested_through']]
 for d in S['dispositions']],[1.2,1.5,1.25,1.65])
p('The test compares 40-, 60-, and 80-point triggers during the first 15 minutes after the 9:30 a.m. Eastern open. Each trade fades the first reached side, with one MNQ contract, a half-trigger target, an equal stop, and a 60- or 120-minute maximum hold. There is at most one trade per session.')
p('<b>The most promising development case was confirmation after an 80-point move:</b> a one-hour limit produced $355.56 net over 156 trades, or $2.28 per trade. Its 1.060 profit factor missed the frozen 1.10 hurdle. Positive development profit alone did not qualify it for further testing.')
h('The two entries')
table(['First touch','Close back inside'],[[
 'Enter against the move when price first reaches the upper or lower trigger. Upper trigger = short; lower trigger = long.',
 'Lock the first breached side. Wait for a completed one-minute close strictly back inside that level, then enter at the next minute open.'
],[
 'Nominal fill is the trigger. A gap beyond it receives the less-favorable trigger fill; execution friction is charged separately.',
 'The target and stop are re-anchored to the actual next-open entry price. A later signal cannot switch sides.'
]])
h('A concrete 60-point example')
table(['Cash open','Short trigger / entry','Profit target','Stop'],[['20,000','20,060','20,030','20,090']])
p('That is the first-touch example: 30 points of target and 30 points of stop. For the confirmation version, a close below 20,060 is required; if the next opening quote is 20,052, entry is 20,052, target 20,022, and stop 20,082. Confirmation does not preserve the original trigger-based bracket.',True)
h('Costs and timing')
p('<b>Baseline:</b> $2.24 per filled round trip: $1.24 commission plus one tick of modeled execution friction per side. <b>Planned stress, not run:</b> $4.48. These are illustrative inputs, not a verified broker quote. Entries must occur before 9:45 a.m. Eastern, and the holding clock starts at the actual entry minute.')

page('All 12 development candidates','May 6, 2019 - December 31, 2023 | Conservative execution order | One MNQ contract')
p('Eligibility required <b>at least 150 trades, positive net profit, and profit factor of at least 1.10</b>. Within each style, eligible candidates would be ranked by net profit divided by maximum daily closed-equity drawdown. No losing or ineligible candidate is hidden.')
table(['Entry / trigger','Hold','Trades','Net profit','Mean / trade','Profit\nfactor','Closed\ndrawdown','Eligible'],[
 [f'{"Touch" if r["mode"]=="touch" else "Confirm"} / {r["trigger"]}pt',f'{r["horizon"]//60}h',str(r['trades']),money(r['net_profit']),money(r['expectancy_dollars'],2),pf(r),money(r['max_daily_closed_drawdown']),'Yes' if r['eligible'] else 'No']
 for r in dev],[1.35,.5,.6,.95,1.0,.7,1.0,.65])
p('All net figures include baseline modeled costs. Profit factor is total positive net trade P&L divided by the absolute total of negative net trade P&L. Drawdown is based on daily closed equity and excludes unrealized intratrade losses. Dollar amounts are rounded for display; exported ledgers retain precision.',True)
h('Development examples shown for context')
for r in S['development_best_descriptive']:
    status='met development eligibility' if r['eligible'] else 'did not meet development eligibility'
    reasons='; '.join(r.get('eligibility_failures',[]))
    p(f'<b>{NAMES[r["mode"]]}:</b> {r["trigger"]}-point trigger, {r["horizon"]//60}-hour hold; {r["trades"]} trades, {money(r["net_profit"])} net, {money(r["expectancy_dollars"],2)} average per trade, profit factor {pf(r)}, and {money(r["max_daily_closed_drawdown"])} closed drawdown. This row {status}.'+(f' Failed criteria: {html.escape(reasons)}.' if reasons else ''))
p('These displayed rows follow the saved net/drawdown ranking, which is not a useful best-strategy endorsement when returns are negative. The 80-point, two-hour touch case also failed, despite a smaller net loss of $246.08. No candidate qualified for selection or advancement.',True)
h('Why the return-to-open frequency was insufficient')
p('The earlier report counted whether price eventually returned after an opening push. This strategy has a causal entry, an intervening stop, a partial-recovery target, costs, and a deadline. A later recovery does not rescue a trade whose stop was reached first.')

page('Execution uncertainty is material','One-minute OHLC cannot always identify the order of entry, target and stop')
p('The primary test uses conservative feasible ordering. The favorable bound credits the best feasible ordering where minute data cannot resolve the path. These are sensitivity bounds, not two executable strategies and not evidence that future outcomes can choose the trade direction.')
table(['Entry / trigger','Hold','Conservative\nnet profit','Favorable-bound\nnet profit','Conservative\nmean / trade','Favorable-bound\nmean / trade'],[
 [f'{"Touch" if r["mode"]=="touch" else "Confirm"} / {r["trigger"]}pt',f'{r["horizon"]//60}h',money(r['net_profit']),money(fav[(r['mode'],r['trigger'],r['horizon'])]['net_profit']),money(r['expectancy_dollars'],2),money(fav[(r['mode'],r['trigger'],r['horizon'])]['expectancy_dollars'],2)]
 for r in dev],[1.2,.5,1.2,1.3,1.25,1.3])
p('The favorable bound cannot make a failed conservative candidate eligible. If a result changes sign across the bounds, the data do not establish a single executable outcome. Tick-level data or conservative execution evidence would be needed to resolve it.',True)
p('<b>Example:</b> the 40-point first-touch, one-hour case ranges from -$1,934 conservative to +$7,746 under favorable ordering. Entry-minute target timing was ambiguous in 241 of its 724 trades. That is too large a difference to label the immediate-entry idea definitively profitable or unprofitable from minute bars alone.',True)
h('Ambiguity in the displayed 80-point, one-hour cases')
table(['Style / trigger / hold','Dual-side\nsessions','Entry-minute\ntarget uncertainty','Stop/target\ncollision trades','Trades entered\nin first minute'],[
 [f'{NAMES[r["mode"]]} / {r["trigger"]} / {r["horizon"]//60}h',str(r['direction_ambiguous_sessions']),str(r['entrybar_target_ambiguous_trades']),str(r['bracket_collision_trades']),str(r['first_minute_trades'])]
 for r in S['development_best_descriptive']],[1.8,.85,1.2,1.15,1.15])
p('Counts are diagnostic categories and can overlap. A first-minute entry is not automatically ambiguous. A dual-side bar can produce different feasible first directions, and confirmation can produce a no-fill branch. The bounds retain those alternatives.',True)
h('What the conservative rules do')
p('A favorable extreme before a touch entry is not treated as a certain post-entry target. Known opening gaps resolve before within-minute extremes. Stops gap to an adverse opening quote; targets receive no favorable gap improvement. At the time limit, the opening quote is used and that minute\'s later high/low is excluded.')

page('Chronological disposition','Selection, later evaluation and stopping rules were frozen before strategy results')
if not evals:
    note('No later-year strategy evaluation was run. Both styles stopped at development because no candidate met every entry criterion. The 2024-2026 strategy windows remain unscored in this campaign.')
    h('Yearly record: 80-point trigger, one-hour limit')
    ids={r['case_id'] for r in S['development_best_descriptive']}
    yr=sorted([r for r in S['yearly_breakdown'] if r['case_id'] in ids],key=lambda r:(0 if r['mode']=='touch' else 1,r['year']))
    table(['Entry style','Year','Trades','Net profit','Mean / trade','Profit factor'],[
      [NAMES[r['mode']],str(r['year'])+('*' if r['year']==2019 else ''),str(r['trades']),money(r['net_profit']),money(r['expectancy_dollars'],2),pf(r)] for r in yr
    ],[1.5,.65,.65,1.05,1.15,1])
    p('* 2019 begins May 6. These are breakdowns of the displayed 80-point, one-hour cases. No candidate qualified for selection, and these yearly views are not independent validation.',True)
    p('The positive 80-point confirmation result was concentrated in 2021 (+$629.78); 2022 lost $330.24. The remaining tested years did not establish consistent annual profitability. The favorable-order replay gives the same result for this candidate, so its screen failure is not caused by an unresolved OHLC tie.',True)
else:
    p('Only configurations chosen on earlier data were scored in the following fold. A failed fold stopped that style; later strategy outcomes were not inspected to search for a rescue.')
    table(['Style / fold','Trigger / hold','Scenario','Trades','Net profit','PF','Gate'],[
      [f'{NAMES[r["mode"]]} / {r["stage"].split("_")[-1]}',f'{r["trigger"]}pt / {r["horizon"]//60}h',SCENARIOS[r['scenario']],str(r['trades']),money(r['net_profit']),pf(r),'Bound only' if r['scenario']=='favorable_order' else 'Fail' if r.get('evaluation_failures') else 'Pass'] for r in evals
    ],[1.35,.85,1.5,.6,1,.6,.65])
h('What would have been required to advance')
p('<b>Chronological folds:</b> 2024, 2025, and January-September 3, 2026, using only expanding earlier history to select among the same six candidates in each style. Each selected fold required at least 30 trades, positive net profit, and profit factor of at least 1.05 under baseline costs, doubled costs, and one additional minute of entry delay.')
p('<b>After all folds pass:</b> test the final trigger at -10% and +10% under doubled costs, requiring at least 100 trades, positive net profit, and profit factor of at least 1.05. A failure ends progression; it does not authorize a wider search for a passing result.')
p('<b>Not run in this campaign:</b> later-year strategy folds, doubled-cost and entry-delay stress scenarios, and nearby-trigger robustness. Those were conditional next stages; the development failure stopped advancement.',True)
p('All years were previously inspected in the descriptive opening report and other research. Chronological selection reduces leakage within this experiment; it does not make later years globally unseen or prospective.',True)

page('Rules, data and evidence','Standalone historical replay | Strategy-specific conclusions, not live approval')
h('Exact rules retained in the protocol')
p('<b>Reference and first side:</b> the first trade of the 9:30 minute is the day\'s opening reference. Upper and lower thresholds remain fixed at open plus/minus the chosen trigger. The first reached side stays locked. There is no second trade, averaging down, stop-and-reverse, or size increase.')
p('<b>Entry cutoff:</b> actual entry must occur before 9:45. Confirmation waits for a strict close back inside the first breached level and fills at the next minute open; the breach minute may confirm. A delayed confirmation at or after 9:45 is rejected. In the delay stress, touch fills at the next opening quote and confirmation waits one additional minute beyond its normal fill.')
p('<b>Brackets:</b> 40/60/80-point triggers use 20/30/40-point targets and identical stop distances from the nominal entry. For confirmation and delayed entries, brackets are re-anchored to the actual fill. No trailing stop or discretionary exit is assumed.')
p('<b>Time exit:</b> flatten at the opening quote 60 or 120 minutes after the entry minute begins. A working bracket has priority for a gap at that quote; otherwise use the quote as the time exit. An intraminute touch can expire up to one minute early because exact entry seconds are unavailable. The deadline bar\'s later range is never used.')
h('Data quality and scope')
p(f'The source is the registered, checksum-verified MNQ.v.0 one-minute cache, with {S["data"]["available_sessions"]:,} complete cash sessions available from {S["data"]["available_first"]} through {S["data"]["available_last"]}. Cash holidays are excluded. Every included day has all 135 minute bars from 9:30 through 11:44 and no contract switch in that window. The original vendor request and acquisition receipt remain unverified.')
p('March 9, 12, and 16, 2020 are excluded for missing minutes; no bars are filled. Excluding those disruption sessions can understate tail risk. Early-close sessions remain eligible because every required quote occurs before the cash close. Times follow America/New_York daylight saving rules.')
p('This is a source-snapshotted standalone replay. The current workbench event engine cannot faithfully express simultaneous first-touch thresholds from the first opening minute. There is no official workbench run/evaluation ID, stage promotion, TradingView parity, prospective evidence, or live-trading approval.')
h('Reproducibility and sources')
p('The companion folder preserves the frozen protocol, replay source, synthetic tests, every attempted configuration summary, daily ledgers, descriptive trade exports, yearly breakdowns, decisions and source checksums. The completed calculations were checked independently before publication. Figures are rounded in this report; the ledgers retain full precision.',True)
p('<link href="https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html" color="#187c73">CME Group: MNQ specifications</link> - $2 per index point and a 0.25-point tick ($0.50).<br/><link href="https://databento.com/docs/schemas/ohlcv" color="#187c73">Databento OHLCV schema</link> - minute timestamps label interval starts.<br/><link href="https://www.nyse.com/markets/hours-calendars" color="#187c73">NYSE hours and holidays</link> - cash-session reference.',True)


def para(text,style='body'):
    text=re.sub(r'&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z][A-Za-z0-9]+;)','&amp;',text)
    return Paragraph(text.replace('\n','<br/>'),styles[style])
def tab(headers,rows,widths):
    widths=[WIDTH/len(headers)]*len(headers) if widths is None else [WIDTH*w/sum(widths) for w in widths]
    vals=[[para(html.escape(str(x)),'head') for x in headers]]+[[para(html.escape(str(x)),'cell') for x in r] for r in rows]
    t=Table(vals,colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor(NAVY)),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f1f5f6')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),('LINEBELOW',(0,-1),(-1,-1),.5,colors.HexColor(RULE))]))
    return t
def decorate(c,d):
    c.setFillColor(colors.HexColor(TEAL));c.rect(40,756,32,4,fill=1,stroke=0)
    c.setFont('Helvetica-Bold',8);c.setFillColor(colors.HexColor(MUTED));c.drawString(80,756,'MNQ / OPENING FADE STRATEGY TEST')
    c.setStrokeColor(colors.HexColor(RULE));c.line(40,36,572,36)
    c.setFont('Helvetica',7);c.drawString(40,23,'Historical research | One MNQ contract | Illustrative costs | All times Eastern')
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
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#edf5f4')),('BOX',(0,0),(-1,-1),.5,colors.HexColor('#cee4df')),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
            story += [t,Spacer(1,9)]
PDF.parent.mkdir(parents=True,exist_ok=True)
doc=SimpleDocTemplate(str(PDF),pagesize=(612,792),leftMargin=34,rightMargin=34,topMargin=50,bottomMargin=48,title='MNQ Opening Fade Strategy Test',author='Strategy Workbench Research')
doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
reader=PdfReader(PDF)
assert len(reader.pages)==len(pages),f'Layout overflow: {len(reader.pages)} pages; expected {len(pages)}'

def webtext(s):
    s=re.sub(r'<link href="([^"]+)" color="[^"]+">',r'<a href="\1">',s)
    s=re.sub(r'&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z][A-Za-z0-9]+;)','&amp;',s)
    return s.replace('</link>','</a>').replace('\n','<br>')
sections=[]
for i,pg in enumerate(pages):
    parts=[f'<section id="section-{i+1}"><div class="eyebrow">{i+1:02d} / MNQ STRATEGY TEST</div><h1>{pg["title"]}</h1><p class="subtitle">{pg["subtitle"]}</p>']
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
css='''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#edf2f4;color:#263846;font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}header{background:#153549;color:white;padding:25px max(25px,calc((100vw - 1240px)/2));display:flex;align-items:center;justify-content:space-between;gap:20px}header strong{font-size:19px}header span{font-size:13px;opacity:.8}button{border:1px solid #6d8d9d;background:transparent;color:white;padding:9px 16px;border-radius:6px;cursor:pointer}.layout{max-width:1240px;margin:28px auto;display:grid;grid-template-columns:230px 1fr;gap:24px;padding:0 20px}nav{position:sticky;top:22px;height:max-content;font-size:13px}nav a{display:block;padding:9px 11px;margin-bottom:5px;text-decoration:none;color:#153549;border-radius:5px}nav a:hover{background:#dbe8e9}nav p{font-size:12px;color:#596c78;padding:12px}section{background:white;border:1px solid #dce5e8;box-shadow:0 6px 18px #1c36400a;border-radius:10px;padding:34px;margin-bottom:24px;scroll-margin-top:20px}.eyebrow{font-size:11px;font-weight:750;letter-spacing:.12em;color:#187c73}h1{font-size:29px;line-height:1.2;color:#153549;margin:12px 0 14px}h2{font-size:18px;line-height:1.35;color:#153549;margin:25px 0 12px}.subtitle{font-size:13px;color:#596c78;margin-bottom:24px}p{margin:12px 0}.small{font-size:12px;color:#596c78;line-height:1.6}aside{background:#edf5f4;border-left:4px solid #187c73;padding:18px 20px;font-weight:650;color:#153549;margin:19px 0}.table-wrap{overflow-x:auto;margin:13px 0}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:13px}th{background:#153549;color:white;text-align:left;font-size:12px;line-height:1.3;vertical-align:bottom}th,td{padding:10px 8px}td{vertical-align:top;border-bottom:1px solid #dce5e8}tr:nth-child(even) td{background:#f2f6f7}a{color:#187c73}footer{text-align:center;font-size:12px;color:#596c78;padding:10px 20px 35px}@media(max-width:850px){.layout{display:block}nav{position:static;display:flex;overflow-x:auto;gap:8px;margin-bottom:20px}nav a{white-space:nowrap;background:#dfe9eb;font-size:12px}nav p{display:none}section{padding:22px}h1{font-size:25px}header{padding:20px}header span{display:none}.table-wrap table{min-width:600px}}@media print{body{background:white;font-size:10pt}header,nav,button,footer{display:none}.layout{display:block;margin:0;padding:0}section{box-shadow:none;border:0;padding:0;break-after:page;margin:0}h1{font-size:22pt}h2{font-size:13pt}table{font-size:9pt}th,td{padding:5px}.small,.subtitle{font-size:8pt}aside{padding:9px}@page{size:letter;margin:14mm}}'''
document='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MNQ Opening Fade Strategy Test</title><style>'+css+'</style></head><body><header><div><strong>MNQ / Opening Fade Strategy Test</strong><br><span>First touch versus close back inside | October 28, 2026</span></div><button onclick="window.print()">Print report</button></header><div class="layout"><nav>'+nav+'<p>12 bounded configurations.<br>One MNQ contract.<br>Conservative execution gates.<br>All times Eastern.</p></nav><main>'+''.join(sections)+'</main></div><footer>Standalone historical replay. No official workbench stage advancement or live-trading approval.</footer></body></html>'
(OUT/'report.html').write_text(document,encoding='utf-8')
print(json.dumps({'pdf':str(PDF),'pages':len(reader.pages),'html':str(OUT/'report.html')},indent=2))
