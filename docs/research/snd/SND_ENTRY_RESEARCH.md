# Supply/demand execution stress and entry mechanics

This isolated research campaign answers two questions about the Fresh Retest wick-zone strategy:

1. Does the stronger observed relaxed-FVG MNQ version survive higher costs, adverse fill prices, and nearby settings?
2. What changes when first-touch eligibility and stop-order lifetime are varied independently?

The [complete report](../../../artifacts/research/snd-entry-research-2026-09-25/REPORT.md) and [machine-readable analysis](../../../artifacts/research/snd-entry-research-2026-09-25/analysis.json) contain all declared outcomes and evidence checks.

## Findings

All 42 cases succeeded and verified, all five historical controls matched exactly, and the independent audit passed 2,168 checks with zero failures. All 21 predeclared MNQ stability checks passed. This is a targeted historical result, not an overall strategy-validation pass.

**Test 1 — relaxed-FVG MNQ, first touch and a five-minute order lifetime.** Results are USD net of modeled costs, with one contract. Full history is January 2022–July 2026; later history is January 2025–July 2026.

| Execution scenario | Full net | Later net | Full max drawdown |
| --- | ---: | ---: | ---: |
| Original cash-cost baseline | $6,951.50 | $5,464.00 | $1,718.75 |
| Twice commissions and cash slippage | $3,380.50 | $4,207.00 | $3,417.50 |
| Adverse one-tick price fills | $6,153.50 | $4,668.00 | $1,689.75 |
| Adverse two-tick price fills | $5,211.00 | $4,399.00 | $2,132.25 |
| Adverse two-tick price fills and twice commissions | $2,463.50 | $3,431.50 | $3,653.00 |

All six one-factor neighboring settings stayed profitable in the later period, from $846 to $6,553 with 379–421 closed trades each. Higher stresses substantially increased drawdown even while total profit remained positive. The baseline has 1,105 full-history trades, a 1.174 profit factor, and 390 later-period trades.

**Test 2 — separate entry eligibility and order lifetime, relaxed-FVG MNQ.**

| Eligibility / order lifetime | Full net | Later net | Full max drawdown | Full net at doubled cash costs |
| --- | ---: | ---: | ---: | ---: |
| First touch / 5 minutes | $6,951.50 | $5,464.00 | $1,718.75 | $3,380.50 |
| First touch / 15 minutes | $3,482.50 | $4,055.50 | $3,329.25 | -$1,201.50 |
| First or later touch / 5 minutes | $3,680.00 | $4,360.00 | $3,442.50 | -$2,654.00 |
| First or later touch / 15 minutes | $6,220.50 | $6,338.00 | $3,129.75 | $177.00 |

For this relaxed-FVG MNQ combination, the evidence favors retaining first-touch eligibility and a five-minute lifetime as the research baseline. Allowing later touches with fifteen-minute orders earns more in the later period, but its later drawdown is $2,581 versus $1,307.25 for the baseline, and its full-history profit nearly disappears at doubled costs. Eligibility and lifetime interact; neither can be judged solely from a test that changes both.

This does not prove first-touch is universally best. Under strict FVG on MNQ, any-touch/fifteen-minute orders earned $1,878.50 full-history versus the strict control's $1,097.50, but drawdown rose from $1,966.25 to $4,814.75. NQ's relaxed entry matrix also favors first-touch/five-minute orders in full and later dollar profit; it is related exposure, not an independent replication. MGC's relaxed baseline loses $2,101.50 full-history and $5,585 at doubled costs.

The preferred relaxed MNQ baseline still lost $293 in 2024, has slightly negative full-history mean net R (-0.0049), and its later mean-R interval spans zero (approximately -0.0457 to +0.1372). One-contract dollar profitability therefore does not establish an equal-risk sizing edge. Keep this as the reference for prospective validation; these already-inspected histories cannot establish that it is locked or ready for live trading. No strategy or Pine settings were promoted automatically.

## Fixed experiment

The [protocol](../../../artifacts/research/snd-entry-research-2026-09-25/protocol.json) declared 42 cases before their historical execution: 24 MNQ cases, nine MGC cases, and nine NQ cases. MNQ is primary; the other markets are transfer checks. Data covers January 2022 through July 2026, preceded by 30 calendar days of state warmup. All cases use one fixed contract and their declared costs. This history had already been inspected; it is not an untouched holdout.

Every market tests strict and relaxed FVG formation separately, with each of four combinations: first-touch/one-bar, first-touch/three-bars, any-touch/one-bar, and any-touch/three-bars. Every market also reruns relaxed first-touch/one-bar at doubled cash costs. MNQ adds actual adverse fill prices, costs across the relaxed entry matrix, and six one-factor neighboring settings.

The relaxed formation still uses wick zone boundaries. It requires the third candle's close to pass the base candle's wick, while strict FVG requires its whole wick to pass. Other formation directions and causal swing alignment remain unchanged.

## Entry timing

A one-bar stop order lives for the five minutes immediately after the signal; a three-bar order lives for fifteen elapsed minutes. Trigger, stop, opposing obstacle and expiry are frozen while pending. Gaps consume elapsed lifetime. Orders can cancel earlier under the existing validity rules.

First-touch eligibility only permits the original physical-touch candle to arm. Any-touch eligibility permits a first or later completed candle that actually overlaps a valid unused zone, including consecutive candles inside the zone. It does not continuously move the trigger when price is outside the zone. At the final lifetime bar's close, the old order expires before a new qualifying overlap can arm; first-touch can also arm a different zone first touched in that completed bar. A filled trade consumes its zone.

Cash slippage reproduces the prior simulator. Price slippage moves entry and non-limit exit fills adversely, then derives risk, target and opposing room from the actual entry. Fees remain separate; slippage is not charged twice. This deterministic stress may place modeled fills outside recorded OHLC and does not model queue position or liquidity.

## Reproduction and checks

The original engines, prior campaigns and Pine indicator are preserved. A separate simulator is necessary because Workbench event-v1 does not support this stop-entry lifecycle.

Files:

- `strategies/_snd_entry_research.py`: isolated simulator.
- `tests/test_snd_entry_research.py`: 23 focused checks passed before freezing, covering parity, expiry, eligibility, cancellations, chronology and adverse-fill accounting.
- `scripts/research-snd-entry-research.py`: declaration, data preview, source freeze and historical execution.
- `scripts/audit-snd-entry-research.py`: independent reconstruction from raw input without importing strategy code.
- `scripts/report-snd-entry-research.py`: saved-ledger metrics, five exact historical controls, declared checks and report generation.

For a new explicitly declared campaign, use a new output directory with `--declare --preview`, then `--freeze`, then `--run --workers 2`. Existing complete, failed or interrupted attempts are preserved. Do not edit the frozen protocol or execution source to alter an existing campaign. The reporter is separately captured by content hash at analysis time; execution, audit and inherited metric helpers are frozen before the runs.

```powershell
.venv/Scripts/python.exe scripts/audit-snd-entry-research.py
.venv/Scripts/python.exe scripts/report-snd-entry-research.py --require-complete
```

Passing the targeted historical checks does not override earlier losing periods, uncertainty in mean R, inspected-history selection, or missing prospective execution evidence. No live-readiness label or canonical-strategy change follows automatically from these tests.
