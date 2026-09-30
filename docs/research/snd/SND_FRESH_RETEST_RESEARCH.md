# SND fresh retest with hourly alignment

A new research strategy combining the most promising prior rule findings.
It is implemented separately from the original SND and transcript models in
[`strategies/_snd_fresh_retest.py`](../../../strategies/_snd_fresh_retest.py).
Combining the rules is a new hypothesis; prior support for individual filters
does not establish that the combination is profitable.

**Completed result:** all 40 declared simulations finished and reconciled, but
the candidate failed the historical validation requirements on both primary
markets. MNQ earned $1,097.50 over January 2022–July 2026 and lost $966 under
doubled costs; MGC lost $1,194.50 and $3,244 respectively. NQ was positive,
while ES, YM and CL were negative. No market or setting was changed after
seeing these outcomes.

See the [complete results and gates](../../../artifacts/research/snd-fresh-retest-2026-09-24/REPORT.md),
[equity charts](../../../artifacts/research/snd-fresh-retest-2026-09-24/candidate-equity.png), and
[independent ledger audit](../../../artifacts/research/snd-fresh-retest-2026-09-24/independent-audit.json).
The implementation passed 21 new tests, 14 original regression tests, the
production build and 2,284 independent ledger checks. All six legacy controls
reproduced the prior baseline trade and equity records.

The strict first-touch/one-candle entry restriction reduced total profit on
both primary markets relative to allowing later rolling entries. Opposing
room improved cash results on both primaries. These are observations from
the frozen comparisons; they do not justify changing the tested candidate
and labeling the revised strategy validated without another declared test.

## Frozen default rules

1. Build complete five-minute candles from one-minute source bars. Structure
   uses strict two-bar pivots that become known only after confirmation.
2. The last completed hourly direction and five-minute direction must agree
   when an entry zone forms and when an entry is armed.
3. Demand uses a bearish base, bullish middle candle and confirmed three-candle
   wick gap; supply is the mirror. Use the original transcript zone boundaries.
4. The first observed physical touch after formation consumes freshness even
   during warmup, an open position, a direction mismatch or an incomplete
   candle. Only the close of that first touching complete candle may arm entry.
5. Buy one tick above the touching candle's high, or sell one tick below its
   low. The order is valid during the immediately following five-minute bucket
   only. An expired opportunity cannot rearm later.
6. Place the stop one tick beyond the zone's distal boundary and the target
   one initial risk unit from the actual, gap-aware entry. Nearby fractional-R
   test targets are rounded toward entry to a valid tick; effective R is saved.
7. Require at least two initial risk units before the nearest opposing zone,
   or no known opposing zone ahead. Opposing context uses the same formations
   regardless of direction alignment. Freeze the obstacle at arming and recheck
   distance using actual entry price and stop risk; reject an adverse gap that
   removes the required room.
8. Use one fixed contract and one open position. Retain the full trading-day
   session, 288 observed-candle zone expiry, 100-zone caps and 30-day warmup.
   There is no volume/RVOL filter, extra impulse/width threshold, extra BOS
   requirement, opposing-zone exit or discretionary news/session exclusion.

“First touch” here is stricter than an entire multi-candle first-touch episode
in older SND. It also replaces the transcript's potentially long sequence of
rolling entry attempts. The matched `without_first_touch` control measures this
whole freshness/entry-expiry rule, not freshness independently of order lifetime.

The gap rejection is a price-protection rule, not a claim that an ordinary
broker stop order can reject its fill after execution. With obstacle B, stop S
and required room k, the permissible long entry is at most `(B + k*S)/(1+k)`;
the short entry is at least that value. An order implementation would floor
the long cap or ceil the short cap to the instrument's tick. The limit is known when the order is
armed. The simulator cancels an order if the triggering opening gap exceeds
this bound, without crediting a later rebound fill inside that same minute.
Cancellation at that observation is idealized: a real resting stop-limit could
fill on a rebound before cancellation completes. No broker-specific stop-limit
queue or cancellation latency is modeled.

## Frozen retrospective validation

The protocol is under
[`artifacts/research/snd-fresh-retest-2026-09-24/protocol.json`](../../../artifacts/research/snd-fresh-retest-2026-09-24/protocol.json).
MNQ and MGC are the declared primary markets. NQ, ES, YM and CL are transfer
checks; NQ and MNQ are related contracts, not independent confirmation. GC is
excluded because only five-minute execution bars are available for it.

The 40 declared cases include the candidate, each new filter removed separately,
both removed together, and primary-market checks for hourly alignment, FVG
qualification, nearby pivots/targets, doubled costs and additional slippage.
Removing both new filters restores the previous transcript baseline for parity.
No settings or markets are selected using this campaign's outcomes.

Scoring covers January 2022 through July 2026. Report 2024, 2025 and
January–July 2026 separately, along with pooled later evidence. This history was
already inspected in prior research. These are retrospective checks, not an
untouched holdout or a prospective paper-trading record.

One fixed contract with $100,000 reference equity is not equal-risk sizing.
Fees per side are $1.25 for MNQ/MGC and $2.50 elsewhere. Charge one tick on
entry and market/stop exits, and commission only on target limits. Report
net dollars, risk-normalized R, net profit factor and marked drawdown together.
The doubled-cost primary cases are actual reruns; arithmetic cost repricing
provides a separate consistency check.

## Reproduction

```powershell
.venv/Scripts/python.exe scripts/research-snd-fresh-retest.py --declare --preview
.venv/Scripts/python.exe -m unittest discover -s tests -p test_snd_fresh_retest.py -v
.venv/Scripts/python.exe scripts/research-snd-fresh-retest.py --freeze
.venv/Scripts/python.exe scripts/research-snd-fresh-retest.py --run --workers 2
.venv/Scripts/python.exe scripts/report-snd-fresh-retest.py --require-complete
```

Existing attempt artifacts are retained, not overwritten on rerun. The declared
protocol, immutable source copies, dataset hashes, per-case inputs, complete
trade ledgers, equity marks and errors preserve both favorable and unfavorable
results. The simulator runs the frozen copy of the new model.

Native Workbench `event-v1` has no stop-entry order type, so the research uses
the separate simulator instead of substituting next-open fills. It does not
register a misleading native strategy or grant a Working badge. There is no
broker execution or certified TradingView parity.

## Execution limitations

The inherited simulator resolves stop/target ambiguity conservatively, uses
one-minute execution and five-minute equity marks, and excludes incomplete
aggregate candles from setup formation. Physical touches still consume zones
when an incomplete candle contains the observed touch. A first-touch timestamp
identifies the source candle interval, not the exact tick.

Identifiable contract changes retain the previous engine's idealized liquidation
at the prior source close. That is a data-boundary adjustment, not an executable
roll-timing signal. Gold lacks instrument identifiers. Continuous prices, gaps,
missing/no-trade minutes, queue effects and unmodeled margin remain limitations.
Bootstrap intervals are exploratory and are not adjusted for all comparisons.

Passing accounting tests proves consistent execution of the specification.
Passing numeric historical gates would supply retrospective evidence only.
Neither result establishes suitability for live trading.
