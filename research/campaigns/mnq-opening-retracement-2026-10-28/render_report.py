"""Render the saved opening-retracement percentages without estimating results."""
from pathlib import Path
import html
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'reports/mnq-opening-retracement-2026-10-28'
summary = json.loads((OUT / 'summary.json').read_text(encoding='utf-8'))
protocol = json.loads((OUT / 'protocol.json').read_text(encoding='utf-8'))
rows = summary['summary_rows']
assert len(rows) == 27
PERIODS = {
    'all_history': ('All history · 2019–2026', 'May 6, 2019–September 3, 2026'),
    'earlier_2019_2023': ('Earlier · 2019–2023', 'May 6, 2019–December 31, 2023'),
    'recent_2024_2026': ('Recent · 2024–2026', 'January 1, 2024–September 3, 2026'),
}

def get(period, distance, retracement):
    selected = [r for r in rows if r['period'] == period and r['threshold_points'] == distance and r['retracement_points'] == retracement]
    assert len(selected) == 1
    return selected[0]

def matrix(period, metric):
    parts = ['<div class="table-wrap"><table class="matrix"><thead><tr><th scope="col">Opening stretch</th>']
    parts += [f'<th scope="col">{r}-point<br>retracement</th>' for r in [5, 10, 15]]
    parts.append('</tr></thead><tbody>')
    for d in [40, 60, 80]:
        n = get(period, d, 5)['triggered_sessions']
        parts.append(f'<tr><th scope="row">{d} points<span>{n:,} events</span></th>')
        for r in [5, 10, 15]:
            data = get(period, d, r)
            low, high = data[f'{metric}_certain_pct'], data[f'{metric}_possible_pct']
            a, b = data[f'{metric}_certain_count'], data[f'{metric}_possible_count']
            assert 0 <= low <= high <= 100
            parts.append(f'<td><strong>{low:.1f}–{high:.1f}%</strong><span>{a:,}–{b:,} of {n:,}</span></td>')
        parts.append('</tr>')
    return ''.join(parts) + '</tbody></table></div>'

def coverage(period):
    parts = ['<div class="table-wrap"><table class="coverage"><thead><tr><th scope="col">Stretch</th><th scope="col">Reached</th><th scope="col">Frequency</th><th scope="col">Not reached</th></tr></thead><tbody>']
    for d in [40, 60, 80]:
        r = get(period, d, 5)
        parts.append(f'<tr><th scope="row">{d} points</th><td>{r["triggered_sessions"]:,}</td><td>{r["trigger_rate_pct"]:.1f}%</td><td>{r["no_trigger_sessions"]:,}</td></tr>')
    return ''.join(parts) + '</tbody></table></div>'

def periods(metric):
    chunks = []
    for period, (_, dates) in PERIODS.items():
        hidden = '' if period == 'all_history' else ' hidden'
        chunks.append(f'<div class="period-panel" data-period="{period}"{hidden}><p class="period-label">{dates}</p>{matrix(period, metric)}</div>')
    return ''.join(chunks)

coverage_panels = []
for period, (_, dates) in PERIODS.items():
    r = get(period, 40, 5)
    hidden = '' if period == 'all_history' else ' hidden'
    coverage_panels.append(f'<div class="period-panel" data-period="{period}"{hidden}><p class="period-label">{dates} · {r["cash_sessions"]:,} complete sessions</p>{coverage(period)}</div>')

options = ''.join(f'<option value="{key}">{name}</option>' for key, (name, _) in PERIODS.items())
data = summary['data']
assert data['included_sessions'] == 1841
assert data['first_session'] == '2019-05-06' and data['last_session'] == '2026-09-03'
first5 = [get('all_history', d, 5)['any_retracement_certain_pct'] for d in [40, 60, 80]]
headline = f'A 5-point retracement is certain in {min(first5):.1f}%–{max(first5):.1f}% of the full-history stretch events, depending on the opening distance. Smaller retracements were common, but the candles often leave their timing unresolved.'
verified = '--verified' in sys.argv
verification = ('The calculations and event-count summaries passed independent review. This remains a descriptive price-event study, not a strategy backtest.' if verified else 'Independent review of the calculations and event-count summaries is pending. This is a descriptive price-event study, not a strategy backtest.')
exclusions = ', '.join(x['date'] for x in data['excluded_sessions'])

