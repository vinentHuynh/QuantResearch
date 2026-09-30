Expanded strategy search — September 16, 2026

Completed 188 new screens and 54 later scenario ledgers. 6 frozen selections; 3 pass all later session-metric checks. Original workbench campaign remains unchanged.

Screening uses 2018–2023. At most one timeframe/session per family/market advances, ranked before the later tests. Each later year starts independently with $100,000 and one full-sized contract, $1.25 commission and one tick of slippage per side. Tests cover 2024, 2025 and January–August 2026. Costs are represented as equivalent round-trip ticks in the unchanged canonical functions. This is historical research on previously inspected data, not an untouched holdout.

**The deeper search confirms overnight exposure; it does not establish a new independent strategy family**

The additional campaign completed 188 screens across three existing canonical implementations, all four markets, every supported timeframe, and every named session supported by those implementations. Six configurations qualified on 2018–2023 and were frozen before 54 later scenarios. Three survive every later numeric check, including the open-position risk audit: NQ, ES and YM session drift during Globex overnight. All three simply hold the 18:00–06:00 New York session long. This overlaps the economic exposure of the overnight-block candidates from the first campaign; it should not be counted as three new diversified sources of return. The breakout and prior-range-fill leads fail later tests.

**NQ and ES overnight remain the clearest research priorities**

On one-minute charts, NQ overnight session drift earns $54,657.50 in 2024, $64,615 in 2025 and $71,440 in January–August 2026. Doubled-cost results remain $51,420, $61,390 and $69,290. Delaying entry by one minute reduces the 2026 result to $54,650, still positive but $16,790 below baseline. ES earns $22,790, $26,280 and $28,945 in the three later periods, and remains positive under both stress scenarios. Removing each period's five best trades arithmetically leaves NQ and ES positive in every later year. Neither result establishes future profitability, and this is not a retuned replacement for the first campaign's frozen rules.

**Open-position drawdown is materially worse than the engine headline**

The canonical session-based engine reports realized equity at session close. Reconstructing the overnight paths at one-minute closes raises NQ's 2025 baseline drawdown from about 22.8% to 29.02%; its worst later scenario reaches 29.72%. ES's worst marked later scenario is 20.20%, and YM's is 15.20%. These still pass the declared 35% risk boundary, but session-close statistics alone substantially understate the path's risk. The audit also lists incomplete or late source sessions. It does not model adverse intraminute prices, explicit contract rolls, broker margin or liquidation.

**YM overnight is a marginal survivor, not a replacement for NQ or ES**

YM overnight produces $4,692.50, $3,715 and $14,980 in the three later baseline periods. Its doubled-cost 2025 profit is only $490 across 258 trades: approximately $1.90 of additional round-trip cost per trade would erase it. Each later period becomes negative if its five best trades are removed arithmetically. The first campaign's different YM overnight-block configuration failed the 2025 cost stress; this nearby implementation passes by a narrow margin. Keep both results visible. The difference supports a fragility finding rather than choosing the better historical implementation after the fact.

**The most attractive new breakout screen breaks down in 2026**

The separate canonical NQ opening-range breakout on 30-minute New York RTH bars earned $163,082.50 with screening Sharpe around 1.11. It then earned $38,485 in 2024 and $59,755 in 2025, but lost $46,842.50 in January–August 2026. The conservative next-open/gap-stop scenario also loses $46,777.50 in 2026. Its worst marked later drawdown is 51.59%. This is a different rule from the first campaign's filtered TSMOM ORB, so the results are not interchangeable. Strong training and two profitable later years did not prevent a subsequent large failure.

**Prior-range fill does not survive all later periods**

CL prior-range fill during London hours earns $3,812.50 in 2024 and $13,500 in 2025, then loses $4,552.50 in January–August 2026; the conservative execution scenario also remains negative in 2026. NQ prior-range fill during New York RTH loses $24,047.50 in 2024 despite positive 2025–2026 totals. The audit found one CL native entry priced outside its entire signal-minute range, demonstrating why the original level-touch fill assumption needs review. No timeframe/session replacement is made after these failures. Across the complete new screen, 79 of 188 configurations are net profitable; another 68 are gross profitable but lose after costs. Repeated identical timeframe outcomes are not independent observations.

**SND needs cost and parity work before promotion**

