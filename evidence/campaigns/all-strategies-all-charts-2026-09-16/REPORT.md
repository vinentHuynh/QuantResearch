Strategy research report — all markets and supported timeframes

104/104 screening combinations analyzed. 13 frozen strategy/market selections; 4 pass all later numeric checks. Campaign completed 2026-09-16T14:35:44.766Z.

**Four numeric survivors; two have fewer unresolved issues**

All 104 screening combinations, 279 total backtests, 26 chronological evaluations and 26 regime studies completed without execution failures. Four of the 13 frozen selections passed every later numeric scenario. Prioritize NQ overnight block on 15-minute bars and ES moving-average trend on daily bars for further validation. ES overnight block on 5-minute bars also passes later metrics but has a negative nearby entry-time variant. NQ TSMOM ORB on 5-minute bars passes the metrics but needs session-exit review. The other nine frozen selections fail the stated later criteria. These are research priorities, not live allocation approvals.

**First priority: NQ overnight block, 15 minutes**

The frozen rule schedules entry at 17:00 and exit at 06:00 New York time, with fills subject to the next available bar and exchange reopening. Baseline net profits are $56,505 in 2024, $60,887.50 in 2025 and $71,380 in January–August 2026. Respective maximum drawdowns are 18.30%, 28.55% and 26.10%. Doubled-cost profits remain $53,280, $57,675 and $69,230. Trade counts of 258, 257 and 172 provide more observations than the daily trend candidate. Both declared 2022–2023 entry-time variants are profitable. Removing the five best trades arithmetically still leaves positive net profit in each later year ($22,272.50, $20,835 and $24,597.50), although this is not a different executable rule. Its profit factor is modest at 1.29–1.39. All three descriptive bootstrap intervals include zero, so the evidence does not establish statistical certainty. Event-order delay remains untested, and overnight exposure and contract-roll accounting need explicit validation.

**Second priority: ES daily moving-average trend**

The current 20-bar moving-average configuration produces $39,510, $22,902.50 and $12,347.50 in 2024, 2025 and January–August 2026, with drawdowns of 7.26%, 19.84% and 18.71%. Every doubled-cost and extra-bar-delay scenario passes; the 2026 delayed result is $9,585 with 18.84% drawdown. Both training-period lookback variants remain profitable. However, each later period has only 11–14 trades, and removing the best five trades makes each period negative. Its apparent robustness comes from a small number of trend captures, not frequent independent successes. Recheck fills and daily-session construction, then collect prospective evidence with the parameters frozen.

**Conditional priorities: ES overnight block and NQ ORB**

ES overnight block produces $23,392.50, $25,757.50 and $28,557.50 in the three later periods, with baseline drawdown below 19% and positive doubled-cost results. The earlier-entry sensitivity variant loses $2,090 in 2022–2023, so entry-time robustness remains unresolved. NQ ORB produces $25,432.50, $8,265 and $11,552.50, with drawdown near 10–12%. Nine actual later baseline trades cross into a later New York date: two in 2024, five in 2025 and two in 2026. Those trades contribute $3,570, $162.50 and minus $3,645 respectively; their existence cannot be dismissed because the aggregate strategy is profitable. The 2026 ORB result contains only 29 trades and becomes negative after removing its five best trades. Correct and separately version missing-window/session-end handling, preserve this original ledger, and retest the revised execution rules before promoting it.

**What to deprioritize**

NQ four-hour multi-speed momentum is the clearest screening false positive: it earns $217,872.50 in the screen but loses $7,300 in 2024 and $128,392.50 in January–August 2026. The latter path reaches 124.29% drawdown and negative equity; a real account could not continue as this simulation does. NQ four-hour moving-average trend remains profitable in later baseline tests but exceeds 50% drawdown in both 2025 and 2026, and its delayed 2025 result loses $41,620. NQ daily RSI(2) has positive baseline profits but 49.59% drawdown in 2025 and 57.91% under the 2026 delay stress. YM daily moving-average trend loses $5,550 in 2026; a profitable delayed variant does not rescue the frozen baseline. All four selected filtered overnight-drift markets lose money in 2025; CL also remains negative in 2026. YM overnight block's small $2,337.50 baseline profit in 2025 becomes an $875 loss at doubled costs. None warrants a timeframe substitution based on these already inspected later results.

**Whole-library findings and benchmark context**

