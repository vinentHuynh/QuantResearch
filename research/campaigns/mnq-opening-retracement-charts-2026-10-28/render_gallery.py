"""Build a local, responsive gallery from the preserved real-session examples."""
from pathlib import Path
from datetime import datetime
import html
import json

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'reports/mnq-opening-retracement-charts-2026-10-28'
meta = json.loads((OUT / 'examples.json').read_text(encoding='utf-8'))
examples = meta['examples']
assert len(examples) == 10
assert meta['classification_target_points'] == 10
CATEGORIES = {
    'retracement_first': 'Retracement before stop',
    'continuation_only': 'Stop; no 10-point retracement',
    'stop_then_retracement': 'Stop first, retracement later',
    'ambiguous': 'Order unresolved',
}

def esc(x):
    return html.escape(str(x), quote=True)

def price(x):
    return f'{x:,.2f}'

def minute(value):
    return f'{value} minute' if value else 'Not reached before 09:45'

cards = []
for example in examples:
    for key in ['png', 'svg', 'data_csv']:
        assert (OUT / example[key]).is_file(), example[key]
    title, category = example['title'], example['category']
    date = datetime.strptime(example['date'], '%Y-%m-%d').strftime('%B %d, %Y').replace(' 0', ' ')
    timing = (
        f'Stretch: {minute(example["trigger_minute_et"])} · '
        f'10-point retracement: {minute(example["first_10pt_retracement_minute_et"])} · '
        f'Stop level: {minute(example["first_stop_minute_et"])}'
    )
    if category == 'ambiguous':
        timing = f'Stretch: {minute(example["trigger_minute_et"])} · 10-point retracement: certain by the cutoff; first minute unresolved · Stop level: {minute(example["first_stop_minute_et"])}'
    levels = [
        ('09:30 open', example['opening_price']),
        ('Stretch / nominal entry', example['stretch_level']),
        ('5-point retracement', example['target_levels']['5']),
        ('10-point retracement', example['target_levels']['10']),
        ('15-point retracement', example['target_levels']['15']),
        (f'{example["stop_points"]:g}-point stop level', example['stop_level']),
    ]
    levels_html = ''.join(f'<div><dt>{esc(label)}</dt><dd>{price(value)}</dd></div>' for label, value in levels)
    alt = f'{example["date"]}: actual one-minute MNQ candles, {example["stretch_points"]}-point {example["first_direction"]} stretch. {title}. Classification uses the 10-point retracement.'
    cards.append(f'''
<article class="chart-card" id="{esc(example['id'])}" data-stretch="{example['stretch_points']}" data-scenario="{category}">
  <div class="card-heading"><div><div class="badge {category}">{esc(CATEGORIES[category])}</div><h2>{example['stretch_points']}-point stretch <span>· {date}</span></h2></div><span class="side">{esc(example['first_direction'].capitalize())} push · {esc(example['fade_side'].upper())} fade</span></div>
  <p class="narrative">{esc(example['narrative'])}</p>
  <div class="chart-frame" tabindex="0" aria-label="Scrollable chart for {esc(date)}"><a href="{esc(example['svg'])}" target="_blank" rel="noopener" aria-label="Open full-size chart for {esc(date)}"><img src="{esc(example['png'])}" alt="{esc(alt)}" loading="lazy" decoding="async" width="2336" height="1216"></a></div>
  <div class="card-caption"><p class="timing">{esc(timing)}</p><dl class="levels">{levels_html}</dl><div class="card-links"><a href="{esc(example['svg'])}" target="_blank" rel="noopener">Open full-size chart</a><a href="{esc(example['png'])}" download>Save PNG</a><a href="{esc(example['data_csv'])}" download>15 observed candles · CSV</a></div></div>
</article>''')

