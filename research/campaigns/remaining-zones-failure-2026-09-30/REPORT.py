"""Create the final reviewable screen report from reconciled saved evidence."""
from pathlib import Path
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

folder = Path(__file__).resolve().parent
rows = json.loads((folder / 'summary.json').read_text())
campaign = json.loads((folder / 'campaign.json').read_text())
evaluation = json.loads((folder / 'round-100-evaluation.json').read_text())
names = {'swing-1h': '1-hour confirmed swing', 'swing-4h': '4-hour confirmed swing',
         'opening-15m': '15-minute opening range', 'opening-30m': '30-minute opening range',
         'departure-swing': 'Strong-departure swing', 'role-flip': 'Support/resistance flip',
         'rolling-20': '20-bar range extremes', 'round-100': '100-point round numbers',
         'daily-pivots': 'Classic daily S1/R1 pivots', 'generic-prior-bar': 'Previous-bar sweep benchmark'}
order = list(names)
development = {r['detector']: r for r in rows if r['stage'] == 'development'}
round_dev = development['round-100']
round_tests = sorted([r for r in rows if r['stage'] == 'evaluation-Test'], key=lambda r: r['fee'])
later = next(r for r in rows if r['stage'] == 'later-round-100')
assert not later['eligible']
assert all(r['eligible'] for r in round_tests)
assert len(development) == 10 and len(rows) == 14
assert not any(r['stage'].startswith(('nearby', 'later-stress')) for r in rows)

fig, axes = plt.subplots(3, 1, figsize=(14, 11), constrained_layout=True)
for ax, selected, title in [(axes[0], [round_dev], 'Development: 2022-2024'),
                            (axes[1], round_tests, 'Chronological evaluation: 2025'),
                            (axes[2], [later], 'Later-period continuation: 2026 through September 28')]:
    for row in selected:
        equity = pd.read_csv(folder / 'runs' / row['run_id'] / 'equity.csv')
        x = pd.to_datetime(equity.timestamp, utc=True)
        label = 'Baseline costs' if row['fee'] == 2.5 else 'Doubled costs'
        ax.plot(x, equity.equity - 100000, label=label, linewidth=1.1)
    ax.axhline(0, color='#6b7280', linewidth=0.8)
    ax.set_title(title)
    ax.set_ylabel('Marked net P&L ($)')
    ax.grid(alpha=0.2)
    ax.legend(loc='best')
fig.suptitle('Fixed 100-point round-number failure test\nEach stage starts flat with $100,000; panels are separate simulations', fontsize=15)
fig.savefig(folder / 'round-number-equity.png', dpi=140)
plt.close(fig)

money = lambda value: f'{"+" if value >= 0 else "-"}${abs(value):,.0f}'
lines = [
 '# Remaining support/resistance detectors: completed failure-test screen', '',
 '**No candidate survived the full declared sequence.** All seven remaining families were screened under common mechanics. Fixed 100-point round numbers were the only development survivor and passed the 2025 baseline/doubled-cost evaluation, but the unchanged 2026 continuation lost money and failed the profit-factor gate. Stop advancement; no 2026 cost-stress or nearby-width search was launched after that decisive failure.', '',
 '## Initial development screen', '',
 'NQ, January 1, 2022 through December 31, 2024; 15-minute bars, regular-hour entries, one contract, $100,000 initial capital. Figures include $2.50 commission and one tick of slippage per side ($15 per completed trade). Nine detector candidates across seven families plus one descriptive benchmark were declared before inspecting outcomes.', '',
 '| Candidate | Trades | Net P&L | Net PF | Marked drawdown | Development disposition |',
 '| --- | ---: | ---: | ---: | ---: | --- |']
for mode in order:
    row = development[mode]
    disposition = 'Passed; advanced unchanged' if row['eligible'] else row['disposition']
    lines.append(f"| {names[mode]} | {row['metrics']['trades']} | {money(row['metrics']['net_pnl'])} | {row['profit_factor']:.2f} | {-100*row['metrics']['max_drawdown']:.2f}% | {disposition} |")
lines += ['',
 'Sparse means below the frozen operational floor of 100 trades, not proof of no edge. Negative economics remain visible for sparse candidates. Support/resistance flips were positive cumulatively but missed PF>=1.05 and had only one profitable year. Strong-departure swings and 20-bar extremes failed with larger samples; the latter also exceeded the 35% drawdown ceiling.', '',
 'All initial attempts were retained. Prior-day extremes (42 trades, +$17,010), overnight extremes (61, +$7,830), and the consolidation box (159, -$13,200) remain preserved in their separate preceding campaigns. Their daily lifetimes, visit policies or cluster widths differ; they are descriptive historical comparisons, not members of this common-engine batch.', '',
 '## Round-number candidate: stage progression', '',
 '| Stage | Trades | Net P&L | Net PF | Marked drawdown | Decision |',
 '| --- | ---: | ---: | ---: | ---: | --- |']
for label, row in [('2022-2024 development', round_dev),
                   ('2025 baseline', round_tests[0]), ('2025 doubled costs', round_tests[1]),
                   ('2026 Jan 1-Sep 28 baseline', later)]:
    lines.append(f"| {label} | {row['metrics']['trades']} | {money(row['metrics']['net_pnl'])} | {row['profit_factor']:.2f} | {-100*row['metrics']['max_drawdown']:.2f}% | {'Passed stage gates' if row['eligible'] else 'Failed; stop'} |")