Of 80 active-strategy screening combinations, 41 are net profitable. Eighteen additional combinations have positive gross P&L but lose after costs; 17 active paths cross zero simulated equity. VWAP reversion is negative before and after costs on all 12 supported charts, and no daily TSMOM rebalance configuration passes the screen. ORB transfers poorly across markets: only NQ is net profitable among the four ORB screens. All 24 passive screening references are profitable, which is useful context for long-biased strategies. Each of the four numeric survivors earns less absolute profit than its matched passive reference in every later period, while showing lower marked drawdown. For example, NQ overnight block in 2025 earns $60,887.50 with 28.55% drawdown versus the matched passive reference's $83,302.50 with 95.51% drawdown. These are one-contract, unadjusted continuous-futures simulations; the comparison demonstrates a profit/risk tradeoff, not proven risk-adjusted alpha or an investable roll-neutral benchmark.

**Regime evidence and remaining uncertainty**

In 2026, $64,257.50 of NQ overnight block's $71,380 comes from higher trailing-volatility states; both its volatility states and both signed-trend states contribute positively. ES overnight block contributes positively in both volatility states. ES daily trend and NQ ORB have positive higher-volatility contributions and negative lower-volatility contributions. For ORB, the lower-volatility state has only four entries, which is inadequate evidence for a new exclusion rule. These studies attribute the existing path using preceding native-timeframe bars and 2025-calibrated thresholds; they do not test an executable regime filter. The profitable survivors' descriptive daily bootstrap intervals all include zero. Contract-switch gaps also contribute materially to several trend/overnight paths. Explicit contract rolls, margin constraints, missing-session classification and prospective observations remain necessary. No combined portfolio or diversification claim is established by these separate tests.

**Coverage boundary and concrete next work**

The campaign covers every supported timeframe of all nine currently runnable workbench adapters across all four newly registered markets: CL, ES, NQ and YM. The screen scores 2018–2023; later checks score 2024, 2025 and January–August 2026. Earlier imported history supplies warmup where needed; September's three partial-history days are excluded. The inventory accounts for 109 original files, including 48 entries explicitly requiring adapters and an existing SND Python engine outside this workbench campaign. Those sources were inventoried, not falsely reported as freshly backtested. Next: validate roll-aware and margin-aware execution for the two primary candidates; resolve the two conditional candidates' execution/sensitivity issues; register and port missing families with their actual rules and required data; then begin prospective paper tracking with frozen settings. Any new filters, sizing or parameter changes need separately recorded experiments. The prior workbench-status report records software test coverage and its four unresolved legacy test failures/errors; this campaign's checks validate these research artifacts, not a claim that the entire repository test suite is green.

Independent verification covered 279 campaign runs, 26 chronological evaluations, 26 regime studies and 30 matching passive-reference runs. Execution failures: 0; research-analysis errors: 0. See [validation record](validation.json).

Of 80 active-strategy combinations, 41 were profitable after costs. 18 had positive gross P&L but lost money after fees and slippage. 17 crossed zero simulated equity; the engine continued without margin liquidation, so those paths are infeasible at the stated starting capital. The 24 passive reference screens are excluded from these counts.

The screen uses 2018–2023 only. Each selected strategy/market keeps its chosen timeframe and original parameters for 2024, 2025 and January–August 2026. Every supported timeframe was included; only one eligible timeframe per strategy/market advances, to avoid counting closely related timeframes as separate discoveries. Selection is fixed before the later campaign results. Older repository work has already inspected some later history, so this is chronological historical research, not a certified untouched holdout.

This new campaign uses the current adapter defaults, with explicit fixed-contract sizing and the ORB risk-cap overrides below. It does not reuse every 2022-optimized preset from the earlier NQ reports. Differences in parameters and selected timeframes must be considered when comparing those reports with this one.

Four full-sized futures contracts: NQ, ES, YM and CL. Each independent test starts with $100,000, uses one contract, $1.25 commission per side and one tick of slippage per side. ORB uses a $2,500 stop-risk cap and at most one contract. Standard and micro contracts are not interchangeable. Dollar profits across markets do not represent equal-risk allocations.

| Strategy | Combinations | Profitable screens | Eligible screens | Frozen follow-ups | Later metric passes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Buy and hold benchmark | 24 | 24 | 0 | 0 | 0 |
| Moving-average trend | 24 | 11 | 5 | 3 | 1 |
| Multi-speed momentum | 16 | 10 | 2 | 1 | 0 |
| Pine · Daily TSMOM rebalance | 4 | 2 | 0 | 0 | 0 |
| Pine · Overnight block | 8 | 6 | 6 | 3 | 2 |
| Pine · Filtered overnight drift | 8 | 8 | 7 | 4 | 0 |
| Pine · TSMOM intraday ORB | 4 | 1 | 1 | 1 | 1 |
| RSI(2) trend-filtered reversion | 4 | 3 | 1 | 1 | 0 |
| Session VWAP reversion | 12 | 0 | 0 | 0 | 0 |