css = '''
:root{--ink:#183747;--muted:#59717c;--teal:#157d73;--line:#dce6e9;--pale:#edf6f4}*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:#edf2f4;color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}main{max-width:1070px;margin:32px auto;padding:0 22px 28px}header{background:var(--ink);color:white;border-radius:14px 14px 0 0;padding:30px 34px}.eyebrow{font-size:11px;font-weight:750;letter-spacing:.13em;color:#a6d9d2}h1{font-size:35px;line-height:1.18;letter-spacing:-.025em;margin:10px 0 12px}header p{margin:0;max-width:850px;color:#e1ebee}.stamp{font-size:12px;color:#a6d9d2;margin-top:16px}article{background:white;border:1px solid var(--line);border-top:0;padding:28px 34px;border-radius:0 0 14px 14px;box-shadow:0 8px 24px #1c36400a}h2{font-size:23px;line-height:1.3;margin:7px 0 12px}p{margin:10px 0}.small{font-size:13px;line-height:1.6;color:var(--muted)}.lead{background:var(--pale);border-left:4px solid var(--teal);padding:17px 20px;margin-bottom:22px;font-weight:600}.controls{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:16px 18px;border:1px solid var(--line);border-radius:8px;margin-bottom:22px}.controls label{font-weight:700}.controls small{display:block;color:var(--muted);font-size:12px}select{font:inherit;color:var(--ink);background:white;border:1px solid #a6bdc5;border-radius:6px;padding:10px 12px;max-width:100%}.section-label{font-size:11px;font-weight:750;letter-spacing:.1em;color:var(--teal)}section+section{border-top:1px solid var(--line);margin-top:28px;padding-top:25px}.period-label{font-size:12px;color:var(--muted);margin-top:15px}.table-wrap{overflow-x:auto;margin:12px 0 16px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}thead th{background:var(--ink);color:white;text-align:left;font-size:12px;line-height:1.35}th,td{padding:12px 14px}tbody th{font-size:15px;font-weight:700;text-align:left}tbody td{font-size:14px}tbody tr{border-bottom:1px solid var(--line)}tbody tr:nth-child(even){background:#f2f6f7}.matrix td strong{font-size:21px;line-height:1.25;font-weight:700;white-space:nowrap}.matrix span{display:block;font-size:11px;font-weight:400;color:var(--muted);margin-top:6px}.matrix tbody th{width:22%}.coverage th,.coverage td{font-size:14px}.legend{font-size:13px;color:var(--muted);line-height:1.6}.example{border:1px solid var(--line);border-radius:8px;padding:15px 18px;margin-top:15px;font-size:14px}.distances{display:flex;flex-wrap:wrap;gap:8px;margin:15px 0}.distances span{background:#edf3f5;border-radius:5px;padding:6px 12px;font-size:13px}.methods{padding-left:22px}.methods li{padding-left:4px;margin:10px 0}.downloads{display:flex;flex-wrap:wrap;gap:10px;margin-top:17px}.downloads a{border:1px solid #bdd4d7;border-radius:6px;padding:8px 12px;text-decoration:none;font-size:13px}a{color:var(--teal)}details{border-top:1px solid var(--line);padding-top:17px;margin-top:22px}summary{cursor:pointer;font-weight:650}footer{text-align:center;font-size:12px;color:var(--muted);padding:18px 3px 0}@media(max-width:730px){main{margin:14px auto;padding:0 12px 20px}header{padding:25px 22px}h1{font-size:28px}article{padding:22px 18px}h2{font-size:21px}.controls{display:block}.controls select{width:100%;margin-top:10px}.matrix td strong{font-size:14px}.matrix span{font-size:10px}.matrix th,.matrix td{padding:10px 6px}.matrix tbody th{font-size:13px;width:23%}thead th{font-size:11px}.coverage th,.coverage td{font-size:12px;padding:10px 7px}}@media(max-width:390px){.matrix td strong{font-size:12px}.matrix th,.matrix td{padding:9px 4px}.matrix span{font-size:9px}}@media print{body{background:white;font-size:10pt}main{max-width:none;padding:0;margin:0}header{border-radius:0;padding:18px 22px}article{border:0;box-shadow:none;padding:20px 22px}h1{font-size:25pt}h2{font-size:15pt}.controls{display:none}.matrix td strong{font-size:15pt}.lead,.table-wrap,.example{break-inside:avoid}.small,.legend{font-size:9pt}footer{font-size:8pt}@page{size:letter;margin:12mm}}
'''

