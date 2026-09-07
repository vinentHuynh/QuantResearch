export type CheckState = 'pass' | 'watch' | 'fail' | 'unknown';

export interface Check {
  name: string;
  state: CheckState;
  observed: string;
  limit: string;
  rationale: string;
  response: string;
}

export interface Strategy {
  id: string;
  name: string;
  short: string;
  version: string;
  instrument: string;
  family: string;
  eligibility: 'Eligible' | 'Provisional' | 'Ineligible';
  health: 'OK' | 'Watch' | 'Breach' | 'Unknown';
  reason: string;
  months: number[];
  trades: number[];
  ytd: number;
  drawdown: number;
  underwater: string;
  historicalDrawdown: number;
  volatility: number;
  currentRisk: number;
  proposedRisk: number;
  contracts: string;
  rounding: string;
  margin: number;
  cost: number;
  condition: [string, string][];
  evidence: [string, string][];
  execution: [string, string, string][];
  allocationReason: string;
  restart: string[];
  checks: Check[];
}

const commonEvidence: [string, string][] = [
  ['Development window', 'Sep 2016 – Dec 2021'],
  ['Out-of-sample', 'Jan 2022 – Sep 2026 (4.7 y)'],
  ['Evidence coverage', '9.9 y · 2,494 sessions'],
];

const pass = (name: string, observed: string, limit: string, rationale: string): Check => ({
  name, state: 'pass', observed, limit, rationale, response: 'None.',
});