| Frozen selection | 2024 baseline | 2025 baseline | 2026 Jan–Aug baseline | Decision |
| --- | ---: | ---: | ---: | --- |
| pine-overnight-block / NQ / 15m | $56,505 | $60,888 | $71,380 | Retain for research |
| multi-speed-momentum / NQ / 4h | -$7,300 | $13,900 | -$128,393 | Failed later checks |
| moving-average / ES / 1d | $39,510 | $22,903 | $12,348 | Retain for research |
| pine-tsmom-orb / NQ / 5m | $25,433 | $8,265 | $11,553 | Passes metrics; exit review |
| moving-average / NQ / 4h | $48,150 | $29,185 | $31,370 | Failed later checks |
| pine-overnight-drift / CL / 5m | $3,088 | -$24,813 | -$700 | Failed later checks |
| moving-average / YM / 1d | $20,805 | $24,643 | -$5,550 | Failed later checks |
| pine-overnight-drift / YM / 5m | $13,483 | -$13,130 | $9,785 | Failed later checks |
| rsi2-reversion / NQ / 1d | $55,668 | $59,688 | $43,593 | Failed later checks |
| pine-overnight-block / ES / 5m | $23,393 | $25,758 | $28,558 | Passes metrics; sensitivity review |
| pine-overnight-block / YM / 15m | $5,400 | $2,338 | $16,245 | Failed later checks |
| pine-overnight-drift / NQ / 5m | $62,373 | -$12,318 | $13,635 | Failed later checks |
| pine-overnight-drift / ES / 5m | $33,728 | -$12,988 | $11,758 | Failed later checks |

Acceptance requires positive profit, maximum drawdown no worse than 35%, and enough trades in every baseline, doubled-cost and supported-delay scenario. Later losses do not cause a switch to another timeframe. Training-period sensitivity checks are diagnostics; their settings never replace the frozen baseline. Pine event strategies have no added execution-delay model. Regime results attribute the existing path to historical states; they are not backtests of a new regime filter.

**Buy and hold benchmark**

Hold a fixed long position after the first completed bar; liquidate at the evaluation end.

24 of 24 screening combinations had positive net P&L; 0 met every screening requirement. Highest screening Sharpe: NQ 4h, 0.78, $211,963 net profit, 39.87% drawdown, 1 trades. This highest-Sharpe row did not necessarily qualify; see its failure reasons in the full table.

Consolidates the passive long benchmark only. Fixed futures contracts with explicit entry/exit costs replace the original proxy-return benchmark.

**Moving-average trend**

Existing canonical long/flat trend signal, with next-bar-open fills and fixed whole contracts.

11 of 24 screening combinations had positive net P&L; 5 met every screening requirement. Highest screening Sharpe: ES 1d, 0.82, $89,613 net profit, 22.08% drawdown, 80 trades. This highest-Sharpe row qualified.

Consolidates long/flat moving-average decisions. Original cash-index portfolios and notional-return accounting are not reproduced.

ES 1d: Retain for research.  

2024: 11 trades; win rate 45.45%; profit factor 3.76; average winner/loss 4.51; expectancy $3,592. Net profit excluding the five best trades arithmetically: -$14,340. Mean daily P&L five-day-block bootstrap 95% interval: -$33 to $339.

2025: 14 trades; win rate 28.57%; profit factor 1.77; average winner/loss 4.42; expectancy $1,636. Net profit excluding the five best trades arithmetically: -$29,135. Mean daily P&L five-day-block bootstrap 95% interval: -$148 to $338.

2026 Jan–Aug: 11 trades; win rate 27.27%; profit factor 1.47; average winner/loss 3.92; expectancy $1,123. Net profit excluding the five best trades arithmetically: -$25,178. Mean daily P&L five-day-block bootstrap 95% interval: -$254 to $428.

2024 matching buy-hold reference: $55,985 profit and 17.72% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $47,198 profit and 51.81% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $39,935 profit and 29.96% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: $12,360 (2 entries; 11 episodes); Lower: -$13 (9 entries; 12 episodes).

2026 volatility attribution: Higher: $17,886 (6 entries; 5 episodes); Lower: -$5,539 (5 entries; 6 episodes).

NQ 4h: Failed later checks. Failed scenarios: 2026 Jan-Aug Baseline; 2026 Jan-Aug Higher costs; 2026 Jan-Aug Delayed execution; 2025 Baseline; 2025 Higher costs; 2025 Delayed execution. 