lines += ['',
 'Development annual net P&L was +$8,230 in 2022, +$9,270 in 2023 and +$8,405 in 2024. The Workbench evaluation used one unchanged candidate, 366 training days in 2024 followed by 365 test days in 2025. Its record succeeded with outcome **Meets criteria**; independent checks also passed the campaign\'s stricter positive-P&L and PF>1 requirements for both scenarios.', '',
 'The 2026 baseline failed positive net P&L and PF>1. Its 33.09% drawdown was below the 35% ceiling, but that does not offset the profit failures. Doubled 2026 costs and nearby widths were deliberately not launched. The later loss does not prove that all round-number strategies fail; it stops this fixed candidate under this protocol.', '',
 'The latest dataset extends into a partial September 29 session. September 28 was selected before outcomes as the last complete calendar day; no partial tail was scored.', '',
 f"![Separate round-number stage equity curves]({(folder / 'round-number-equity.png').as_posix()})", '',
 '## Uncertainty and comparison limits', '',
 f"The round-number development expectancy was ${round_dev['expectancy']:.2f} per trade. Its seeded day-cluster 95% interval was approximately ${round_dev['day_cluster_expectancy_95'][0]:.0f} to ${round_dev['day_cluster_expectancy_95'][1]:.0f}; it includes zero. The largest winner was {money(round_dev['best_trade'])}, about 42% of net development profit, and the ten largest winners supplied 28.4% of winning P&L. Positive yearly totals did not establish stable expectancy.", '',
 'Intervals are 5,000 seeded resamples of whole occupied Chicago entry days, recalculating net P&L divided by trade count. They are pointwise exploratory estimates, not adjusted for searching ten candidates and not protection against dependence across days. Intervals, occupied-day counts and concentration are retained for every run in summary.json. Later-period intervals also span zero.', '',
 'The previous-bar benchmark lost $36,985 on 2,288 trades, net PF 0.94. It is an executable descriptive reference, not a matched-location control: trade populations, occupancy and market conditions differ. No claim that the round-number location causally adds value is established by comparing these totals.', '',
 'Every date is previously inspected retrospective history. The Workbench evaluation preserves earlier overlapping runs. The 2025 sequence is chronological later history, not certified untouched data, and the 2026 extension remains historical research.', '',
 '## Common mechanical interpretation', '',
 'All ten candidates used the same frozen +/-0.10 formation ATR zones, 80 subsequent selected-bar lifetime, formation-close arming, no formation-bar entry, first armed physical-touch retirement (including shallow and overnight touches), and deterministic active-price deduplication. Overlapping distinct levels are retained; at most one entry per bar and one position are permitted.', '',
 'The signal must open on the approach side, wick one tick beyond the far edge and close inside the small zone. A stronger reclaim that closes entirely beyond the near edge is excluded. Entry is the next contiguous 15-minute open and expires if absent. Stop is one tick beyond the sweep extreme; the preserved exit is the 20th entry-inclusive chart-bar close, with the exceptional-move target unchanged. New entries occur 08:30-15:00 Chicago, capped by the frozen holiday calendar; positions can continue afterward.', '',
 'Higher-timeframe candles require all expected observed 15-minute candles and activate only after strict two-left/two-right pivot confirmation. Opening ranges activate after their completed window. Departure requires 1.5 confirmation ATR; flips require a later break of the original far edge by one tick. Rolling levels use only preceding completed candles. Classic daily S1/R1 uses the previous complete scheduled regular session. The complete frozen definitions are in PROTOCOL.md.', '',
 '## Verification, provenance and retained limitations', '',
 '- Ten focused detector tests passed. The first deterministic December 2021 formation per candidate was visually inspected before scored launch; all source-release checks passed. No preview selection used strategy P&L.',
 '- Validate & preview ran before every launch. Development warmup required 142 completed bars and had 1,928; workers reported sufficient coverage. The production build passed with its bundle-size advisory. Unrelated workspace edits were preserved.',
 '- All 14 runs succeeded. All five artifact checksums and byte counts per run were independently checked; full trade P&L and costs reconcile to marked equity. Independently recalculated P&L, trade count, observations and drawdown match Workbench. Entry hours and expected per-trade friction were checked.',
 '- Source prices are unadjusted continuous contracts; rolls can alter detector structure and P&L. No minute or tick completeness claim follows from observed 15-minute continuity. No forward fill, historical order-book replay or margin model is used. Stops use one-minute OHLC with conservative ordering.',
 '- Additional event-entry delay is unavailable. No market transfer, live approval, automatic Watchlist promotion or matched generic-location study was performed.', '',
 f"Evaluation ID: `{evaluation['id']}`. Dataset: `3b9114199a2f6f0e51b70a63edc43de00940ae5df8d047b3aaa6aa8424aac9f1-v1`; SHA-256 `67092a9b6201747c46ae08029068fd03b42c5def68339ac2434dba78a77386c7`.", '',
 '## Complete run ledger', '',
 '| Detector | Stage | Run ID |', '| --- | --- | --- |']
for row in sorted(rows, key=lambda r: (r['stage'] != 'development', order.index(r['detector']), r['start'], r['fee'])):
    lines.append(f"| {names[row['detector']]} | {row['stage']} | `{row['run_id']}` |")
lines += ['', 'Execution source hashes: ' + ', '.join('`' + h + '`' for h in sorted({r['source_hash'] for r in rows})) + '.', '',
 'Saved beside this report: PROTOCOL.md, REVIEW.md, detection-review.json, campaign.json, summary.json, launch requests and previews, and the completed evaluation record. Complete verified copies live in runs/<run-id>/; primary Workbench records remain available.', '',
 'The next useful research step is a formation/trigger diagnostic and matched-event comparison, if further research is requested. Any broader reclaim or repeat-touch interpretation needs a new bounded protocol; the failed 2026 result must remain visible rather than being tuned away.']
(folder / 'RESULT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps({'report': str(folder / 'RESULT.md'), 'runs': len(rows), 'evaluations': len(campaign['evaluations']),
                  'final_round_decision': later['disposition']}))
