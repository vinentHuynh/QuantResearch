"""Build the review from newly verified evidence, preserving every campaign row."""
import json
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/workbench-review-2026-09-16'
read = lambda name: json.loads((OUT / name).read_text(encoding='utf-8'))
audit, state, collective, campaign = [read(n) for n in ['artifact-audit.json', 'state-after.json', 'collective-analysis.json', 'campaign.json']]
runs = pd.read_csv(OUT / 'all-runs-audited.csv')
new = runs[runs.id.isin(campaign['runs'].values())].copy()
new.to_csv(OUT / 'new-campaign-results.csv', index=False)
money = lambda x: f'${x:,.2f}'
percent = lambda x: f'{abs(x)*100:.2f}%'
missing = [e for e in state['library']['entries'] if e['status'] == 'Adapter required']
lines = [
    'Strategy and portfolio review — September 16, 2026', '',
    f"The workbench is running at http://127.0.0.1:5173. This review completed {len(new)} additional native runs, refreshed the imported portfolio evidence, and independently audited {audit['verified']} of {audit['runs']} stored runs. The catalog contains {collective['verified_histories']} checksum-verified histories. Seven configurations retain the existing working label; one retains the stricter historical checklist. New profitable baselines have not been promoted automatically.", '',
    '**Scope and import status**', '',
    f"All {len(state['strategies'])} current adapters and {len(state['datasets'])} datasets were already registered. The repo initially exposed 112 original Python/Pine source files; the current library also includes this review's support scripts. {len(missing)} original entries still require adapter work, including rule collections and research studies. They are catalogued with explicit requirements, not falsely labelled as runnable strategies. The historical canonical and SND campaigns were already imported; this review imports the new native baselines through Refresh evidence. No old runs were deleted or replaced.", '',
    'The new campaign fills two gaps: 26 supported MNQ strategy/chart combinations over January 2022–August 2026, and 20 SND market/variant combinations over January–August 2026. Every request was validated before launch. Each independent run uses $100,000 starting capital, one contract, $1.25 commission per side and one tick slippage per side. ORB uses a $2,500 risk cap and at most one contract. Adapter-specific warmup is recorded. The report retains all attempts, zero-trade results and losing paths. These dates were already inspected; this is descriptive historical coverage, not an untouched holdout.', '',
    'Two additional momentum diagnostics address insufficient initialization in the initial 30-day warmup. Its slowest default horizon needs 240 completed bars. Increasing 4h warmup to 90 calendar days changes net from −$6,106.50 to −$3,266; increasing daily warmup to 600 days changes net from $8,897.50 to $10,239 and trade count from 37 to 44. The initial runs remain visible but should not be treated as fully initialized from the first scored bar. Both supplementary runs are tagged sensitivity, retained in Runs & compare, and excluded from additional portfolio sleeves. There are 48 new runs in total.', '',
    '**What the strategy evidence supports**', '',
    '| Family | Assessment | Evidence and limitation |',
    '| --- | --- | --- |',
    '| NQ overnight block, 15m | Strongest frequent-trading research candidate from the earlier frozen campaign | Baseline net: $56,505 in 2024, $60,887.50 in 2025, $71,380 in Jan–Aug 2026. Doubled costs and nearby earlier-period entry-time checks remain positive. Profit factor is modest; overnight, contract-roll and execution risks remain. |',
    '| ES daily moving-average trend | Passes the strictest available historical checklist | Baseline net: $39,510, $22,902.50 and $12,347.50. Cost and supported delay checks pass, but each later period has only 11–14 trades and becomes negative after removing its five best trades arithmetically. |',
    '| ES overnight block | Profitable but timing-sensitive | $23,392.50, $25,757.50 and $28,557.50 in the three later periods. A nearby earlier-entry variant lost $2,090 in the development sensitivity check. |',
    '| NQ filtered TSMOM ORB | Numeric survivor with an execution issue | $25,432.50, $8,265 and $11,552.50. Nine later baseline trades crossed into another local date; the absent flattening-window policy requires a versioned fix. The 2026 sample has 29 trades. |',
    '| Canonical NQ/ES overnight session drift | Supports the same overnight exposure | Passed the previous baseline, doubled-cost and conservative-entry scenarios. It is highly correlated with overnight block, not a separate diversified source. YM drift has very little 2025 cost headroom. |',
    '| Multi-speed momentum and higher-frequency trend | Strong screens did not reliably survive later tests | NQ 4h momentum lost $128,392.50 in Jan–Aug 2026 and crossed zero simulated equity. Profitable trend variants can still exceed the declared drawdown limit. |',
    '| Filtered overnight drift and RSI(2) | Configuration-specific results need caution | All four selected drift markets lost money in 2025. NQ RSI(2) remained profitable but failed drawdown/delay requirements. A positive total is insufficient. |',
    '| VWAP reversion and daily TSMOM | Low priority under the tested default configurations | The earlier four-market screen found no profitable VWAP chart among 12 and no daily-TSMOM configuration passing all screening conditions. New MNQ results below remain visible. |',
    '| SND original / Phase 6 / Phase 7 RVOL | Retain as research; no consistent multi-year winner | The prior 40-stateful-run campaign found zero of 20 next-open market/variant combinations passing every 2024–2026 base/doubled-cost check. Every MNQ/NQ variant lost in 2024. Native 2026 results below extend integration coverage, not multi-year eligibility. |',
    '| Canonical breakout and prior-range fill | Earlier attractive screens failed later periods | Canonical NQ ORB lost $46,842.50 in 2026; CL prior-range fill lost $4,552.50, and NQ fill lost $24,047.50 in 2024. These differ from filtered TSMOM ORB. |',
    '| Asia gap-fill and market profile | Saved evidence is fragile or weak | Existing Asia results fell from +$589.50 to −$95.50 with one-tick target trade-through; the saved nPOC ledger net was −$55. These are earlier saved-ledger checks, not newly simulated native ports. |', '',
    'Sources for those historical findings: [original broad campaign](../all-strategies-all-charts-2026-09-16/REPORT.md), [expanded canonical campaign](../expanded-search-2026-09-16/REPORT.md), and [full SND campaign](../snd-fresh-backtest-2026-09-16/REPORT.md). The fresh artifact audit verifies the current native ledgers; these linked reports retain their original protocols and accounting differences.', '',
    '**New native results — every tested combination**', '',
    'The new MNQ overnight-block runs earn $17,176.50 on 5m and $17,319 on 15m over 2022–August 2026, each with 1,205 trades and roughly 3.4–3.5% marked drawdown at $100,000. The matched 15m passive reference earns more ($26,307.50) with higher drawdown (12.02%). MNQ 5m moving-average trend loses $57,843; all three MNQ VWAP charts lose ($21,384 to $40,869.50). The new evidence reinforces the importance of costs and chart choice without validating a newly chosen optimum.', '',
    'For native SND in January–August 2026, all four MNQ variants are positive ($1,552.50 to $6,357). NQ original and Phase 6 earn $93,920 and $48,752.50, but NQ prior-1m RVOL loses $4,477.50. All CL and YM variants lose; ES is mixed. These observations do not overturn the failed multi-year SND checks. Particularly large original-SND profits depend on native state and fill conventions and should not be substituted for the standalone ledger.', '',
    'MNQ dollar results are micro-contract results and cannot be compared with a full-size NQ book as equal-risk allocations. SND uses the original price-point distances on every market; this is literal transfer, not instrument-calibrated risk. Native SND starts flat, consumes warmup state and uses commission-only limit exits, so it need not reproduce the uninterrupted standalone report.', '',
    '| Strategy / variant | Market | Chart | Warmup days | Net P&L | Marked drawdown | Trades | Net without best five trades | Status |',
    '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |',
]
for _, r in new.sort_values(['strategy', 'symbol', 'timeframe', 'parameters']).iterrows():
    params = json.loads(r.parameters)
    name = r.strategy + (' / ' + params['variant'] if 'variant' in params else '')
    if r.status == 'Succeeded' and r.verified:
        lines.append(f'| {name} | {r.symbol} | {r.timeframe} | {r.warmup_days} | {money(r.net_pnl)} | {percent(r.drawdown)} | {int(r.trades)} | {money(r.without_best_five)} | Verified |')
    else:
        lines.append(f'| {name} | {r.symbol} | {r.timeframe} | {r.warmup_days} | — | — | — | — | {r.status}; see audit |')