2024: 84 trades; win rate 28.57%; profit factor 1.38; average winner/loss 3.44; expectancy $573. Net profit excluding the five best trades arithmetically: -$40,253. Mean daily P&L five-day-block bootstrap 95% interval: -$235 to $598.

2025: 72 trades; win rate 34.72%; profit factor 1.20; average winner/loss 2.26; expectancy $405. Net profit excluding the five best trades arithmetically: -$60,423. Mean daily P&L five-day-block bootstrap 95% interval: -$312 to $543.

2026 Jan–Aug: 54 trades; win rate 29.63%; profit factor 1.22; average winner/loss 2.90; expectancy $581. Net profit excluding the five best trades arithmetically: -$94,288. Mean daily P&L five-day-block bootstrap 95% interval: -$583 to $1,018.

2024 matching buy-hold reference: $84,293 profit and 37.65% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $83,303 profit and 91.84% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $80,838 profit and 54.99% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: $23,091 (23 entries; 61 episodes); Lower: $8,279 (31 entries; 62 episodes).

2026 volatility attribution: Higher: $4,199 (40 entries; 26 episodes); Lower: $27,171 (14 entries; 27 episodes).

YM 1d: Failed later checks. Failed scenarios: 2026 Jan-Aug Baseline; 2026 Jan-Aug Higher costs. 

2024: 10 trades; win rate 70.00%; profit factor 11.29; average winner/loss 4.84; expectancy $2,081. Net profit excluding the five best trades arithmetically: -$523. Mean daily P&L five-day-block bootstrap 95% interval: -$48 to $229.

2025: 13 trades; win rate 46.15%; profit factor 2.81; average winner/loss 3.28; expectancy $1,896. Net profit excluding the five best trades arithmetically: -$12,200. Mean daily P&L five-day-block bootstrap 95% interval: -$49 to $245.

2026 Jan–Aug: 14 trades; win rate 28.57%; profit factor 0.78; average winner/loss 1.96; expectancy -$396. Net profit excluding the five best trades arithmetically: -$24,758. Mean daily P&L five-day-block bootstrap 95% interval: -$245 to $170.

2024 matching buy-hold reference: $24,458 profit and 11.72% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $27,068 profit and 33.06% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $24,403 profit and 22.87% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: $2,120 (4 entries; 10 episodes); Lower: -$7,670 (10 entries; 11 episodes).

2026 volatility attribution: Higher: $5,129 (9 entries; 4 episodes); Lower: -$10,679 (5 entries; 5 episodes).

**Multi-speed momentum**

Long/short consensus of four completed-bar momentum horizons. Fixed contracts and next-open fills.

10 of 16 screening combinations had positive net P&L; 2 met every screening requirement. Highest screening Sharpe: NQ 4h, 0.89, $217,873 net profit, 22.33% drawdown, 385 trades. This highest-Sharpe row qualified.

Uses the canonical engine four-speed signal. Original CME proxy portfolio, lookbacks, volatility sizing, and NAV accounting are not reproduced.

NQ 4h: Failed later checks. Failed scenarios: 2024 baseline; 2024 costs; 2024 delay; 2026 Jan-Aug Baseline; 2026 Jan-Aug Higher costs; 2026 Jan-Aug Delayed execution; 2025 Baseline; 2025 Higher costs; 2025 Delayed execution. 

2024: 64 trades; win rate 34.38%; profit factor 0.93; average winner/loss 1.77; expectancy -$114. Net profit excluding the five best trades arithmetically: -$76,458. Mean daily P&L five-day-block bootstrap 95% interval: -$522 to $402.

2025: 70 trades; win rate 31.43%; profit factor 1.07; average winner/loss 2.35; expectancy $199. Net profit excluding the five best trades arithmetically: -$121,918. Mean daily P&L five-day-block bootstrap 95% interval: -$632 to $750.

2026 Jan–Aug: 79 trades; win rate 22.78%; profit factor 0.53; average winner/loss 1.78; expectancy -$1,625. Net profit excluding the five best trades arithmetically: -$258,755. Mean daily P&L five-day-block bootstrap 95% interval: -$1,957 to $515.

2024 matching buy-hold reference: $84,293 profit and 37.65% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $83,303 profit and 91.84% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $80,838 profit and 54.99% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: -$68,350 (37 entries; 61 episodes); Lower: -$60,043 (42 entries; 62 episodes).

2026 volatility attribution: Higher: -$111,103 (53 entries; 26 episodes); Lower: -$17,290 (26 entries; 27 episodes).

**Pine · Daily TSMOM rebalance**

Completed daily 20/60/120/252 votes, point-volatility sizing, and a rebalance at the first 15-minute close of each Globex session.

