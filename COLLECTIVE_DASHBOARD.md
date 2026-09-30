# Combined strategy dashboard

Open `http://127.0.0.1:5173`. The app lands on **Portfolio → Combined
portfolio**, and the sidebar link always returns to it.

The portfolio starts with the seven configurations that passed the available
later-period checks. It has four views: **Overview** (totals, chart, market and
year tables), **Calendar** (daily P&L with the selected day's breakdown beside
it), **Contributions**, and **Pause & sizing**. The **Combination** panel on
the right stays visible in every view; **Add** opens the configuration picker.
Individual evaluations are under **Portfolio → Strategy scorecards**.

## Build a combination

1. In **Add**, use the compact filter tabs above the configuration table.
   The default **Evaluation passed** includes configurations with additional
   robustness checks. Filter by milestone, market, timeframe, name or session;
   **All tested** includes earlier research and benchmarks.
2. Check configurations individually, or click **Apply visible strategies** to
   replace the combination. Filtering alone does not remove selected books;
   hidden selections are explicitly counted.
3. Set **Starting capital (USD)** in the Combination panel. It defaults to
   $100,000 shared across the entire portfolio. Set whole-number copies of
   each recorded book; two copies double its dollar P&L and exposure while total
   capital stays fixed. This does not rerun risk-based sizing.
4. In the Combination panel, choose dates and marked or closed-trade
   accounting. **Use common tested
   window** finds the intersection of the selected histories. Missing history
   blocks aggregation rather than becoming a zero return.
5. Inspect the market curves, daily bars, yearly and strategy contributions,
   and the calendar. Click a calendar date for each strategy's contribution.

Contributions lists **Strategy** and **Chart** separately; Chart identifies the
market, timeframe and session. **Maximum drawdown** is each strategy's largest
peak-to-trough dollar loss within the selected dates, starting its cumulative
P&L at zero. It uses the chosen accounting basis, copies and active pause/sizing
replay. Drawdowns are measured at daily observations and do not capture intraday
extremes. Individual strategy drawdowns are not additive portfolio drawdown.

Selections and settings persist in the browser. From the Combination panel,
export daily P&L as CSV and save the combination, source identities and policy
settings as JSON. Policy decision logs have a separate CSV export in **Pause &
sizing**.

## Research milestones

The picker uses the same milestones as scripts, library and evaluations, in the
original compact table layout. The Evaluation passed tab includes Robustness
checked configurations; Backtested only excludes both and benchmarks.

- **Backtested:** a recorded simulation is available. Includes exploratory,
  incomplete and failed-check configurations; inspect their findings before
  planning the next baseline/stress evaluation. Coverage dates do not pass tests.
- **Evaluation passed:** available later-period baseline, cost and declared
  execution/risk checks passed. Maps to the existing `working` catalog flag.
- **Robustness checked:** evaluation plus completed historical execution and
  nearby-parameter checks. Maps to the existing `working` and `feasible` flags.
- **Benchmarks:** comparison references, listed separately from validation stages.

Each row identifies the symbol, chart, coverage, original findings
and exact parameters. A failure on another configuration does not invalidate
a passing one. Adding a book includes its history for portfolio research; it
does not promote its evidence. The milestones describe historical research,
not live approval. Catalog eligibility and original evidence are preserved.

Imported evidence after the September 16 review: **386 configurations, seven working, one passing the
stricter checklist**. The latter is ES daily moving-average trend; its small
trade sample remains a limitation. Stress/execution alternatives are validation
evidence, not additional books to add to the same portfolio.

## Accounting and the combination score

Coverage errors show each affected book's tested dates and offer **Apply common
tested window** directly in the unavailable view, including on mobile. The common
window intersects the recorded coverage spans of all selected books and chooses
the longest continuous overlap (the latest on ties); it never bridges an untested
gap. With no overlap, the view offers **Review configurations**. Dates change only
when the user applies the window; missing history is never treated as zero P&L.