active = new[(new.strategy != 'buy-hold') & (new.status == 'Succeeded')]
lines += ['', f"Among the {len(active)} new active-strategy rows, {int((active.net_pnl > 0).sum())} have positive net P&L and {int((active.trades == 0).sum())} have no trades. These rows span different windows and related variants; they are not independent discoveries. Removing the best five trades is an arithmetic concentration diagnostic, not an executable strategy. Full annual marked P&L, costs, profit factor, win rate and expectancy are in [all-runs-audited.csv](all-runs-audited.csv) and [annual-marked-pnl.csv](annual-marked-pnl.csv).", '',
    '**Pause and portfolio analysis**', '',
    'The default seven-book combination represents $700,000 of separate starting capital. Its January 2024–August 2026 marked net is $678,605 and its daily marked maximum drawdown is $111,856.25 (11.76% of the running equity peak). Selection occurred after inspecting the histories. This is a descriptive sum of recorded books, without shared margin, order netting or capital reallocation.', '',
    '| Same closed-trade basis | Net P&L | Maximum drawdown | Recovery factor |',
    '| --- | ---: | ---: | ---: |']
labels = {'off-closed': 'Always on', 'rolling': 'Corrected rolling-loss pause', 'streak': 'Losing-streak pause', 'drawdown': 'Shadow-drawdown pause', 'volatility': 'Volatility scaling'}
for key, label in labels.items():
    r = collective['portfolios'][key]
    lines.append(f"| {label} | {money(r['net'])} | {money(r['drawdown_dollars'])} | {r['recovery_factor']:.2f} |")