2 of 4 screening combinations had positive net P&L; 0 met every screening requirement. Highest screening Sharpe: NQ 15m, 0.46, $115,510 net profit, 69.20% drawdown, 54 trades. This highest-Sharpe row did not necessarily qualify; see its failure reasons in the full table.

Historical Pine decision/timing port. Daily bars and signal use the selected futures dataset, not a separate signal symbol or TradingView settlement feed. Whole contracts; no TradingView margin-call emulation. Live request.security repaint behavior is not reproduced.

**Pine · Overnight block**

Clock-window transition orders evaluated at the bar close, filled at the next open. Default 17:00 arming captures the 18:00 CME reopen.

6 of 8 screening combinations had positive net P&L; 6 met every screening requirement. Highest screening Sharpe: NQ 15m, 0.94, $133,103 net profit, 18.29% drawdown, 1549 trades. This highest-Sharpe row qualified.

Ports the Pine clock/order rules, including boundary-only entries. Scoring starts flat; no entry midway through an existing hold window. Costs and contract economics use the run inputs.

NQ 15m: Retain for research.  

2024: 258 trades; win rate 55.43%; profit factor 1.39; average winner/loss 1.12; expectancy $219. Net profit excluding the five best trades arithmetically: $22,273. Mean daily P&L five-day-block bootstrap 95% interval: -$1 to $373.

2025: 257 trades; win rate 53.70%; profit factor 1.29; average winner/loss 1.12; expectancy $237. Net profit excluding the five best trades arithmetically: $20,835. Mean daily P&L five-day-block bootstrap 95% interval: -$61 to $443.

2026 Jan–Aug: 172 trades; win rate 55.23%; profit factor 1.34; average winner/loss 1.08; expectancy $415. Net profit excluding the five best trades arithmetically: $24,598. Mean daily P&L five-day-block bootstrap 95% interval: -$70 to $762.

2024 matching buy-hold reference: $84,293 profit and 38.84% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $83,303 profit and 95.51% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $80,623 profit and 56.65% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: $25,566 (78 entries; 918 episodes); Lower: $45,814 (94 entries; 918 episodes).

2026 volatility attribution: Higher: $64,258 (126 entries; 248 episodes); Lower: $7,123 (46 entries; 249 episodes).

ES 5m: Passes metrics; sensitivity review.  

2024: 258 trades; win rate 55.04%; profit factor 1.31; average winner/loss 1.07; expectancy $91. Net profit excluding the five best trades arithmetically: $1,543. Mean daily P&L five-day-block bootstrap 95% interval: -$27 to $189.

2025: 257 trades; win rate 53.70%; profit factor 1.22; average winner/loss 1.06; expectancy $100. Net profit excluding the five best trades arithmetically: $7,183. Mean daily P&L five-day-block bootstrap 95% interval: -$56 to $228.

2026 Jan–Aug: 172 trades; win rate 55.81%; profit factor 1.34; average winner/loss 1.06; expectancy $166. Net profit excluding the five best trades arithmetically: $6,608. Mean daily P&L five-day-block bootstrap 95% interval: -$42 to $326.

2024 matching buy-hold reference: $55,985 profit and 20.34% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $47,198 profit and 59.41% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $40,010 profit and 31.84% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: $16,604 (78 entries; 2925 episodes); Lower: $11,954 (94 entries; 2925 episodes).

2026 volatility attribution: Higher: $14,759 (114 entries; 633 episodes); Lower: $13,799 (58 entries; 633 episodes).

YM 15m: Failed later checks. Failed scenarios: 2025 Higher costs. 

2024: 258 trades; win rate 47.29%; profit factor 1.11; average winner/loss 1.24; expectancy $21. Net profit excluding the five best trades arithmetically: -$10,158. Mean daily P&L five-day-block bootstrap 95% interval: -$49 to $93.

2025: 257 trades; win rate 49.42%; profit factor 1.03; average winner/loss 1.05; expectancy $9. Net profit excluding the five best trades arithmetically: -$8,385. Mean daily P&L five-day-block bootstrap 95% interval: -$74 to $97.

2026 Jan–Aug: 172 trades; win rate 54.65%; profit factor 1.30; average winner/loss 1.08; expectancy $94. Net profit excluding the five best trades arithmetically: $1,128. Mean daily P&L five-day-block bootstrap 95% interval: -$38 to $202.

2024 matching buy-hold reference: $24,458 profit and 12.83% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $27,068 profit and 37.31% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $24,568 profit and 24.68% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: $12,191 (78 entries; 955 episodes); Lower: $4,054 (94 entries; 955 episodes).

