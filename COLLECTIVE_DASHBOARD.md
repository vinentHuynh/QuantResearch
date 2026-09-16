# Combined strategy dashboard

Open `http://127.0.0.1:5173`, choose **Dashboard → Combined portfolio**.

The dashboard starts with the seven configurations that passed the available
later-period checks. Combined totals and the chart appear first. **Choose
strategies** jumps to the configuration picker; **Calendar** jumps to daily P&L.
Individual evaluations remain available in the other dashboard view.

## Build a combination

1. Filter by eligibility, market, timeframe, name or session.
2. Check configurations individually, or click **Apply visible strategies** to
   replace the combination. Filtering alone does not remove selected books;
   hidden selections are explicitly counted.
3. Set whole-number copies of each recorded book. Two copies double that book's
   dollar P&L and represented capital. This does not rerun risk-based sizing.
4. Choose dates and marked or closed-trade accounting. **Use common tested
   window** finds the intersection of the selected histories. Missing history
   blocks aggregation rather than becoming a zero return.
5. Inspect the market curves, daily bars, yearly and strategy contributions,
   and the calendar. Click a calendar date for each strategy's contribution.

Selections and settings persist in the browser. Export daily P&L as CSV and save
the combination, source identities and policy settings as JSON. Policy decision
logs have a separate CSV export.

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
data invariance, corrupt ledgers, and new workbench imports. Browser checks cover
filters, application of combinations, dates, chart/calendar drilldowns, exports,
persistence, mobile layout, policy controls and preservation of all 279 previous
workbench runs. Screenshots and the verification record are saved under
`reports/collective-dashboard-2026-09-16`.