Fresh repricing of the saved Phase 6 ledger finds $12,441 gross profit across 3,915 MNQ trades, but minus $1,261.50 at the campaign's $1.25 per-side commission plus one tick per-side slippage, or $3.50 round trip for MNQ. The break-even round-trip cost is $3.178; the older four-tick stress costs only $2 and therefore passes. This is a check of an existing micro-contract ledger, not a new full-size-market simulation. Rerun Strategy Tester comparisons match 215 of 230 Phase 6 reference signals and 64 of 86 RVOL reference signals. The RVOL export also has 52 unmatched TradingView signals. Feed construction and stateful trade eligibility remain unresolved; strong agreement in matched RVOL values is not full trade-sequence parity.

**Next work should target execution evidence, not another unrestricted parameter search**

Prioritize a versioned, roll-aware and calendar-aware replay of NQ/ES overnight rules, followed by prospective paper tracking with fixed parameters. Reconcile SND's missing and additional signals on the same feed, then resimulate any RVOL filter through the complete position state machine. Treat YM as fragile and retain the failed breakout/fill tests. The saved Asia gap-fill result also disappears under a one-tick target trade-through or a higher commission assumption, while the saved market-profile rules have no persuasive net edge. These legacy checks use existing ledgers and remain separate from the 242 new canonical runs. The original 279-run workbench campaign is preserved.

| Frozen configuration | 2024 net | 2025 net | 2026 Jan–Aug net | Decision |
| --- | ---: | ---: | ---: | --- |
| opening-range-breakout__NQ__30m__new-york-rth | $38,485.00 | $59,755.00 | $-46,842.50 | Fails later checks |
| prior-range-fill__CL__1m__london | $3,812.50 | $13,500.00 | $-4,552.50 | Fails later checks |
| prior-range-fill__NQ__1m__new-york-rth | $-24,047.50 | $55,375.00 | $15,442.50 | Fails later checks |
| overnight-session__YM__1m__globex-overnight | $4,692.50 | $3,715.00 | $14,980.00 | Further research candidate |
| overnight-session__ES__1m__globex-overnight | $22,790.00 | $26,280.00 | $28,945.00 | Further research candidate |
| overnight-session__NQ__1m__globex-overnight | $54,657.50 | $64,615.00 | $71,440.00 | Further research candidate |

Conservative execution waits until the next chart bar opens after a confirmed breakout or prior-range touch; session drift waits one extra chart bar after the open. ORB brackets are recalculated from that entry, include entry-bar hits, fill gap-through stops at the opening price, and resolve stop/target ties stop-first. These are declared execution stress variants, not replacements selected after failure. Doubled costs are an exact arithmetic replay because these fixed-size rules do not depend on equity or fees.

Native metrics use session-close realized equity. The additional risk audit marks open positions at one-minute closes for session exits, and at completed chart closes before the ORB exit bar. Intrabar extremes and the ORB exit-bar path remain unknown. Prices are unadjusted continuous futures, sessions use weekday calendars, incomplete source sessions remain present, and there is no margin liquidation. No new portfolio, live allocation, or certified original Pine/legacy parity is established. Some identical timeframe rows are repeated views of the same economic rule.

**opening-range-breakout__NQ__30m__new-york-rth — Fails later checks**

2026 baseline: nonpositive profit, session drawdown >35%
2026 conservative_execution: nonpositive profit, session drawdown >35%
2026 double_cost: nonpositive profit, session drawdown >35%
2026 baseline: 50.30% marked drawdown
2026 conservative_execution: 50.23% marked drawdown
2026 double_cost: 51.59% marked drawdown

| Period | Scenario | Net profit | Session DD | Marked DD | Trades | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2024 | baseline | $38,485.00 | 13.14% | 13.74% | 254 | 1.22 |
| 2024 | conservative_execution | $34,577.50 | 13.10% | 13.70% | 251 | 1.19 |
| 2024 | double_cost | $35,310.00 | 13.39% | 14.00% | 254 | 1.20 |
| 2025 | baseline | $59,755.00 | 10.19% | 11.06% | 252 | 1.27 |
| 2025 | conservative_execution | $56,135.00 | 12.17% | 13.04% | 252 | 1.25 |
| 2025 | double_cost | $56,605.00 | 10.72% | 11.60% | 252 | 1.26 |
| 2026 | baseline | $-46,842.50 | 49.34% | 50.30% | 167 | 0.79 |
| 2026 | conservative_execution | $-46,777.50 | 49.26% | 50.23% | 167 | 0.79 |
| 2026 | double_cost | $-48,930.00 | 50.64% | 51.59% | 167 | 0.78 |

