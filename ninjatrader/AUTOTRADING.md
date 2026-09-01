# Setup to run these two strategies automated in NinjaTrader 8

Order matters. Steps 1–2 are blocking; nothing below them can be tested without
them.

---

## 0. What is missing right now

**No connection is configured.** `Config.xml` holds only the *Simulated Data
Feed* and *Playback Connection*, `<DefaultAccount />` is empty, and there are no
cached connection tokens. `PreferredRealtimeFutureConnection` points at
`Provider31` but nothing is authenticated against it.

This blocks live trading *and* Sim101. Sim101 simulates the **broker**, not the
**market** — it still needs a real-time data feed to produce bars. Options:

- A prop/broker account that ships its own feed (Lucid runs on Rithmic or
  Tradovate; the eval purchase includes the connection)
- A data-only subscription — Kinetick or NT Continuum — paired with Sim101

## 1. Compile — pending

**New → NinjaScript Editor → F5.** Both files are already in
`bin\Custom\Strategies\` and compile clean in isolation. NinjaTrader builds every
file in `bin\Custom` as one assembly, so a failure will most likely name
`3wick.cs` or a `SupplyDemandZones` variant rather than these.

## 2. Connect and pick an account

Control Center → **Connections**. Once connected, the account dropdown shows
`Sim101` plus any live/funded accounts.

## 3. Platform settings that matter

**Tools → Options → Strategies.** Current values, read from `Config.xml`:

| Setting | Current | Keep? |
|---|---|---|
| `ConnectionLossHandling` | `Recalculate` | **Yes.** On reconnect NinjaTrader recomputes what the position should be and syncs to it. For a strategy holding 12 hours, `Stop Strategy` is the dangerous choice — it leaves a live position at the broker with nothing managing it. |
| `NumberRestartAttempts` | `4` | Yes |
| `RestartsWithinMinutes` | `5` | Yes |
| `CancelExitsOnStrategyDisable` | `false` | **Yes — important.** Disabling the strategy leaves the protective stop working. |
| `CancelEntriesOnStrategyDisable` | `false` | **Change to `true`.** Otherwise disabling the strategy can still leave a pending entry that fills into a position nothing is managing. |

Also confirm **"submit live working historical orders" is OFF**. NinjaTrader
replays historical bars when a strategy starts; you do not want that replay
producing real orders.

**Time zone** must be Eastern (Tools → Options → General), or every clock input
in both strategies shifts.

## 4. Enable a strategy

Control Center → **Strategies** tab → right-click → **New Strategy**.

| Field | Value |
|---|---|
| Instrument | MNQ (front month, or a continuous with back-adjust) |
| Bars | 5 Minute |
| Session template | CME US Index Futures ETH |
| **Days to load** | **≥ 120** |
| Account | `Sim101` first |

Then tick **Enabled** on the row, and confirm the master strategy toggle is on.

**Days to load is not optional.** Both strategies rebuild a rolling 25-session
close history from the bars NinjaTrader replays at startup, and neither will size
a position until it has 26 sessions. Load too few days and the strategy runs but
silently never trades.

## 5. Strategy-specific requirements

### OrbCarver — the tolerant one

- `Calculate.OnBarClose`, so a brief feed hiccup between bars costs nothing.
- Active 09:35–16:00 ET only. The machine has to be up during RTH, not overnight.
- Bracket is a real stop-market plus limit, working at the broker — they survive a
  NinjaTrader disconnect.

### OvernightDriftCarver — the fragile one

- `Calculate.OnEachTick`, so it needs a **live tick feed**, not just bar data.
- **The realtime entry fires once, at the first tick of the 18:00 bar.** If the
  strategy is not enabled and connected at that instant — NinjaTrader restarting,
  feed down, you enabled it at 18:20 — the night is skipped. It does not chase a
  missed entry. That is deliberate and matches the backtest, but it means uptime
  at 18:00:00 is the whole game.
- **Holds ~12 hours unattended**, and has **no stop by default**. If NinjaTrader
  is down at 06:00 the exit does not fire and you carry the position into RTH with
  nothing managing it.
- Power: sleep and hibernate are already `Never` on AC, but **on battery the
  machine sleeps after 10 minutes**. Keep it plugged in, or it will sleep through
  the position. A VPS is the real answer for a 12-hour unattended hold.

## 6. Sequencing before real money

1. **Sim101, one month minimum.** Compare actual fills against the backtest's
   exit mix (42.6% stopped / 15.5% target / 41.9% flat-at-close for ORB) — that
   mix moves on mechanical errors long before P&L does.
2. **Market Replay.** This is the *only* reproducible way to exercise
   `OvernightDriftCarver`'s realtime entry path. Strategy Analyzer runs everything
   as `State.Historical` and never touches that branch — the branch most likely to
   hold a bug.
3. **Live, small**, and only once a real account clears the capital floor.

## 7. Before you enable anything on a funded account

Two findings from this workspace that setup cannot fix:

- **Capital.** Carver's 4-lot floor is ~$190k (MES) to $525k (MNQ) for ORB, and
  ~$379k/$1.05M for the overnight rule. Below that the vol targeting is not
  running — the system is fixed-size, and every risk number in the backtest is
  void.
- **Prop containers.** Across all four LucidPro sizes and every contract count,
  the historical one-lot drawdown exceeds the max loss limit, and ORB's pass rate
  (44.3%) is indistinguishable from the 44.4% a zero-edge coin flip produces
  against the same geometry. Only Overnight/MNQ beats its baseline meaningfully,
  and it may be barred by the 4:45 PM flatten rule — confirm with Lucid first.

Sim101 is the correct destination today.