The portfolio sums recorded strategy P&L against one editable starting balance.
Equity equals shared starting capital plus cumulative combined P&L; return is
combined P&L divided by that starting capital. Percentage drawdown uses the peak
of this shared equity path. Each strategy's return contribution uses the same
denominator. Adding strategies or copies does not add capital. There is no
position netting, shared-margin simulation, portfolio rebalancing or automatic
capital-based resizing. Overlapping strategies can create correlated exposure.

Settings without a valid saved capital amount default to $100,000 total.
Capital edits persist across reloads. Overview omits the separate starting-capital
and ending-equity cards; edit capital in Combination. Combination JSON version 2 declares
`capital_model: "shared"` and includes this capital; daily CSV includes
`starting_capital` and the shared equity path. If equity reaches zero or below,
the dashboard flags exhaustion and retains the full loss path. It does not
simulate liquidation. Individual backtest inputs and historical reports retain
their original capital assumptions.

All calendars use UTC dates. Marked mode includes open P&L at daily observations;
closed mode books a complete net trade at its exit date. Fees and slippage already
present in the ledgers are retained. The calendar distinguishes dates outside
the test window from covered days with no recorded change. Missing source-market
bars are not reconstructed as additional price observations.

The score is transparent: **net P&L / maximum drawdown in dollars**. It is a
descriptive recovery factor, not a probability or an optimized allocation score.
Drawdown uses daily marks or closed-trade equity, depending on the selected mode;
it omits intraday extremes. Profit factor and winning-trade rate use closed trade
events. Copies scale cash flows, not the count of distinct trade events.

For the default seven-book combination over January 2024–August 2026:

| Measurement | Result |
| --- | ---: |
| Net P&L | $678,605.00 |
| Shared starting capital | $100,000.00 |
| Return on shared capital | 678.61% |
| Maximum daily marked drawdown | $111,856.25 / 33.33% |
| Recovery factor | 6.07 |

These strategies were selected after reviewing these periods. The combined
historical curve is not untouched portfolio validation.

## Optional pause/resume experiment

### Replay version 3: sizing comparisons and risk controls

New browser settings start with **Constant size (no pause)** at 0.75x, replay
disabled. Existing saved modes remain selected, and existing volatility settings
retain the explicitly labelled legacy estimator. The original rolling, streak,
drawdown and manual experiments remain available.

The Pause & sizing view now includes 50%, 75% and 100% constant-exposure
benchmarks on the same books, dates and accounting basis, with net P&L, maximum
dollar drawdown, worst day and recovery factor. Benchmarks retain the same
shared starting capital and proportionally scale recorded net costs; they are
fractional exposure comparisons, not executable contract allocations. Export
comparison saves these metrics; Export entry sizes saves each entry's final
multiple, accepted status and represented quantity. Average exposure includes
zero-sized/skipped closed-trade opportunities.

Modern volatility sizing uses observed daily marks including zero P&L, with
either sample standard deviation or normalized exponentially weighted variance
(decay `1 - 2 / (lookback + 1)`). Missing dates are not fabricated. The default
25-observation lookback, 50%-of-target volatility floor, 0.25x maximum change
per entry and 1x cap are research defaults. The target is the median valid
daily volatility estimate through a separately saved calibration date (default
2023-12-31), requiring at least 20 estimates. Decisions use only marks dated
before entry. Calibration history is not sized retrospectively; entries through
calibration retain baseline exposure. Moving the reporting window cannot refit
the target. A scored start on/before calibration is rejected.

**Portfolio-aware volatility sizing** adds a conservative concurrent-exposure
cap. Its automatic dollar target comes from frozen book volatilities and shared
calibration correlations; a user dollar cap can replace it. At entry, trailing
correlations use shared observed dates only, shrink halfway toward +1, receive
no negative-correlation hedge credit, and default to +1 when unavailable. The
optional equity-index cap groups ES/NQ/YM/RTY and their micros. Equal-timestamp
entries share remaining risk pro rata; existing trades keep their size and exit.
The cap estimates risk from recorded daily book P&L, not actual open-position
stop distances. Portfolio caps can cut size faster than the per-book step limit.