Baseline entries priced outside their signal bar: 0. Full incomplete-session and fill diagnostics are in intratrade-risk.csv.

**prior-range-fill__CL__1m__london — Fails later checks**

2026 baseline: nonpositive profit
2026 conservative_execution: nonpositive profit
2026 double_cost: nonpositive profit

| Period | Scenario | Net profit | Session DD | Marked DD | Trades | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2024 | baseline | $3,812.50 | 11.29% | 13.43% | 83 | 1.14 |
| 2024 | conservative_execution | $4,352.50 | 11.14% | 13.31% | 83 | 1.16 |
| 2024 | double_cost | $1,945.00 | 12.41% | 14.47% | 83 | 1.07 |
| 2025 | baseline | $13,500.00 | 3.76% | 4.59% | 64 | 1.88 |
| 2025 | conservative_execution | $13,580.00 | 3.75% | 4.54% | 64 | 1.90 |
| 2025 | double_cost | $12,060.00 | 4.08% | 4.90% | 64 | 1.75 |
| 2026 | baseline | $-4,552.50 | 19.86% | 23.67% | 41 | 0.86 |
| 2026 | conservative_execution | $-3,262.50 | 19.24% | 23.02% | 41 | 0.90 |
| 2026 | double_cost | $-5,475.00 | 20.46% | 24.26% | 41 | 0.83 |

Baseline entries priced outside their signal bar: 1. Full incomplete-session and fill diagnostics are in intratrade-risk.csv.

**prior-range-fill__NQ__1m__new-york-rth — Fails later checks**

2024 baseline: nonpositive profit
2024 conservative_execution: nonpositive profit
2024 double_cost: nonpositive profit

| Period | Scenario | Net profit | Session DD | Marked DD | Trades | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2024 | baseline | $-24,047.50 | 29.38% | 33.00% | 59 | 0.61 |
| 2024 | conservative_execution | $-24,597.50 | 29.38% | 33.22% | 59 | 0.61 |
| 2024 | double_cost | $-24,785.00 | 30.01% | 33.60% | 59 | 0.61 |
| 2025 | baseline | $55,375.00 | 11.53% | 16.20% | 78 | 1.82 |
| 2025 | conservative_execution | $57,172.50 | 11.20% | 16.10% | 77 | 1.88 |
| 2025 | double_cost | $54,400.00 | 11.69% | 16.23% | 78 | 1.80 |
| 2026 | baseline | $15,442.50 | 21.93% | 25.10% | 51 | 1.24 |
| 2026 | conservative_execution | $21,972.50 | 20.73% | 24.16% | 51 | 1.37 |
| 2026 | double_cost | $14,805.00 | 22.05% | 25.21% | 51 | 1.23 |

Baseline entries priced outside their signal bar: 0. Full incomplete-session and fill diagnostics are in intratrade-risk.csv.

**overnight-session__YM__1m__globex-overnight — Further research candidate**


| Period | Scenario | Net profit | Session DD | Marked DD | Trades | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2024 | baseline | $4,692.50 | 6.50% | 6.77% | 259 | 1.09 |
| 2024 | conservative_execution | $3,612.50 | 7.22% | 7.88% | 259 | 1.07 |
| 2024 | double_cost | $1,455.00 | 6.88% | 7.68% | 259 | 1.03 |
| 2025 | baseline | $3,715.00 | 11.69% | 14.47% | 258 | 1.05 |
| 2025 | conservative_execution | $4,580.00 | 8.26% | 9.65% | 258 | 1.06 |
| 2025 | double_cost | $490.00 | 12.40% | 15.20% | 258 | 1.01 |
| 2026 | baseline | $14,980.00 | 10.07% | 12.48% | 172 | 1.27 |
| 2026 | conservative_execution | $16,115.00 | 8.43% | 11.21% | 172 | 1.30 |
| 2026 | double_cost | $12,830.00 | 10.69% | 13.04% | 172 | 1.23 |