options = ''.join(f'<option value="{key}">{esc(value)}</option>' for key, value in CATEGORIES.items())
assert (OUT / meta['overview_png']).is_file()
css = '''
:root{--ink:#183747;--muted:#59717c;--teal:#157d73;--line:#dce6e9;--pale:#edf6f4}*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:#edf2f4;color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}main{max-width:1260px;margin:30px auto;padding:0 22px 28px}header{background:var(--ink);color:white;border-radius:14px;padding:30px 34px}.eyebrow{font-size:11px;font-weight:750;letter-spacing:.13em;color:#a6d9d2}h1{font-size:36px;line-height:1.17;letter-spacing:-.025em;margin:10px 0 13px}header p{max-width:1030px;margin:0;color:#e1ebee}.header-links{display:flex;flex-wrap:wrap;gap:12px;margin-top:18px}.header-links a{color:#d5f2ed;border-bottom:1px solid #739b9d;text-decoration:none;font-size:13px}.guide{background:white;border:1px solid var(--line);border-radius:12px;padding:22px 27px;margin:22px 0}.guide p{margin:8px 0}.guide strong{color:var(--teal)}.small{font-size:13px;color:var(--muted);line-height:1.6}.controls{display:flex;align-items:flex-end;gap:18px;flex-wrap:wrap;background:white;border:1px solid var(--line);border-radius:10px;padding:18px 22px;margin:22px 0}.control{flex:1;min-width:190px}.control label{display:block;font-size:12px;font-weight:750;margin-bottom:7px}select{font:inherit;font-size:14px;background:white;color:var(--ink);border:1px solid #a6bdc5;border-radius:6px;padding:10px 12px;width:100%}#result-count{font-size:13px;color:var(--muted);padding:10px 0;margin:0}button{font:inherit;font-size:13px;border:1px solid #bdd4d7;background:#f7fafb;color:var(--ink);border-radius:6px;padding:10px 14px;cursor:pointer}.chart-card{background:white;border:1px solid var(--line);border-radius:12px;margin:24px 0;overflow:hidden;box-shadow:0 6px 20px #1c364008}.card-heading{display:flex;justify-content:space-between;gap:20px;align-items:center;padding:23px 27px 0}.badge{display:inline-block;font-size:11px;font-weight:750;letter-spacing:.025em;padding:4px 9px;border-radius:5px;background:#e8f4ef;color:#18724e}.continuation_only{background:#fcebed;color:#ae3341}.stop_then_retracement{background:#eeeaf7;color:#68518d}.ambiguous{background:#fff2d9;color:#836415}h2{font-size:24px;line-height:1.3;margin:10px 0}h2 span{font-size:18px;font-weight:500;color:var(--muted)}.side{font-size:12px;font-weight:650;color:var(--muted);white-space:nowrap}.narrative{padding:0 27px;margin:0 0 17px;font-size:15px}.chart-frame{overflow-x:auto;background:#f5f8f9;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.chart-frame img{display:block;width:100%;height:auto;min-width:1000px}.chart-frame a{display:block;color:inherit}.card-caption{padding:18px 27px 22px}.timing{font-size:12px;line-height:1.7;color:var(--muted);margin:0 0 15px}.levels{display:grid;grid-template-columns:repeat(6,1fr);gap:13px;margin:0}.levels dt{font-size:11px;color:var(--muted);line-height:1.4;min-height:31px}.levels dd{font-size:16px;font-weight:700;margin:5px 0 0;font-variant-numeric:tabular-nums}.card-links{display:flex;gap:20px;flex-wrap:wrap;margin-top:18px;font-size:12px}a{color:var(--teal)}.overview{background:white;border:1px solid var(--line);border-radius:10px;margin:22px 0;padding:17px 22px}.overview summary{font-size:14px;font-weight:650;cursor:pointer}.overview .chart-frame{margin:16px -22px 0}.overview img{min-width:1100px}.empty{background:white;border:1px solid var(--line);padding:27px;border-radius:10px}.method{background:white;border:1px solid var(--line);border-radius:10px;padding:24px 27px;margin-top:28px}.method h2{margin-top:0;font-size:22px}.method p{margin:10px 0}.method ul{padding-left:22px}.method li{margin:8px 0}.method a{font-size:13px}footer{text-align:center;font-size:12px;color:var(--muted);padding:20px 3px 0}@media(max-width:850px){main{padding:0 12px 20px;margin:14px auto}header{padding:25px 22px}h1{font-size:29px}.guide{padding:19px 21px}.controls{gap:12px;padding:17px}.control{min-width:150px}.card-heading{display:block;padding:20px 20px 0}h2{font-size:21px}h2 span{display:block;font-size:16px;margin-top:4px}.side{display:block;margin:7px 0 12px}.narrative{padding:0 20px}.card-caption{padding:17px 20px 22px}.levels{grid-template-columns:repeat(3,1fr);gap:17px 12px}.levels dt{min-height:31px}.card-links{gap:11px 18px}.method{padding:22px}.chart-frame{scrollbar-width:thin}}@media(max-width:440px){.control{flex-basis:100%}.levels{grid-template-columns:repeat(2,1fr)}.levels dt{min-height:auto}.levels dd{margin-top:3px}}@media print{body{background:white}main{max-width:none;margin:0;padding:0}header{border-radius:0;padding:18px 22px}h1{font-size:25pt}.controls,.overview,.header-links,button{display:none}.guide{padding:14px 20px}.chart-card{break-inside:avoid;box-shadow:none;margin:16px 0}.chart-frame{overflow:visible}.chart-frame img{min-width:0;width:100%}.card-heading{padding:15px 20px 0}.card-caption{padding:12px 20px}.levels{grid-template-columns:repeat(6,1fr)}.levels dd{font-size:11pt}.levels dt,.timing{font-size:8pt}.card-links{display:none}.narrative{font-size:10pt}h2{font-size:15pt}.method{font-size:10pt}footer{font-size:8pt}@page{size:letter landscape;margin:12mm}}
'''

