import {readFile,writeFile} from 'node:fs/promises';
const folder='reports/strategy-potential-2026';
const read=async name=>JSON.parse(await readFile(`${folder}/${name}`,'utf8'));
const campaign=await read('campaign.json');
const rows=await read('summary.json');
const exits=await read('orb-exit-analysis.json');
const money=n=>n==null?'Unavailable':n.toLocaleString('en-US',{style:'currency',currency:'USD'});
const pct=n=>`${(100*Math.abs(n)).toFixed(2)}%`;
const ratio=n=>n==null?'Undefined':n.toFixed(2);
const orb=rows.find(r=>r.strategy==='pine-tsmom-orb');
const block=rows.find(r=>r.strategy==='pine-overnight-block');
const drift=rows.find(r=>r.strategy==='pine-overnight-drift');
const lines=[
  '# Strategy analysis: January–August 2026', '',
  '## Main findings', '',
  `- **ORB remains the strongest candidate across the declared historical checks:** ${money(orb.net_pnl)} net profit, ${pct(orb.max_drawdown)} maximum drawdown, ${orb.trades} trades, ${pct(orb.win_rate)} win rate, ${ratio(orb.profit_factor)} profit factor and ${ratio(orb.payoff_ratio)}:1 realized dollar payoff. Doubled costs leave ${money(orb.higher_cost_pnl)}. This is a small sample, not a live-readiness conclusion.`,
  `- **Overnight block improved in this period:** ${money(block.net_pnl)}, ${pct(block.max_drawdown)} drawdown and ${money(block.higher_cost_pnl)} under doubled costs. It remains conditional because earlier failures still count.`,
  `- **Overnight drift remains conditional:** ${money(drift.net_pnl)} and ${pct(drift.max_drawdown)} drawdown. Its earlier drawdown failure has not disappeared.`,
  '- **RSI2 passes the 2026 checks but has only 12 trades**, a 32.2% drawdown, and earlier training/evaluation weaknesses. It moves into the conditional category, not the strongest candidate category.',
  '- **Moving-average and VWAP fail the 35% drawdown ceiling.** VWAP improves sharply from 2025 losses but reaches 35.6% drawdown. The benchmark also exceeds the ceiling.',
  '- **Multi-speed momentum and daily TSMOM crossed below zero simulated equity.** Their drawdowns exceed 100%; the simulator continues without margin liquidation, so later recovery does not make those paths feasible at this capital level.', '',
  '## All strategies', '',
  'NQ futures; $100,000 starting capital per strategy, fixed one contract, existing fees and slippage. Each row is a separate run, not a combined portfolio. Drawdown is measured from marked-equity peaks including starting capital.', '',
  '| Strategy | Net profit | Max drawdown | Trades | Win rate | Profit factor | Realized payoff | Doubled-cost profit | Added-delay profit | Dashboard status |',
  '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |',
  ...rows.map(r=>`| ${r.strategy} | ${money(r.net_pnl)} | ${pct(r.max_drawdown)} | ${r.trades} | ${pct(r.win_rate)} | ${ratio(r.profit_factor)} | ${ratio(r.payoff_ratio)} | ${money(r.higher_cost_pnl)} | ${money(r.delayed_pnl)} | ${r.status} |`), '',
  'Pine event strategies have no added execution-delay simulation. A single winning benchmark trade has no defined average loss, payoff ratio, or profit factor.', '',
  '## ORB exits: why a 2R target does not produce a 2:1 average payoff', '',
  '| Period | Target exits | Scheduled exits | Stop exits | Other exits | Net profit | Realized payoff | Mean net R per trade |',
  '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
  ...exits.map(s=>{
    const n=reason=>s.exit_groups.find(g=>g.exit_reason===reason)?.trades??0;
    return `| ${s.period} | ${n('limit')} | ${n('force-flat window')} | ${n('stop')} | ${s.trades-n('limit')-n('force-flat window')-n('stop')} | ${money(s.net_pnl)} | ${ratio(s.payoff_ratio)}:1 | ${ratio(s.mean_net_r)} |`;
  }), '',
  'The 2R target is only one exit path. Most winning trades in 2025 closed at the scheduled time before reaching that target. Trades also have different initial dollar risks because opening ranges differ. Fees and slippage further reduce realized payoff.', '',
  ...exits.slice(0,2).map(s=>`${s.period}: the five best trades contributed **${money(s.best_5_net_pnl)}**. Removing them arithmetically leaves **${money(s.net_excluding_best_5)}**. This shows profit concentration; it is not a simulated filter or a prediction.`), '',
  '**Exit scheduling issue:** five 2025 trades and two January–August 2026 trades crossed into a later local date. All seven entry dates have no source bars in the 15:45–16:00 flattening window, so that scheduled exit could not run. Six ultimately closed at a stop or target; one used the next-morning safety exit. Exit-reason labels alone therefore undercount overnight exposure. A fixed wall-clock exit needs explicit handling for sessions without that window. The historical rules were preserved for this comparison.', '',
  'The June 19, 2026 trade carried over the weekend and exited at the June 21 reopening below its stop: initial risk $1,010, gross loss $2,105 (2.084R), net loss $2,117.50. A stop does not cap losses at 1R when prices gap. Across the twelve 2026 stop exits, mean gross loss was 1.09R.', '',
  'ORB also weakened after April: May, June and August closed-trade P&L were negative, and February and July had no completed trades. The positive eight-month total should not be read as uniformly strong recent performance.', '',
  'See [ORB_EXITS.md](ORB_EXITS.md), [exit contribution chart](orb-exit-contributions.png), and the full `orb-exits-*.csv` ledgers for exit P&L, normalized risk, holding times, monthly concentration, and long/short attribution.', '',
  '## September 1–3: partial month only', '',
  '| Strategy | Net profit | Trades |', '| --- | ---: | ---: |',
  ...rows.map(r=>`| ${r.strategy} | ${money(r.september_pnl)} | ${r.september_trades} |`), '',
  'These are independent short-window baseline runs starting flat with warmed-up signals and forced final liquidation. They are not appended to August equity and do not change dashboard rankings. The small sample is insufficient to establish a new performance trend. Zero trades, including overnight drift, supplies no trading evidence.', '',
  '## Regime attribution', '',
  'Thresholds use 2025 data only: median trailing trend/volatility over 20 preceding bars in each strategy’s native timeframe. Higher and lower are relative to that threshold, not universally bull/bear. Contributions come from existing continuous paths with unequal exposure. No state-only entry or exit rule was tested.', '',
];
for(const id of ['pine-tsmom-orb','pine-overnight-block','pine-overnight-drift']){
  const {studies}=await read(`${id}.json`);
  lines.push(`### ${id}`,'','| Feature | State | Net P&L contribution | Entries | Mean episode P&L 95% interval |','| --- | --- | ---: | ---: | --- |');
  for(const [feature,study] of Object.entries(studies)) for(const s of study.result.states)
    lines.push(`| ${feature} | ${s.state} | ${money(s.net_pnl)} | ${s.entry_count} | ${s.mean_episode_pnl_interval_95?.map(money).join(' to ')??'Unavailable'} |`);
  lines.push('');
}
lines.push('## Protocol and validation','',...Object.entries(campaign.plan).map(([k,v])=>`- **${k}:** ${v}`),'',
  `Completed nine evaluations with 32 child runs, nine separate September runs and 18 regime studies. All ${campaign.prior_run_ids.length} earlier runs remain available. Source snapshot: \`${campaign.source_hash}\`.`, '',
  'All nine 2025 training replays exactly matched the earlier 2025 baseline P&L, drawdown, trade counts and costs. All parameters remained frozen. Full artifact checksums, trade/equity reconciliation, doubled costs, threshold dates, dashboard values, evaluation charts, downloads and mobile layout were checked. See [browser-validation.json](browser-validation.json).', '',
  `There were ${campaign.preexisting_2026_runs.length} preexisting 2026 runs in the active app ledger when this campaign began. This does not establish that 2026 had never been inspected elsewhere or in deleted/legacy research. Treat it as historical carry-forward evidence, not a certified untouched holdout.`, '',
  '2025 is a full year; the main 2026 period is eight months. Dollar totals are not directly comparable annual rates. This analysis does not resolve continuous-contract roll gaps, exchange-calendar completeness, real execution latency, margin requirements, or future returns.', '',
  '## Next analysis', '',
  'Prioritize ORB session-end handling and nearby-parameter/slippage sensitivity. Any exit-rule variants should be declared and developed on earlier data; 2026 is now inspected and must be treated as such. Then assess whether ORB, block and drift diversify each other using simultaneous marked-equity paths and overlapping positions.', '',
  'Open the local app → **Dashboard** for the January–August results, or **Evaluation & Regimes** and select a `potential-2026-v1` evaluation. September runs remain in **Runs & Compare**. [CSV summary](summary.csv).', '');
await writeFile(`${folder}/OVERVIEW.md`,lines.join('\n'));
console.log(`Wrote ${folder}/OVERVIEW.md`);