2026 volatility attribution: Higher: $11,870 (121 entries; 224 episodes); Lower: $4,375 (51 entries; 224 episodes).

**Pine · Filtered overnight drift**

Use the completed RTH close filter and overnight volatility sizing. Fill at the close of the first outside-RTH bar and exit at the first RTH bar close.

8 of 8 screening combinations had positive net P&L; 7 met every screening requirement. Highest screening Sharpe: CL 5m, 0.66, $49,403 net profit, 13.69% drawdown, 639 trades. This highest-Sharpe row qualified.

Preserves actual Pine bar-close timing, which differs from the header's ideal RTH-close/RTH-open trades. Uses selected-dataset daily prices and economics; no TradingView margin-call simulation.

CL 5m: Failed later checks. Failed scenarios: 2026 Jan-Aug Baseline; 2026 Jan-Aug Higher costs; 2025 Baseline; 2025 Higher costs. 

2024: 113 trades; win rate 56.64%; profit factor 1.10; average winner/loss 0.84; expectancy $27. Net profit excluding the five best trades arithmetically: -$4,420. Mean daily P&L five-day-block bootstrap 95% interval: -$36 to $62.

2025: 105 trades; win rate 41.90%; profit factor 0.51; average winner/loss 0.71; expectancy -$236. Net profit excluding the five best trades arithmetically: -$37,870. Mean daily P&L five-day-block bootstrap 95% interval: -$161 to -$8.

2026 Jan–Aug: 80 trades; win rate 51.25%; profit factor 0.99; average winner/loss 0.94; expectancy -$9. Net profit excluding the five best trades arithmetically: -$28,037. Mean daily P&L five-day-block bootstrap 95% interval: -$268 to $247.

2024 matching buy-hold reference: $138 profit and 19.18% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: -$14,462 profit and 22.62% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $28,957 profit and 31.74% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: $5,921 (50 entries; 2854 episodes); Lower: -$6,621 (30 entries; 2854 episodes).

2026 volatility attribution: Higher: $1,512 (71 entries; 433 episodes); Lower: -$2,212 (9 entries; 434 episodes).

YM 5m: Failed later checks. Failed scenarios: 2025 Baseline; 2025 Higher costs. 

2024: 103 trades; win rate 52.43%; profit factor 1.47; average winner/loss 1.34; expectancy $131. Net profit excluding the five best trades arithmetically: -$1,930. Mean daily P&L five-day-block bootstrap 95% interval: -$15 to $110.

2025: 108 trades; win rate 44.44%; profit factor 0.75; average winner/loss 0.94; expectancy -$122. Net profit excluding the five best trades arithmetically: -$30,118. Mean daily P&L five-day-block bootstrap 95% interval: -$129 to $37.

2026 Jan–Aug: 74 trades; win rate 59.46%; profit factor 1.29; average winner/loss 0.88; expectancy $132. Net profit excluding the five best trades arithmetically: -$7,088. Mean daily P&L five-day-block bootstrap 95% interval: -$62 to $146.

2024 matching buy-hold reference: $24,458 profit and 12.98% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $27,068 profit and 37.49% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $24,523 profit and 24.80% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: $2,048 (37 entries; 2876 episodes); Lower: $7,738 (37 entries; 2876 episodes).

2026 volatility attribution: Higher: $4,524 (57 entries; 613 episodes); Lower: $5,261 (17 entries; 613 episodes).

NQ 5m: Failed later checks. Failed scenarios: 2025 Baseline; 2025 Higher costs. 

2024: 107 trades; win rate 55.14%; profit factor 1.96; average winner/loss 1.60; expectancy $583. Net profit excluding the five best trades arithmetically: $29,595. Mean daily P&L five-day-block bootstrap 95% interval: $55 to $354.

2025: 115 trades; win rate 49.57%; profit factor 0.92; average winner/loss 0.93; expectancy -$107. Net profit excluding the five best trades arithmetically: -$54,570. Mean daily P&L five-day-block bootstrap 95% interval: -$260 to $175.

2026 Jan–Aug: 70 trades; win rate 52.86%; profit factor 1.12; average winner/loss 1.00; expectancy $195. Net profit excluding the five best trades arithmetically: -$31,588. Mean daily P&L five-day-block bootstrap 95% interval: -$285 to $439.

2024 matching buy-hold reference: $84,293 profit and 39.61% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $83,303 profit and 96.20% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $80,493 profit and 57.28% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: $40,405 (37 entries; 2870 episodes); Lower: -$26,770 (33 entries; 2870 episodes).

2026 volatility attribution: Higher: $14,465 (52 entries; 661 episodes); Lower: -$830 (18 entries; 661 episodes).