export const strategies: Strategy[] = [
  {
    id: 'mnq-trend', name: 'MNQ Trend', short: 'MNQ Trend', version: 'v3.1', instrument: 'MNQ', family: 'EWMAC 16/32/64', eligibility: 'Eligible', health: 'Watch',
    reason: 'Evidence and execution pass. Realised volatility is 17.1% against a 12% target, so the sleeve is sized on realised rather than target volatility.',
    months: [1.8, 3.1, -0.9, 0.4, 2.2, -1.7, 0.9, 1.4, 0.6], trades: [3,4,2,3,4,3,2,3,1], ytd: 7.9, drawdown: -1.7, underwater: '34 d', historicalDrawdown: -21.7, volatility: 17.1, currentRisk: 22, proposedRisk: 24, contracts: '1.9 → 2', rounding: '+5%', margin: 5280, cost: 78,
    condition: [['Month to date', '+0.6% · 1 trade'], ['August', '+1.4% · 3 trades'], ['Year to date', '+7.9%'], ['Current drawdown', '−1.7%'], ['Time under water', '34 days'], ['Deepest backtest DD', '−21.7%']],
    evidence: [['Version', 'v3.1 · forecast scalars unchanged'], ...commonEvidence, ['SR gross / net', '+0.47 / +0.46'], ['Deflated SR', '0.41 · 3 variants tested']],
    execution: [['Slippage', '0.9 tk', 'vs 1.0 modelled'], ['Fill rate', '100%', '31 of 31 lots'], ['Lots / yr', '25', 'limit 300'], ['Cost / SR', '0.002', 'limit 0.100']],
    allocationReason: '+2 points after MCL is removed. The sleeve remains below its 26% cap because sizing uses realised volatility.', restart: [],
    checks: [pass('Evidence', 'SR net +0.46 over 9.9 y', '> 0 net, OOS ≥ 3 y', 'Positive net of costs in development and evaluation.'), pass('Live vs backtest', '+7.9% YTD vs +8.8% median', '10–90 pct band', 'Live remains inside the expected band.'), pass('Execution cost', '0.002 SR/yr', '0.100 SR/yr', 'Costs are comfortably within the predeclared limit.'), { name: 'Realised risk', state: 'watch', observed: '17.1% vol (1.42× τ)', limit: '±25% of τ', rationale: 'Known overshoot from the sizing rule.', response: 'Size on realised vol; review above 1.6×.' }],
  },
  {
    id: 'mgc-trend', name: 'MGC Trend', short: 'MGC Trend', version: 'v3.1', instrument: 'MGC', family: 'EWMAC 16/32/64', eligibility: 'Eligible', health: 'OK',
    reason: 'All four checks pass. The per-sleeve cap binds because its backtest drawdown is the deepest in the book.',
    months: [2.6,4.4,1.1,-0.6,3.0,2.1,-1.2,2.8,0.9], trades: [4,5,4,3,5,4,3,4,2], ytd: 15.1, drawdown: -1.2, underwater: '6 d', historicalDrawdown: -38.4, volatility: 16, currentRisk: 24, proposedRisk: 26, contracts: '5.6 → 6', rounding: '+7%', margin: 6600, cost: 96,
    condition: [['Month to date', '+0.9% · 2 trades'], ['August', '+2.8% · 4 trades'], ['Year to date', '+15.1%'], ['Current drawdown', '−1.2%'], ['Time under water', '6 days'], ['Deepest backtest DD', '−38.4%']], evidence: [['Version', 'v3.1'], ...commonEvidence, ['SR gross / net', '+0.64 / +0.63'], ['Deflated SR', '0.58 · 3 variants']], execution: [['Slippage','1.1 tk','vs 1.0 modelled'],['Fill rate','100%','46 of 46 lots'],['Lots / yr','46','limit 300'],['Cost / SR','0.006','limit 0.100']], allocationReason: '+2 points to the 26% cap. Unconstrained risk parity would put 31% here.', restart: [], checks: [pass('Evidence','SR net +0.63 over 9.9 y','> 0 net, OOS ≥ 3 y','Positive in development and out-of-sample.'),pass('Live vs backtest','+15.1% YTD vs +12.4% median','10–90 pct band','Above median and inside the band.'),pass('Execution cost','0.006 SR/yr','0.100 SR/yr','Low turnover keeps costs controlled.'),pass('Realised risk','16.0% vol (1.33× τ)','sizing adjusted','Effective exposure meets target.')],
  },
  {
    id: 'mgc-orb', name: 'MGC ORB Carver', short: 'MGC ORB', version: 'v4.2', instrument: 'MGC', family: 'Opening-range break', eligibility: 'Eligible', health: 'Watch',
    reason: 'Six of the last seven months are negative. The −24.6% drawdown remains inside its −27% one-year reference, so allocation is held flat.', months: [0.7,4.9,-1.3,-0.3,-0.3,-3.3,-2.7,1.6,-0.4], trades: [21,20,21,21,21,21,23,5,2], ytd: -1.4, drawdown: -24.6, underwater: '92 d', historicalDrawdown: -31.2, volatility: 14.8, currentRisk: 14, proposedRisk: 14, contracts: '1.2 → 1', rounding: '−17%', margin: 1100, cost: 210,
    condition: [['Month to date','−0.4% · 2 trades'],['August','+1.6% · 5 trades'],['Year to date','−1.4%'],['Current drawdown','−24.6%'],['Time under water','92 days'],['1-yr reference, 95th pct','−27%']], evidence: [['Version','v4.2 · stop cap raised Feb 2026'],['Development window','Jan 2018 – Dec 2023'],['Out-of-sample','Jan 2024 – Sep 2026'],['Evidence coverage','8.4 y · 1,952 sessions'],['SR gross / net','+0.55 / +0.49']], execution: [['Slippage','1.0 tk','as modelled'],['Fill rate','96.7%','5 range misses'],['Trades / yr','232','limit 400'],['Cost / SR','0.021','limit 0.100']], allocationReason: 'Held at 14%. A Watch prevents an increase; remaining inside the reference range prevents an unsupported cut.', restart: [], checks: [pass('Evidence','SR net +0.49 over 8.4 y','> 0 net, OOS ≥ 2 y','Out-of-sample remains positive.'),{name:'Live vs backtest',state:'watch',observed:'−24.6% DD · 92 d underwater',limit:'−27% depth',rationale:'Inside its one-year block-bootstrap range but close enough for review.',response:'Hold allocation flat; breach past −27%.'},pass('Execution cost','0.021 SR/yr','0.100 SR/yr','Within limit.'),pass('Realised risk','14.8% vol (1.23× τ)','±25% of τ','Within band after sizing.')],
  },
  {
    id: 'mnq-on', name: 'MNQ Overnight', short: 'MNQ Overnight', version: 'v2.4', instrument: 'MNQ', family: 'Clock · 18:00–06:00', eligibility: 'Eligible', health: 'Breach',
    reason: 'Measured execution cost is 0.147 SR/yr against a 0.100 limit. Net Sharpe remains +0.88; the prescribed response is reduction, not pause.', months: [1.1,0.9,1.3,0.7,1,0.4,1.2,0.6,0.2], trades: [81,79,84,80,82,78,83,21,9], ytd: 7.6, drawdown: -0.9, underwater: '12 d', historicalDrawdown: -14.8, volatility: 12.1, currentRisk: 18, proposedRisk: 8, contracts: '0.9 → 1', rounding: '+11%', margin: 2640, cost: 640,
    condition: [['Month to date','+0.2% · 9 trades'],['August','+0.6% · 21 trades'],['Year to date','+7.6%'],['Current drawdown','−0.9%'],['Time under water','12 days'],['Deepest backtest DD','−14.8%']], evidence: [['Version','v2.4 · entry narrowed Mar 2026'],...commonEvidence,['SR gross / net','+1.03 / +0.88'],['Deflated SR','0.71 · 6 variants']], execution: [['Slippage','1.3 tk','vs 1.0 modelled'],['Fill rate','98.1%','19 misses / yr'],['Lots / yr','972','limit 300'],['Cost / SR','0.147','limit 0.100']], allocationReason: '18% → 8%, the largest cost-feasible size. The ten points released remain unused because no equivalent diversifying sleeve exists.', restart: ['Cost per unit of risk under 0.100 SR/yr for a full month.','Realised slippage at or under 1.1 ticks over the same month.','Re-screen at observed cost, then restore in one step if it passes.'], checks: [pass('Evidence','SR net +0.88 over 9.9 y','> 0 net, OOS ≥ 3 y','Strongest evidence in the book.'),pass('Live vs backtest','+7.6% YTD vs +7.1% median','10–90 pct band','Tracking the reference path.'),{name:'Execution cost',state:'fail',observed:'0.147 SR/yr',limit:'0.100 SR/yr',rationale:'The live ticket cost is paid despite being flat half of each day.',response:'Reduce to 8% and cap entries at four per week.'},pass('Realised risk','12.1% vol (1.01× τ)','±25% of τ','On target.')],
  },
  {
    id: 'mcl-trend', name: 'MCL Trend', short: 'MCL Trend', version: 'v3.1', instrument: 'MCL', family: 'EWMAC 16/32/64', eligibility: 'Ineligible', health: 'Breach',
    reason: 'Net Sharpe is negative at all three speeds in development and out-of-sample. The response is removal, not a temporary risk reduction.', months: [-1.4,0.6,-2.2,-1.1,-0.3,-2.6,0.8,-1.9,-0.5], trades: [3,4,3,4,3,4,3,3,1], ytd: -8.6, drawdown: -11.4, underwater: '168 d', historicalDrawdown: -29, volatility: 9.4, currentRisk: 12, proposedRisk: 0, contracts: '5 → 0', rounding: 'flatten', margin: 0, cost: 0,
    condition: [['Month to date','−0.5% · 1 trade'],['August','−1.9% · 3 trades'],['Year to date','−8.6%'],['Current drawdown','−11.4%'],['Time under water','168 days'],['Deepest backtest DD','−29.0%']], evidence: [['Version','v3.1'],...commonEvidence,['SR net by speed','−0.18 / −0.49 / −0.49'],['Instrument screen','fail, both windows']], execution: [['Slippage','1.4 tk','vs 1.0 modelled'],['Fill rate','99.4%','1 partial'],['Lots / yr','36','limit 300'],['Cost / SR','0.008','limit 0.100']], allocationReason: '12% → 0%. Removing it improves portfolio Sharpe with a paired interval that excludes zero.', restart: ['Register a materially different crude sleeve before testing.','Require two years of positive, post-registration net performance.'], checks: [{name:'Evidence',state:'fail',observed:'SR −0.18 / −0.49 / −0.49',limit:'> 0 in both windows',rationale:'Negative before and after costs in both windows.',response:'Remove from allocation.'},pass('Live vs backtest','−8.6% YTD vs −7.9% median','10–90 pct band','Live matches the weak reference.'),pass('Execution cost','0.008 SR/yr','0.100 SR/yr','Cheap, but irrelevant without edge.'),pass('Realised risk','9.4% vol','±25% of τ','Low risk contribution.')],
  },
  {
    id: 'mnq-asia', name: 'MNQ Asia-Fill', short: 'MNQ Asia-Fill', version: 'v1.0', instrument: 'MNQ', family: 'NY close → Asia fill', eligibility: 'Provisional', health: 'Unknown',
    reason: 'The headline rule was selected from 54 variants on the scoring sample. Paper-only results cannot establish live health, so budget is reserved rather than allocated.', months: [0.5,0.8,0.3,0.6,-0.4,0.7,0.2,0.5,0.1], trades: [13,12,14,13,12,13,12,4,2], ytd: 3.3, drawdown: -0.4, underwater: '8 d', historicalDrawdown: -8.1, volatility: 6.4, currentRisk: 0, proposedRisk: 0, contracts: '0 → 0', rounding: '—', margin: 0, cost: 0,
    condition: [['Month to date','+0.1% · 2 paper trades'],['August','+0.5% · 4 paper trades'],['Year to date','+3.3% paper'],['Current drawdown','−0.4%'],['Live history','none'],['Deepest backtest DD','−8.1%']], evidence: [['Version','v1.0'],['Development window','Jan 2020 – Aug 2026'],['Out-of-sample','none'],['Evidence coverage','6.2 y paper · 954 sessions'],['Reality check','p = 0.19 over 54 rules']], execution: [['Slippage','1.0 tk','paper assumption'],['Fill rate','—','paper'],['Trades / yr','154','limit 400'],['Cost / SR','0.014','assumed']], allocationReason: '0%, with 6% reserved. Paper performance is not the blocker; the unpriced search is.', restart: ['Register one rule and cutoff before the next run.','Collect sixty post-cutoff paper or live sessions.','Require walk-forward Sharpe above +0.35.'], checks: [{name:'Evidence',state:'fail',observed:'p = 0.19 over 54 rules',limit:'p < 0.05 or OOS ≥ 2 y',rationale:'The rule was selected after seeing the scoring sample.',response:'Reserve budget; no allocation.'},{name:'Live vs backtest',state:'unknown',observed:'no live fills',limit:'≥ 60 live sessions',rationale:'Paper fills do not evidence reopen execution.',response:'Remain Unknown.'},{name:'Execution cost',state:'unknown',observed:'paper costs only',limit:'0.100 measured',rationale:'Measured costs require live round trips.',response:'Remain Unknown.'},pass('Realised risk','6.4% modelled vol','±25% of τ','Would be sized up if funded.')],
  },
];

