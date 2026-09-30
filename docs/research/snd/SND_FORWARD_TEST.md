# Frozen MNQ prospective test

This workflow records the unchanged strategy on bars arriving after a frozen start time. It is a local data collector and OHLC simulation, with a daily input check scheduled for 18:30 America/Chicago under Codex heartbeat `mnq-snd-forward-test`. It does not connect to a live feed or a broker. The daily cadence will normally produce **delayed prospective replay**, rather than timely paper-execution observations.

Initialized and frozen at **2026-09-26 04:29:17 UTC**, before the new sizing backtests ran. The prospective boundary is **2026-09-26 04:30 UTC** (September 25, 23:30 Chicago). The earliest review boundary is **2026-12-25 04:30 UTC**, also requiring 100 closed primary trades and data covering that boundary. The initial check and a manual run of the exact scheduled command both verified and retained zero poststart observations. Current state is **waiting for current warmup data**, not collecting live trades.

Keep the computer on and Codex running for this local scheduled check. The scheduled workflow preserves every outcome and pauses after delivering the first formal review. Its behavior follows the [official scheduled-task documentation](https://learn.chatgpt.com/docs/automations?surface=app).

The initial local inventory ends on **September 3, 2026 at 23:59 UTC**. That is too stale to initialize the strategy at the prospective boundary. The collector preserves a waiting record until current warmup and subsequent minute bars arrive. Setup is not a completed forward test.

## Rules fixed before new outcomes

The primary stream is MNQ, one contract. A second stream uses a **$100 fixed estimated stop-risk budget**, whole contracts, and a maximum of ten contracts. Both were selected before the new sizing backtest outcomes; the historical winner does not automatically replace either stream.

Both streams use wick boundaries, relaxed-FVG formation, strict pivot length two, completed-hour direction, first physical touch only, a stop entry valid for one elapsed five-minute interval, a zone stop, a 1R target, and at least 2R opposing room or no observed opposing obstacle. A later touch cannot revive the zone. Existing warmup, age, roll and session rules remain fixed.

Execution uses source one-minute OHLC. Entries and nonlimit exits receive one adverse tick in their actual simulated price; limit targets fill at their limit. Commission is $1.25 per contract per side. Quantity is fixed when the order arms. The risk-budget calculation includes the estimated entry and stop-exit slippage and both commissions. Entry gaps and stop gaps can still exceed the budget. Neither margin nor buying power is modeled.

Each check retains the current active position and pending order. It does **not** liquidate a position merely because that check reached the end of its available bars.

## Review criteria

The first formal review requires **90 calendar days and at least 100 closed primary-stream trades**, with source data covering the review boundary. Continue the same rules if the sample is smaller. The $100 shadow stream reports its own sample separately.

That sample can include delayed prospective replay, and the report separates it from timely observations. Reaching the sample threshold does not validate real-time fills or authorize live trading. Review marked net profit, closed-trade profit, profit factor, mean net R, marked drawdown, risk-budget overshoots, data quality and delayed-versus-timely counts. The raw ledgers support uncertainty analysis at that review; no minimum-profit claim is substituted for it.

The exact start, earliest review time, assumptions and criteria are saved in [protocol.json](../../../artifacts/research/snd-forward-2026-09-25/protocol.json). The start is the next five-minute boundary strictly after the actual UTC freeze time. Prestart bars are context and never prospective performance.

## Supplying bars

Put complete one-minute MNQ exports in [the artifact inbox](../../../artifacts/research/snd-forward-2026-09-25/inbox). The check also scans the local Workbench catalog for registered immutable MNQ one-minute versions. It makes no vendor requests and reads no credentials.

Supply CSV or Parquet with these columns:

| Field | Required interpretation |
|---|---|
| `ts_event` or `timestamp` | Timezone-aware minute **open**, preferably ISO UTC such as `2026-09-28T12:00:00Z`; a timezone-aware Parquet index also works |
| `open`, `high`, `low`, `close` | Unadjusted prices with valid OHLC geometry |
| `volume` | Finite nonnegative volume |
| `instrument_id` or `contract` | The actual futures contract identity on every bar, preserved across rolls |

The file must have ordered, unique minute timestamps. Keep contract identifiers consistent across exports. Do not supply a continuous root such as `MNQ` as if it were the actual rolling contract identity, or adjusted prices that alter the old historical path.

The initial catch-up needs approximately 30 calendar days before the frozen start, plus new poststart data. A coverage gate requires the warmup to begin within 72 hours of the requested boundary, cover at least 15 UTC dates, have no internal gap greater than 80 hours, and end within 72 hours before the start. These tolerances accommodate ordinary weekend closures; they are a coverage check, not an exchange-calendar completeness guarantee. The September 3 cache fails this gate.

Exact overlapping rows are allowed and retain their first recorded receipt time. Every raw file version is copied under its checksum. Changed accepted bars and late poststart insertions are quarantined, with the rejected source preserved. Missing prestart context can be added only before the first simulation. Once simulation has started, a correction needs a separately documented corrected replay; the original sequence is not overwritten.

Unfinished minute bars remain in the preserved raw file but are not accepted until closed. Simulation advances only through completed five-minute boundaries and never reads rows beyond that boundary.

## Commands

Run these from `C:\Users\vince\OneDrive\Desktop\Quant` with the existing project Python. Initialization must happen only once, after source review:

```powershell
.venv/Scripts/python.exe scripts/forward-snd-frozen.py init
```

For subsequent checks, use the preserved driver and specify the campaign directory:

```powershell
.venv/Scripts/python.exe artifacts/research/snd-forward-2026-09-25/source/scripts/forward-snd-frozen.py check --out artifacts/research/snd-forward-2026-09-25
.venv/Scripts/python.exe artifacts/research/snd-forward-2026-09-25/source/scripts/forward-snd-frozen.py status --out artifacts/research/snd-forward-2026-09-25
.venv/Scripts/python.exe artifacts/research/snd-forward-2026-09-25/source/scripts/forward-snd-frozen.py verify --out artifacts/research/snd-forward-2026-09-25
```

The working driver also works while its checksum equals the frozen copy. Source or Python/pandas/numpy changes cause a visible failure rather than silently changing the experiment. An interrupted check remains in its numbered directory. A leftover `.check.lock` should be investigated before any recovery; do not delete evidence or restart initialization to make an error disappear.

## Evidence retained on every check

The numbered `checks/` directories form a checksum chain. Even a check with no new bars records its timestamp, source age, coverage state and waiting reason. Raw snapshots and accepted-bar batches are hashed, and each check has its own checksum sidecar. Concurrent checks cannot write the same sequence.

When coverage is ready, each of the two streams writes:

- New events and a complete event snapshot: zone creation, signal decisions, order arming/cancellation/expiry, entries, exits and zone removal.
- Closed simulated trades, sizing decisions, marked equity, diagnostics and active-position/pending-order state.
- Counts of closed trades, mean net R, profit factor, marked drawdown, budget overshoots and whether the predeclared review criteria have been reached.

A later replay must preserve every earlier event and its content. It may append newly knowable events; removing or changing prior events fails the check and retains the attempted artifacts.

Poststart bars received more than **120 seconds after their minute close** are labeled `delayed_replay`. Event records separately use when they were first recorded versus when they could have been known. A trade receives the timely label only if its signal, entry, exit and recorded path bars meet the timing condition. Even `timely_ohlc_simulation` is an OHLC assumption, not an actual broker or TradingView fill.

Focused verification uses synthetic fixtures, not fabricated performance results:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p test_snd_forward.py -v
```

The 14 tests cover timestamps and contract data, revisions and late insertions, receipt classification, warmup gating, immutable driver/environment checks, clock regression, checksum chains, waiting checks, and actual nonfinalized model replay through an extension.