ES 5m: Failed later checks. Failed scenarios: 2025 Baseline; 2025 Higher costs. 

2024: 109 trades; win rate 62.39%; profit factor 2.04; average winner/loss 1.23; expectancy $309. Net profit excluding the five best trades arithmetically: $14,128. Mean daily P&L five-day-block bootstrap 95% interval: $34 to $193.

2025: 105 trades; win rate 51.43%; profit factor 0.82; average winner/loss 0.77; expectancy -$124. Net profit excluding the five best trades arithmetically: -$36,375. Mean daily P&L five-day-block bootstrap 95% interval: -$172 to $75.

2026 Jan–Aug: 72 trades; win rate 62.50%; profit factor 1.28; average winner/loss 0.77; expectancy $163. Net profit excluding the five best trades arithmetically: -$7,543. Mean daily P&L five-day-block bootstrap 95% interval: -$66 to $199.

2024 matching buy-hold reference: $55,985 profit and 20.34% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $47,198 profit and 59.41% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $40,010 profit and 31.84% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: $2,200 (38 entries; 2925 episodes); Lower: $9,558 (34 entries; 2925 episodes).

2026 volatility attribution: Higher: $8,111 (46 entries; 633 episodes); Lower: $3,646 (26 entries; 633 episodes).

**Pine · TSMOM intraday ORB**

Daily direction-filtered ORB with signal-close entries, a dollar-risk budget, stop/target brackets, one attempt per session, and a force-flat window.

1 of 4 screening combinations had positive net P&L; 1 met every screening requirement. Highest screening Sharpe: NQ 5m, 0.80, $91,298 net profit, 20.56% drawdown, 821 trades. This highest-Sharpe row qualified.

Pine rules port with one-minute bracket execution. Stop wins ties within a minute; gap fills use the opening price. No TradingView sub-minute Bar Magnifier or order-fill recalculation emulation. A rejected risk-sized attempt still consumes the session.

NQ 5m: Passes metrics; exit review.  9 later ORB trades crossed the entry date.

2024: 149 trades; win rate 46.31%; profit factor 1.26; average winner/loss 1.46; expectancy $171. Net profit excluding the five best trades arithmetically: $7,465. Mean daily P&L five-day-block bootstrap 95% interval: -$46 to $199.

2025: 104 trades; win rate 51.92%; profit factor 1.11; average winner/loss 1.03; expectancy $79. Net profit excluding the five best trades arithmetically: -$11,693. Mean daily P&L five-day-block bootstrap 95% interval: -$68 to $122.

2026 Jan–Aug: 29 trades; win rate 55.17%; profit factor 1.46; average winner/loss 1.18; expectancy $398. Net profit excluding the five best trades arithmetically: -$7,070. Mean daily P&L five-day-block bootstrap 95% interval: -$70 to $205.

2024 matching buy-hold reference: $84,293 profit and 39.61% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $83,303 profit and 96.20% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $80,493 profit and 57.28% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: $12,138 (18 entries; 2870 episodes); Lower: -$585 (11 entries; 2870 episodes).

2026 volatility attribution: Higher: $16,525 (25 entries; 661 episodes); Lower: -$4,973 (4 entries; 661 episodes).

**RSI(2) trend-filtered reversion**

Long when simple RSI(2) is below the entry threshold and price is above its moving average; exit above the RSI exit threshold.

3 of 4 screening combinations had positive net P&L; 1 met every screening requirement. Highest screening Sharpe: NQ 1d, 0.52, $84,438 net profit, 34.03% drawdown, 83 trades. This highest-Sharpe row qualified.

Ports s_rsi2 decisions, including its zero-loss RSI convention. Uses selected futures, fixed whole contracts and next-open fills; original cash-index NAV differs.

NQ 1d: Failed later checks. Failed scenarios: 2026 Jan-Aug Delayed execution; 2025 Baseline; 2025 Higher costs; 2025 Delayed execution. 

2024: 23 trades; win rate 65.22%; profit factor 1.99; average winner/loss 1.06; expectancy $2,420. Net profit excluding the five best trades arithmetically: -$15,985. Mean daily P&L five-day-block bootstrap 95% interval: -$162 to $589.

2025: 17 trades; win rate 76.47%; profit factor 1.84; average winner/loss 0.57; expectancy $3,511. Net profit excluding the five best trades arithmetically: -$29,135. Mean daily P&L five-day-block bootstrap 95% interval: -$225 to $654.

2026 Jan–Aug: 15 trades; win rate 60.00%; profit factor 2.27; average winner/loss 1.51; expectancy $2,906. Net profit excluding the five best trades arithmetically: -$18,475. Mean daily P&L five-day-block bootstrap 95% interval: -$532 to $977.