Baseline entries priced outside their signal bar: 0. Full incomplete-session and fill diagnostics are in intratrade-risk.csv.

**overnight-session__ES__1m__globex-overnight — Further research candidate**


| Period | Scenario | Net profit | Session DD | Marked DD | Trades | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2024 | baseline | $22,790.00 | 6.66% | 8.83% | 259 | 1.30 |
| 2024 | conservative_execution | $20,877.50 | 7.32% | 9.21% | 259 | 1.28 |
| 2024 | double_cost | $15,667.50 | 7.00% | 9.23% | 259 | 1.20 |
| 2025 | baseline | $26,280.00 | 14.60% | 18.64% | 258 | 1.23 |
| 2025 | conservative_execution | $25,192.50 | 9.58% | 13.99% | 258 | 1.23 |
| 2025 | double_cost | $19,185.00 | 16.13% | 20.20% | 258 | 1.16 |
| 2026 | baseline | $28,945.00 | 12.16% | 16.05% | 172 | 1.34 |
| 2026 | conservative_execution | $25,370.00 | 10.72% | 14.26% | 172 | 1.30 |
| 2026 | double_cost | $24,215.00 | 13.49% | 17.24% | 172 | 1.28 |

Baseline entries priced outside their signal bar: 0. Full incomplete-session and fill diagnostics are in intratrade-risk.csv.

**overnight-session__NQ__1m__globex-overnight — Further research candidate**


| Period | Scenario | Net profit | Session DD | Marked DD | Trades | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2024 | baseline | $54,657.50 | 14.04% | 19.67% | 259 | 1.37 |
| 2024 | conservative_execution | $52,617.50 | 14.06% | 19.15% | 259 | 1.37 |
| 2024 | double_cost | $51,420.00 | 14.29% | 19.97% | 259 | 1.35 |
| 2025 | baseline | $64,615.00 | 22.82% | 29.02% | 258 | 1.31 |
| 2025 | conservative_execution | $65,350.00 | 16.35% | 18.63% | 258 | 1.33 |
| 2025 | double_cost | $61,390.00 | 23.54% | 29.72% | 258 | 1.29 |
| 2026 | baseline | $71,440.00 | 20.03% | 25.02% | 172 | 1.33 |
| 2026 | conservative_execution | $54,650.00 | 22.12% | 24.56% | 172 | 1.25 |
| 2026 | double_cost | $69,290.00 | 20.34% | 25.53% | 172 | 1.32 |

Baseline entries priced outside their signal bar: 0. Full incomplete-session and fill diagnostics are in intratrade-risk.csv.

**Legacy evidence rechecked separately**

SND Phase 6: 3,915 existing MNQ trades total $12,441 gross. At $3.50 round trip the unchanged ledger yields minus $1,261.50, PF 0.992. Its break-even cost is $3.178 per trade. This is arithmetic repricing, not a fresh simulation. The original four-tick ($2) stress passed because it was cheaper than this campaign assumption.

Rerun SND Strategy Tester comparisons match 215/230 Phase 6 reference signals and 64/86 RVOL reference signals; the RVOL export also contains 52 unmatched TradingView signals. Matching RVOL values does not resolve differences in the stateful sequence of trades. Exported P&L contains zero commission. No exact-parity approval is claimed.

The existing MNQ Asia short gap-fill headline makes $589.50, but requiring a one-tick trade-through yields minus $95.50. Raising its original $1 round-trip commission to $2.50 alone reduces the unchanged baseline fills to minus $3.00. Saved market-profile results are minus $2,240 for the 80% rule and minus $55 for naked POC. These are checks of prior evidence, not new four-market simulations.

The canonical CLI has an existing SessionDriftConfig/quantity_mode signature mismatch. The screen reuses the unchanged calculation functions directly, with valid parameters. Nine canonical engine tests and five focused execution/accounting tests passed. The prepared charts match canonical resampling in 80 comparisons. Original engine and workbench code remain unchanged.

Files: [all new screens](screen-results.csv), [later scenarios](follow-results.csv), [candidate decisions](candidate-decisions.csv), [intratrade risk](intratrade-risk.csv), [frozen protocol](PLAN.json), [validation](validation.json), [legacy audit](legacy-audit.json).