document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MNQ Opening Retracements — Real Session Charts</title><style>{css}</style></head><body><main>
<header><div class="eyebrow">MNQ / REAL OPENING CANDLES</div><h1>See the retracement scenarios</h1><p>Actual one-minute candles from selected sessions: a retracement before the stop level, continuation without a 10-point retracement, and a stop-level touch followed by a later retracement. An extra example shows what a minute candle cannot resolve.</p><div class="header-links"><a href="../mnq-opening-retracement-2026-10-28/report.html">Open the percentage report</a><a href="examples.json" download>Download example metadata</a><a href="#method">How to read these charts</a></div></header>
<div class="guide"><p><strong>Every scenario label uses the 10-point retracement.</strong> The 5- and 15-point levels are also drawn as references. The continuation/stop distance is 20, 30 or 40 points for a 40-, 60- or 80-point stretch.</p><p class="small">The blue band marks the trigger minute. Candles show 09:30–09:44 Eastern; the 09:45 line is a cutoff, not an observed price. These selected illustrations do not measure how often a scenario occurs. Nominal entry and stop lines are reference prices, not verified fills.</p><p class="small">On a small screen, swipe the chart sideways or open the full-size version.</p></div>
<details class="overview"><summary>Nine clear scenarios at a glance</summary><div class="chart-frame" tabindex="0" aria-label="Scrollable overview"><a href="{esc(meta['overview_png'])}" target="_blank" rel="noopener"><img src="{esc(meta['overview_png'])}" alt="Overview of the nine selected clear scenarios, arranged by opening stretch and outcome." loading="lazy"></a></div><p class="small">Open the individual charts below for prices, times and the observed candle data.</p></details>
<div class="controls"><div class="control"><label for="stretch">Opening stretch</label><select id="stretch"><option value="all">All stretches</option><option value="40">40 points</option><option value="60">60 points</option><option value="80">80 points</option></select></div><div class="control"><label for="scenario">10-point scenario</label><select id="scenario"><option value="all">All scenarios</option>{options}</select></div><button id="reset" type="button">Reset filters</button><p id="result-count" aria-live="polite">Showing {len(examples)} charts</p></div>
<div id="gallery">{''.join(cards)}</div><p id="empty" class="empty" hidden>No selected example matches these filters. The unresolved-order example is a 40-point stretch.</p>
<section id="method" class="method"><h2>How the examples were chosen</h2><p>The gallery uses the saved historical event ledger and the actual 15 one-minute candles for each displayed date. For each stretch and scenario, the selection took the latest known-direction session with a trigger after 09:30 and no 10-point favorable extreme in its trigger candle, preferring separate trigger and outcome minutes when available. The additional 40-point example deliberately shows unresolved order.</p><ul><li><strong>Selected for readability, not representativeness.</strong> These are illustrations, not a random sample or a new frequency estimate. Use the percentage report for the full sample.</li><li><strong>Times identify minute intervals.</strong> “09:35 minute” means sometime from 09:35:00 up to, but not including, 09:36:00. No exact trigger second or within-candle path is invented.</li><li><strong>The labels describe a level race.</strong> A later retracement after the stop level does not make it a retracement-first case. A stop-level label does not establish an actual order fill.</li><li><strong>The levels stay fixed.</strong> They are anchored to the 09:30 open and first stretch, not a hindsight session extreme. No directional filter or repeated-entry strategy is tested here.</li></ul><p class="small">Source: the same preserved local MNQ history used for the <a href="../mnq-opening-retracement-2026-10-28/report.html">retracement percentage report</a>. Each chart includes its 15 observed candles as a downloadable CSV. <a href="https://databento.com/docs/schemas/ohlcv">Databento’s OHLCV schema</a> documents the minute-bar fields and timestamps.</p></section>
<footer>Real session examples · All times Eastern · Scenario labels use the 10-point retracement</footer></main>
<script>
const stretch=document.querySelector('#stretch'),scenario=document.querySelector('#scenario');
function filterCharts(){{
 let count=0;document.querySelectorAll('.chart-card').forEach(card=>{{
  const match=(stretch.value==='all'||card.dataset.stretch===stretch.value)&&(scenario.value==='all'||card.dataset.scenario===scenario.value);
  card.hidden=!match;if(match)count++;
 }});
 document.querySelector('#result-count').textContent=`Showing ${{count}} chart${{count===1?'':'s'}}`;
 document.querySelector('#empty').hidden=count!==0;
}}
stretch.addEventListener('change',filterCharts);scenario.addEventListener('change',filterCharts);
document.querySelector('#reset').addEventListener('click',()=>{{stretch.value='all';scenario.value='all';filterCharts();}});
</script></body></html>'''
(OUT / 'index.html').write_text(document, encoding='utf-8')
print(json.dumps({'html':str(OUT / 'index.html'),'examples':len(examples),'categories':list(CATEGORIES)}))