2024 matching buy-hold reference: $84,293 profit and 34.27% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2025 matching buy-hold reference: $83,303 profit and 83.86% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 matching buy-hold reference: $80,838 profit and 54.62% drawdown. Each reference uses the candidate's market, chart timeframe and session.

2026 trend attribution: Higher: -$19,629 (6 entries; 8 episodes); Lower: $63,221 (9 entries; 9 episodes).

2026 volatility attribution: Higher: $86,140 (9 entries; 4 episodes); Lower: -$42,548 (6 entries; 5 episodes).

**Session VWAP reversion**

Fade deviations from cumulative session VWAP; return to flat when price crosses VWAP. Decision state resets each session.

0 of 12 screening combinations had positive net P&L; 0 met every screening requirement. Highest screening Sharpe: YM 15m, -0.09, -$56,268 net profit, 81.15% drawdown, 2421 trades. This highest-Sharpe row did not necessarily qualify; see its failure reasons in the full table.

Ports s_vwap_rev decision state. Uses selected futures and next-open accounting; positions can carry across excluded-session gaps until the next available fill. Original ETF session returns differ.

**Coverage and limits**

The source inventory contains 109 original files. The runnable workbench adapters cover specific rule subsets. 48 entries explicitly require adapters; indicator drawings, data tools and reports are not invented as tradeable strategies. The interactive report lists every source, its role, available adapter, migration scope and outstanding requirement. SND's existing Python engine is retained, but it is not one of the nine workbench adapters tested in this campaign.

Input checks verify dataset and artifact checksums, ordered unique timestamps, valid OHLC, nonnegative volume, and trade/cost/equity reconciliation. No negative-price bars were found in these four imported archives; the importer does not reject legitimate negative prices. Unadjusted futures rolls and unclassified session gaps remain limitations; no roll-neutral result or margin feasibility is claimed. Drawdowns are marked at chart-bar closes and can miss adverse intrabar excursions. Coarser chart drawdowns are not equally detailed risk measurements.

Regime features use 20 preceding native-timeframe bars and the 2025 training median. Higher/lower trend refers to signed deviation from the moving average, not a universal trend-strength classification. Different timeframes represent different feature horizons. A favorable state contribution does not establish an executable state-only strategy.

The CSV switch-gap diagnostic sums each mapping-change open minus the prior source close, multiplied by the quantity held across that timestamp. These gaps can include genuine market movement as well as contract differences. Subtracting them is an arithmetic exposure diagnostic, not a roll-adjusted backtest or an estimate of realizable roll costs.

The signal-strategy execution stress adds one chart bar, so its elapsed delay differs by timeframe: a daily strategy waits another session, while a five-minute strategy waits another five-minute bar. This tests timing sensitivity; it is not a uniform measured broker-latency model. Pine event strategies receive cost stress but lack this delay test.

Sharpe uses observed UTC daily equity returns, sample standard deviation, 252-date annualization and zero risk-free rate. Missing dates are not filled. Payoff ratio is mean net winning trade divided by the absolute mean net losing trade; profit factor uses total positive net trade P&L divided by absolute negative net P&L. Ratios without the required winners/losers remain undefined. The full ledgers, not sampled chart previews, supply these statistics.

The initial 104 combinations and later sensitivity checks create selection bias. Positive backtests and unadjusted bootstrap intervals are insufficient to establish a reliable live edge. The five-observed-day bootstrap intervals are descriptive, use seed 42 and 1,000 resamples, and are not adjusted for the search. Profit excluding the five best trades is an arithmetic concentration diagnostic, not an alternative trading rule.

**Next steps**

1. Prioritize configurations that survive all later cost/delay/drawdown checks; retain failed trials in the ledger.
2. Resolve ORB missing-window exits in a separate version and test holidays, early closes and price gaps. Keep the original version for comparison.
3. Recheck promising results with explicit roll accounting, executable contract sizing and margin constraints before prospective paper tracking.
4. Treat nearby parameters and regime patterns as new hypotheses; do not retune against the already inspected 2024–2026 results.
5. Port missing strategy families only with their required data and execution rules: supply/demand, market profile, Asia fill, multi-leg portfolios, equity factors and the original ETF/micro/gold variants require separate work.

Files: [interactive report](REPORT.html), [all 104 screening rows](screening.csv), [all campaign runs](all-runs.csv), [annual P&L](annual-pnl.csv), [complete source inventory](source-inventory.csv), [software validation](SOFTWARE-VALIDATION.md), [frozen protocol](PLAN.json), [campaign and run IDs](campaign.json).