An optional **portfolio closed-loss limit** is independent of the performance
monitor. It measures realized peak-to-trough losses after calibration, observes
only exits strictly before each entry, and blocks new entries for the remainder
of the replay after a breach. Equal-time exits are settled together. It does not
liquidate open positions, cap intraday losses, or reset with the chart window.
Dollar limits are off until configured; zero in portfolio mode means its
automatic volatility target, not a user loss allowance.

**Sustained deterioration / manual review** compares the recent mean of trade
P&L divided by entry-time volatility against a frozen reference of at least 50
normalized trades. Default: 30 recent trades, shortfall of two reference standard
errors, and five consecutive qualifying observations. This is a review heuristic,
not a confidence level: overlapping windows and serial dependence invalidate
a naive significance interpretation. A breach stays paused until a dated manual
resume, which resets the monitoring window. Shadow winners never auto-resume it.

Evidence imports now preserve actual whole-contract quantities and recorded
costs where available, in new checksum-addressed histories. Older histories and
source runs remain intact. Whole-contract mode rounds down **after** copies and
portfolio caps; absent quantities block the replay rather than assuming one.
An optional shared margin budget uses the user's uniform per-contract margin
assumption and counts overlapping trades. No margin or stop-risk budget is
invented. Micros require their own data and fees. This remains fixed-ledger
research: strategy state, nonlinear costs, changing brokerage margin and
intraday open risk require a full stateful rerun.

`npm run test:sizing` checks causal calibration, zero sessions, simultaneous
entries, covariance caps, contract/copy rounding, shared margin, loss boundaries
and deterioration/manual-resume behavior. `node scripts/validate-risk-sizing.mjs`
checks UI controls, comparisons, persistence, CSV export and mobile layout.
`node scripts/research-risk-sizing.mjs` freezes settings and source checksums
before running eight declared development comparisons into a new timestamped
report folder; failed, unavailable and zero-trade results remain visible. It
does not optimize settings or promote a configuration. Previously reviewed
2024–2026 data is not a fresh holdout.

### Replay version 2

The dashboard now offers **Manual pause / resume schedule** alongside the three
automatic loss rules and volatility scaling. Select a book, a UTC timestamp,
an action and a reason. A manual pause blocks entries at or after that timestamp
until the next dated resume. Already-open trades retain their recorded exits.
Manual mode does not apply automatic loss rules. Decisions persist with the
browser's combination, can be removed, and are included in the combination JSON
and decision CSV exports. Turning replay off retains the schedule but restores
always-on results. Retrospective manual choices are not prospective validation.

Automatic recovery now requires completed shadow trades **entered after the
pause**. The triggering loss and positions already open at the pause do not count
toward recovery. Both the calendar cooldown and a positive aggregate outcome over
the required recovery trades must pass. A ready cooldown expires without needing
another exit. New losses after expiry belong to the new observation segment.
Equal-timestamp exits remain unavailable to entries at that timestamp.

The per-book status table shows the reason, cooldown expiry, recovery count and
P&L, and the skipped trades' P&L at the reporting cutoff. These are historical
entry controls; they do not stop worker processes or send broker orders.

Fresh replay of the seven working books, January 2024–August 2026, one copy each:

| Closed-trade accounting | Net P&L | Maximum drawdown dollars | Recovery factor |
| --- | ---: | ---: | ---: |
| Always on | $678,605.00 | $105,025.00 | 6.46 |
| Corrected default rolling pause | $382,057.50 | $106,050.00 | 3.60 |
| Default losing streak | $315,547.50 | $120,295.00 | 2.62 |
| Default shadow drawdown | $372,060.00 | $118,617.50 | 3.14 |
| Volatility scaling | $407,922.27 | $83,678.25 | 4.87 |