lines += ['', 'The corrected default rolling rule gives up $296,547.50 and has slightly worse closed-trade drawdown than always on. None of the three default loss-triggered rules improves this combination. Volatility scaling reduces drawdown and average exposure but also reduces profit and recovery factor; its fractional exposure is an exploratory reweighting. Manual schedules are retrospective user choices and have no optimized or recommended default.', '',
    'The two ES overnight implementations correlate 0.994, the two NQ implementations 0.983, and canonical ES/NQ overnight drift 0.924 on daily marked P&L over the same window. These figures use covered calendar dates, with no recorded change treated as zero. Seven books therefore overstates the number of distinct exposures. A useful next comparison is one implementation per overnight exposure plus the separate trend/ORB rules, with allocation fixed before inspecting new outcomes.', '',
    '![Portfolio pause comparison](pause-comparison.png)', '',
    '**Remaining source imports**', '',
    'The following source entries remain explicitly marked Adapter required. They cannot be faithfully imported merely by renaming a function: some need intrabar orders, synchronized legs, original ETF/MGC/factor data or study workflows. Their existing source files remain accessible in Scripts & library. Historical baseline results from the supported canonical families are already visible in the collective dashboard.', '',
    '| Source | Family | Required work |', '| --- | --- | --- |']
for e in missing:
    lines.append(f"| {e['path']} | {e['family']} | {e['requirements']} |")
lines += ['', '**Verification and deliverables**', '',
    f"Full-artifact verification: {audit['verified']}/{audit['runs']} native runs; {len(audit['failures'])} audit issues. Every successful run's artifact checksums, complete trade sum and terminal equity were checked. {collective['verified_histories']} portfolio histories were independently checksum-verified. The 307 pre-existing run records were compared for exact preservation. Complete records: [artifact-audit.json](artifact-audit.json), [preservation.json](preservation.json), [collective-analysis.json](collective-analysis.json), [protocol.json](protocol.json), and [campaign.json](campaign.json).", '',
    'The updated pause controls, per-book explanations, manual schedule and reduced polling load are described in [APPLICATION_REVIEW.md](APPLICATION_REVIEW.md), together with prioritized application improvements and test limitations. The production build and focused checks pass. The full Python suite still has four documented pre-existing legacy failures/errors; it is not fully green.', '',
    'The main next step is better execution evidence and prospective tracking of frozen candidates, not another unrestricted parameter search. Roll effects, incomplete sessions, cost headroom, sample size, trade concentration, parity and margin remain material. None of these historical results is live-trading approval.', '']
(OUT / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
keys = list(labels)
fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), layout='constrained')
colors = ['#16634f', '#b3412e', '#c77d6e', '#cda290', '#3f7fa3']
for ax, metric, title in [(axes[0], 'net', 'Net P&L'), (axes[1], 'drawdown_dollars', 'Maximum closed-trade drawdown')]:
    values = [collective['portfolios'][k][metric] / 1000 for k in keys]
    ax.barh(list(labels.values()), values, color=colors)
    ax.invert_yaxis()
    ax.set_xlabel('USD thousands')
    ax.set_title(title)
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='x', alpha=.15)
fig.suptitle('Seven recorded books · Jan 2024–Aug 2026 · one copy each\nHistorical replay; related exposures and fixed ledgers', fontsize=12)
fig.savefig(OUT / 'pause-comparison.png', dpi=170)
plt.close(fig)
print(f'Wrote REPORT.md with {len(new)} new results and {len(missing)} explicit migration gaps.')