export const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep'];
export const bookReturns = [1.3,3.4,-0.5,0,1.4,-0.9,-0.3,1.1,-0.8];

export const correlations = [
  [1,.11,.09,.34,.02,.21], [.11,1,.62,.07,.18,.04], [.09,.62,1,.05,.12,.03],
  [.34,.07,.05,1,-.01,.47], [.02,.18,.12,-.01,1,0], [.21,.04,.03,.47,0,1],
];
export const correlationLabels = ['MNQ-T','MGC-T','MGC-ORB','MNQ-ON','MCL-T','ASIA'];

export const experiments = [
  ['Current weights','reference · 90% deployed','+5.9%','+0.50','—','reference','1.17×','−19.5%','Reference','Enabled'],
  ['Remove MCL Trend','drop failed-evidence sleeve','+6.4%','+0.59','+0.09','[+0.01, +0.18]','0.84×','−16.0%','Supported','Enabled'],
  ['Reduce MNQ Overnight to 8%','cost-feasible size','+5.1%','+0.52','+0.02','[−0.09, +0.13]','0.91×','−17.1%','Inconclusive','Enabled'],
  ['Pause MNQ Overnight','blunter breach response','+4.4%','+0.50','+0.00','[−0.12, +0.12]','0.76×','−15.2%','Inconclusive','Disabled'],
  ['Current weights at 0.7×','smaller-exposure control','+4.2%','+0.50','+0.00','[−0.02, +0.02]','0.82×','−13.8%','Reference','Disabled'],
  ['Proposed policy','checks + risk parity + caps','+6.1%','+0.61','+0.11','[+0.02, +0.21]','0.87×','−14.9%','Supported','Enabled'],
] as const;

export const sources = [
  ['reports/book_daily_returns.csv','trend + overnight book P&L','Live','2,494','05 Sep 2026','1 d','OK'],
  ['reports/book_rule_speed_limit.csv','measured cost vs limit','Backtest','16','04 Sep 2026','2 d','OK'],
  ['reports/mnq_orb_2026_trades.csv','MGC ORB live trades','Live','153','05 Sep 2026','1 d','2 trades missing exit reason'],
  ['reports/mes_overnight_drift/strategy_stats.csv','overnight gross + net','Backtest','12','31 Aug 2026','6 d','OK'],
  ['reports/mnq_asia_fill_strategy/walk_forward.csv','walk-forward + reality check','Paper','54','12 Aug 2026','25 d','no post-registration rows'],
  ['reports/04_correlation_matrix.csv','instrument correlations','Reference','45','29 Jul 2026','39 d','stale — exposure view reads this'],
] as const;