These parameters were not optimized. The default rolling pause gives up
$296,547.50 and does not improve drawdown. See
`artifacts/research/workbench-review-2026-09-16/collective-analysis.json` for the fresh audit.
The older pause results and sweeps below describe replay version 1 and are
retained as historical evidence; their exact figures do not describe version 2.

Focused regression checks include manual timestamp boundaries, per-book
isolation, disabled replay, overlapping positions, post-pause recovery, cooldown
expiry without an exit, future invariance, invalid settings, and historical
portfolio reconciliation. `node scripts/validate-pause-resume.mjs` exercises
manual controls, persistence, decision removal, export and mobile layout.

The controller can pause new entries after rolling closed-trade losses, a losing
streak, or a shadow-equity drawdown. It uses only trades closed strictly before
the entry timestamp. Equal-timestamp exits are not available to an entry. Trades
accepted before a pause keep their original exits, including positions crossing
the reporting-window boundary.

While paused, the controller continues observing hypothetical (shadow) trades.
It resumes only after the calendar-day cooldown and a positive aggregate outcome
over the configured number of recent shadow recovery trades. Recovery resets the
observation segment to avoid immediately reusing the original loss trigger.
Earlier available trades initialize controller state before the displayed period;
future outcomes cannot alter earlier decisions.

This is a **fixed-ledger entry-filter replay**, not a fresh simulation of strategy
state, position sizing, margin or executable orders. Skipping positions can
change those states. Consequently the replay uses closed-trade accounting and
keeps an always-on comparator on the same basis. It is exploratory and controls
no broker connection.

The default rolling rule (10 trades, negative aggregate P&L, five calendar days
cooldown, three recovery trades) produces **$359,577.50** for the same seven-book
period—**$319,027.50 less** than always on. No parameters were optimized to rescue
this result. A production controller would require a full stateful rerun and
prospective validation with fixed rules.

### What the evidence says about pausing

A 312-combination sweep over the three loss rules (lookback 5–30 trades, loss
threshold $0–$10,000, streak 2–7, drawdown $2,500–$40,000, cooldown 1–20 days,
recovery 1–5 trades) on the seven-book 2024–2026 window found **no combination**
that beat always on, on net P&L or on the recovery factor. The only combinations
that matched always on were those that never triggered. Across calendar years
2018–2026 the default rule trailed always on in eight of nine years (2023:
+$17,818; every other year between −$37,065 and −$130,600). Skipped trades
averaged more than accepted trades in every book. The sweep and diagnostics are
saved under `artifacts/research/pause-rule-research-2026-09-16`.

The reason is structural, not parametric. Kaminski & Lo (*When do stop-loss
rules stop losses?*, 2014) show that a loss-triggered stop can raise expected
return only when outcomes have positive serial dependence; under a random walk
it always lowers it, and under reversal it skips recoveries. No working book
shows persistence. On 2018–2023 trades (the sample the dashboard uses) the
runs-test z runs from +0.8 to +2.2, four books sit above +1.96, and lag-1 trade
autocorrelation is negative in all seven (−0.11 to −0.15); on 2024–2026 trades
z runs from −0.6 to +1.5. If anything the books reverse: the mean trade after a
loss exceeds the mean trade after a win in all seven, and on 2018–2023 data the
mean trade after a win is negative for the five overnight and ORB books.
Mirroring the rule (pausing after gains) gives $451,360, closer to always on
but still below it. Neither direction is worth trading on this evidence.

The dashboard shows this check whenever the replay is enabled (**Do losses
cluster?**): per book, the runs-test z, lag-1 autocorrelation and conditional
means, computed from trades closed before the window when at least 30 exist.
A pause rule has a statistical basis only for books flagged *Losses cluster*.

### Volatility scaling instead of pausing

