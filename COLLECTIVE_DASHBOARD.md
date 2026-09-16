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

1. In **Add**, filter by eligibility, market, timeframe, name or session.
2. Check configurations individually, or click **Apply visible strategies** to
   replace the combination. Filtering alone does not remove selected books;
   hidden selections are explicitly counted.
3. Set whole-number copies of each recorded book. Two copies double that book's
   dollar P&L and represented capital. This does not rerun risk-based sizing.
4. In the Combination panel, choose dates and marked or closed-trade
   accounting. **Use common tested
   window** finds the intersection of the selected histories. Missing history
   blocks aggregation rather than becoming a zero return.
5. Inspect the market curves, daily bars, yearly and strategy contributions,
   and the calendar. Click a calendar date for each strategy's contribution.

Selections and settings persist in the browser. From the Combination panel,
export daily P&L as CSV and save the combination, source identities and policy
settings as JSON. Policy decision logs have a separate CSV export in **Pause &
sizing**.

## Eligibility means evidence, not live approval

- **Working:** every available later-period baseline, cost and declared
  execution/risk check passed. Remaining weaknesses are still shown.
- **Fully tested & feasible — research:** working, with completed execution and
  nearby parameter-sensitivity checks and no known session-exit flag. This is a
  historical checklist. It does not certify exchange calendars, roll treatment,
  capital/margin sufficiency, TradingView parity, statistical certainty or live
  execution.
- **All tested configurations:** includes failed, screened-only and benchmark
  configurations. Profitable screening results do not automatically qualify as
  working. SND's four next-open variants are available on all five markets.
- **Screened only:** configurations without the completed later-period campaign.

Current imported evidence: **312 configurations, seven working, one passing the
stricter checklist**. The latter is ES daily moving-average trend; its small
trade sample remains a limitation. Stress/execution alternatives are validation
evidence, not additional books to add to the same portfolio.

## Accounting and the combination score

The portfolio is the sum of independent recorded strategy books. Capital is the
sum of each book's recorded starting capital times its copies. There is no
position netting, shared-margin model, portfolio rebalancing or capital-based
resizing. Overlapping strategies can create highly correlated exposure.

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
| Represented capital | $700,000.00 |
| Return on represented capital | 96.94% |
| Maximum daily marked drawdown | $111,856.25 / 11.76% |
| Recovery factor | 6.07 |

These strategies were selected after reviewing these periods. The combined
historical curve is not untouched portfolio validation.

## Optional pause/resume experiment

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
saved under `reports/pause-rule-research-2026-09-16`.

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

**Refresh evidence** rebuilds a versioned, checksum-verified catalog from the
completed campaign, expanded-search and SND ledgers. Newly completed workbench
baselines are also discovered from the read-only database; stress and training
runs are excluded. A matching newer baseline replaces the older catalog sleeve
instead of being added twice. Earlier matching later-period failures remain
flagged. New imports do not receive full-checklist status automatically.

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
`reports/collective-dashboard-2026-09-16`.