document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MNQ Opening Retracement Percentages</title><style>{css}</style></head>
<body><main><header><div class="eyebrow">MNQ / OPENING 15-MINUTE RESEARCH</div><h1>How often does the opening stretch retrace?</h1><p>After the first 40-, 60- or 80-point move from the open, how often does price give back 5, 10 or 15 points before 9:45 a.m. Eastern?</p><div class="stamp">1,841 complete sessions · May 6, 2019–September 3, 2026 · Report saved October 28, 2026</div></header>
<article>
<div class="lead">{headline}</div>
<div class="controls"><div><label for="period">Choose the historical period</label><small>Updates both retracement tables and the stretch-frequency table.</small></div><select id="period">{options}</select></div>
<section id="any-retracement"><div class="section-label">01 / DID IT RETRACE?</div><h2>A retracement at any time before 9:45</h2><p>Counts the specified move back toward the opening price after the first stretch, even if price first continued farther outward.</p>{periods('any_retracement')}<p class="legend"><strong>Read each range as certain–possible.</strong> The lower percentage counts an event under every price ordering compatible with the minute candles; the upper includes it under at least one compatible ordering. Possible includes certain. These are bounds on the observed history, <strong>not confidence intervals or guarantees about future percentages</strong>.</p></section>
<section id="retracement-first"><div class="section-label">02 / DID IT RETRACE FIRST?</div><h2>A retracement before a farther outward move</h2><p>This stricter question requires the retracement to happen before price reaches the continuation level. Both levels are measured from the fixed stretch level. Only observations before 9:45 count; the continuation level need not be reached if the retracement occurs first.</p><div class="distances"><span>40-point stretch → 20 farther out</span><span>60-point stretch → 30 farther out</span><span>80-point stretch → 40 farther out</span></div>{periods('retracement_first')}<div class="example"><strong>Why the two tables differ:</strong> with an opening price of 20,000, an upper 40-point stretch is 20,040. A 10-point retracement reaches 20,030; the continuation level is 20,060. If price reaches 20,060 first and later 20,030, it counts in the first table but not the second.</div><p class="small">Every percentage uses all stretch events in its row, including unresolved cases. The continuation distance changes by row, so this comparison does not select a best stretch. These percentages are price-event frequencies, not a strategy win rate.</p></section>
<section id="coverage"><div class="section-label">03 / HOW OFTEN DID THE SETUP OCCUR?</div><h2>Stretch frequency and sample size</h2><p>A day that never reaches the chosen stretch is excluded from the retracement denominator and shown separately below.</p>{''.join(coverage_panels)}<p class="small">The same day can reach more than one stretch. The rows overlap and should not be added together. Earlier and recent periods have already appeared in prior research; the selector is a descriptive comparison, not a fresh validation sample.</p></section>
<section id="method"><div class="section-label">04 / WHAT THESE NUMBERS MEASURE</div><h2>One first stretch per day, with a fixed cutoff</h2><ul class="methods"><li><strong>Fixed levels:</strong> the reference is the observed 9:30 minute open. Each stretch is evaluated separately, using its first upper or lower crossing that day. There is no wait for a candle close and no directional filter.</li><li><strong>Only the first 15 minutes:</strong> the study uses 9:30 through 9:44 candles. All prices at or after 9:45 are excluded. A later first stretch has less time left to retrace.</li><li><strong>Ordering remains uncertain:</strong> a favorable extreme in the trigger candle may precede the stretch. The analysis retains all compatible event orders, revisits and possible first directions, rather than choosing one assumed candle path.</li><li><strong>Levels are not fills:</strong> breaches that gap past a level remain in the sample. Outcomes are measured against nominal fixed levels, not unknown execution prices or a later session high or low. This is not the repeated-entry opening-scalp test.</li></ul><details><summary>Data details, exclusions and downloads</summary><p class="small">Every included session has all 15 observed minute bars and one instrument. No missing bar is filled. Three incomplete sessions were excluded: {exclusions}. Removing disruption days can understate extreme behavior. The 40-point sample contains three sessions with ambiguous first direction; those remain in the overall bounds. The 60- and 80-point samples have no such first-direction ambiguity.</p><p class="small">The local series is an unadjusted continuous MNQ dataset; the original vendor request has not been reconstructed. <a href="https://databento.com/docs/schemas/ohlcv">Databento’s OHLCV schema</a> explains the bar timestamps and price fields. It does not verify this local dataset or these research results. Exact trigger trade times and tradable fills are not identified by minute candles.</p><p class="small">Yearly and direction exports flag samples below 100 events. Zero-event cells are retained with no defined percentage; they do not mean a 0% retracement rate. The separate ambiguous-direction group has only three events and is too small to interpret as a stable percentage. Neither table evaluates a directional filter, repeated entries, execution or profitability.</p><div class="downloads"><a href="events.csv" download>Event ledger · CSV</a><a href="percentages.csv" download>All percentages · CSV</a><a href="yearly_percentages.csv" download>Yearly detail · CSV</a><a href="direction_percentages.csv" download>Direction detail · CSV</a><a href="protocol.json" download>Study definitions · JSON</a><a href="excluded_sessions.csv" download>Excluded sessions · CSV</a></div></details><p class="small" id="verification-status">{verification}</p></section>
</article><footer>Historical price-event frequencies · All times Eastern · No strategy win rate claimed</footer></main>
<script>
document.querySelector('#period').addEventListener('change',function(){{
  document.querySelectorAll('.period-panel').forEach(panel=>{{panel.hidden=panel.dataset.period!==this.value;}});
}});
</script></body></html>'''
(OUT / 'report.html').write_text(document, encoding='utf-8')
print(json.dumps({'html':str(OUT / 'report.html'),'verified':verified,'periods':len(PERIODS),'source_rows':len(rows)}))