The fourth mode, **Scale size by realized volatility (no pause)**, replaces the
on/off decision with sizing (Carver, *Leveraged Trading*; Harvey et al., *The
Impact of Volatility Targeting*, 2018). Each entry is scaled by target ÷ recent
volatility, where volatility is the standard deviation of the book's last 25
non-zero marked daily P&L values dated before the entry, and the target is the
median of that estimate over entries dated before the reporting window. Sizes
are fixed at entry and capped at 2×. The mode never skips a trade, so the replay
remains a re-weighting of the fixed ledger. Cooldown and recovery do not apply.

For the seven-book 2024–2026 window (closed accounting; Sharpe and tails from
the saved research script on days with activity):

| Measurement | Always on | Default pause | Volatility scaling |
| --- | ---: | ---: | ---: |
| Net P&L | $678,605 | $359,578 | $407,922 |
| Maximum drawdown | $105,025 | $112,300 | $83,678 |
| Recovery factor | 6.46 | 3.20 | 4.87 |
| Daily Sharpe | 1.67 | 1.03 | 1.63 |
| Worst day | −$49,737 | −$49,737 | −$37,084 |
| Average size | 1.00× | — | 0.74× |

Volatility scaling keeps the Sharpe ratio, cuts the worst day and the 5% tail
by about a quarter, and reduces the maximum drawdown by a fifth, at lower
average exposure because 2024–2026 volatility ran above the 2018–2023 median.
It adds no return; it removes the days a pause was meant to remove without
conditioning on P&L. Fractional multiples assume divisible contracts (micro
contracts in 0.1 steps give $406,238 at the same Sharpe).

Neither mode is a live controller. A dollar drawdown stop-out calibrated on
2018–2023 daily P&L under IID assumptions (Bailey & López de Prado,
*Drawdown-based stop-outs and the triple penance rule*, 2014) would have stopped
four of the seven books during sharp, short 2024–2026 drawdowns that preceded
their best stretch; those were volatility events, which sizing addresses and
stopping does not. Monitoring for genuine decay belongs on win rate or
volatility-normalised outcomes (a CUSUM on raw dollar outcomes alarms on every
volatility spike), and a book that fails such a check should be re-examined,
not resumed automatically after three winning shadow trades.

## Data refresh and validation

### Strategy condition and permission (condition version 1)

The Pause / sizing view now assesses baseline strategy condition independently
of entry permission. `Enabled` means the replay permits entries; it does not
mean the strategy is profitable recently. Manual decisions and position sizing
do not reset the descriptive history. The condition panel remains available
when replay is off or the selected portfolio cannot be calculated.

Latest replay shows the last historical snapshot and explicitly reports status
unavailable when the requested current date exceeds simulation coverage.
Selected date allows a historical cutoff. Registered market-data timestamps,
simulation coverage, latest marked observation and latest natural exit are
separate. No ingestion or exchange-session completeness guarantee is inferred.

The panel reports the last 10/30 natural trades and 20 observed UTC marked days,
with exact dates and counts, daily exposure overlap, current marked drawdown
since equity inception, and calendar time below the peak. Forced exits remain
in accounting but do not enter natural-trade statistics or pause triggers.
Recorded exit reasons are preserved; legacy signal-worker classifications are
explicitly identified as timing inferences. Unknown exit types are excluded
from natural statistics and make the loss streak unknown.

Research CUSUM uses daily P&L divided by preceding 25-observation volatility,
with a frozen floor, location and scale estimated through 2023-12-31. It excludes
terminal marks and restarts at independent simulation segments. At least 250
reference observations and 20 monitored observations in the current segment
are required. `Watch — recent losses` is descriptive: a complete 10-trade or
20-observed-day window lost money. `Unusual weakness` is a calibrated research
threshold crossing, not a finding that future expectancy is negative.

Recovery requires 20 new observations averaging at least the reference level
and CUSUM below half its alarm threshold. `Recovery developing` lasts up to 20
further observations unless weakness recurs. Recovery never authorizes entries.
The older trade-based deterioration rule remains a separate permission policy.

`node scripts/calibrate-strategy-condition.mjs` freezes a protocol before
evaluation, fits only pre-2024 reference outcomes, and uses joint circular blocks
of 5/10/20 observed days across the selected working books. It chooses the most
conservative trained 95th-percentile maximum CUSUM over 252 observations, then
checks separate simulated paths against a prespecified 8% Wilson upper-bound
ceiling (nominal family alarm target 5%). It also reports injected 0.5/1 SD mean
shifts, recovery and doubled-volatility stress. This accounts for reference-mean
uncertainty conditionally on the fitted reference. The stress doubles
standardized-residual volatility, not raw market volatility; its high warning
rate is shown explicitly because the detector cannot identify mean deterioration
separately from a change in residual variance. This does not cover every
parameter uncertainty, source-selection bias, future structural changes, or
indefinite repeated monitoring. Existing inspected years are development data,
not an untouched holdout. Full outputs are timestamped under reports.

Calibration is tied to source checksums. Refresh invalidates changed sources;
uncalibrated configurations retain descriptive loss windows and display
insufficient detector evidence. JSON condition exports include source hashes,
calibration, date cutoffs and a separately dated permission snapshot. Historical
pause tables elsewhere in this document predate natural-exit filtering and are
not updated measurements of the new rules.

Focused verification: `node scripts/test-strategy-condition.mjs` and
`node scripts/validate-strategy-condition.mjs`, plus the existing sizing,
collective-import, worker and production-build checks.

**Refresh evidence** rebuilds a versioned, checksum-verified catalog from the
completed campaign, expanded-search and SND ledgers. Newly completed workbench
baselines are also discovered from the read-only database; stress and training
runs are excluded. A matching newer baseline replaces the older catalog sleeve
instead of being added twice. Earlier matching later-period failures remain
flagged. New imports do not receive full-checklist status automatically.

The September 29 ES/NQ continuation lives under
`artifacts/research/combined-es-nq-refresh-2026-09-29`. It replays five existing sleeves
against the newly registered ES/NQ datasets using their frozen source rules.
The importer checks all five extensions together, corrects the August 31
overnight boundary, and retains the original catalog IDs and saved-selection
links. The extension is exploratory; prior evaluation labels apply to the
earlier tested windows. ES sleeves cover September 29; NQ sleeves stop at the
last complete common session on September 28. The seven-book combination still
ends August 31 because its YM and MNQ sleeves were not refreshed.
When a saved browser combination still ends in August, the portfolio offers
**View latest ES/NQ**. It selects the five refreshed books, preserves an existing
start date within their common window, and ends on September 28. The prior
combination is retained in browser storage for **Restore previous combination**;
the same view can be opened directly with `?portfolio=latest-es-nq#/portfolio/calendar`.

The importer writes immutable history files under `data/workbench/collective`
and atomically publishes the index last. The API checks each history's hash before
serving it. Original research artifacts and the workbench run ledger are unchanged.
The refresh operation is local and accepts no strategy code or shell commands
from the browser.

Commands:

```text
npm run research:collective
npm run test:collective
node scripts/test-collective.mjs --real
.venv/Scripts/python.exe -m unittest discover -s tests -p test_collective_import.py -v
node scripts/validate-collective.mjs
npm run test:dashboard
npm run build
```

Focused checks cover combined totals, capital/copies, internal coverage gaps,
leap dates, first eligible entry timing, shadow recovery, carried trades, future
data invariance, the loss-clustering diagnostic, causal volatility scaling,
corrupt ledgers, and new workbench imports. Browser checks cover the direct
`#collective-strategies` link, filters, application of combinations, dates,
chart/calendar drilldowns, exports, persistence, mobile layout, all four policy
modes with the loss-clustering table, and preservation of all 279 previous
workbench runs. Screenshots and the verification record are saved under
`artifacts/research/collective-dashboard-2026-09-16`.
