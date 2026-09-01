#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Windows.Media;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.DrawingTools;
#endregion

// =============================================================================
//  OvernightDriftCarver  --  long the Globex overnight block, sized under
//                            Robert Carver's *Leveraged Trading* framework.
//
//  Direct port of the winning row from overnight_drift_carver_backtest.py:
//
//      MNQ | 18:00 -> 06:00 ET | long only | ~504 sides/yr
//      SR_net +0.88 (gross +1.03, cost 0.147), ann vol 5.7%, maxDD -6.0%,
//      win rate 54.7%, skew -0.35, 6.6 years, t = 2.26.
//
//  The window was NOT searched. It is inherited from earlier work in this
//  repository, which established that the equity premium is earned overnight
//  and localises to this block. The alternative pre-specified window,
//  23:00 -> 04:00, scored SR_net +0.81 and is available via the inputs.
//
//  WHAT YOU MUST KNOW BEFORE RUNNING THIS WITH MONEY
//  -------------------------------------------------
//  1. TAU IS HALVED, AND THAT IS DELIBERATE. Nightly return skew is -0.35.
//     Carver halves the risk target for negative-skew payoffs, and holding a
//     gap over a closed market is the textbook case. The default here is
//     tau = 6%, not 12%. Raising it back to 12% is not "using the framework",
//     it is discarding the part of the framework that protects you.
//  2. IT BREACHES THE SPEED LIMIT ON MEASURED DRAG. 0.147 SR/yr against a
//     0.30 / 3 = 0.100 limit. The a-priori screen said "pass" at 0.042; the
//     measured number is 3.5x that, because the block pays a full ticket for
//     half a day's risk. Measured drag is the verdict, not the formula.
//  3. THE HONEST COMPARISON IS 24h BUY-AND-HOLD, NOT ZERO. The same MNQ held
//     24h with buffered vol-targeting scored SR_net +0.71 on ~8 trades a year
//     instead of 504. The block wins by +0.17 SR. That is the entire case for
//     going flat every morning, and it is thin. On MES the block LOSES
//     (+0.39 vs +0.73); on MCL it is negative outright. Do not run this on
//     those without re-reading the backtest.
//  4. Expect a 12% drawdown as ORDINARY (2 x tau) and plan for 18% (3 x tau).
//     Realised maxDD has been -6.0% only because the rule is flat ~12h of
//     every 24 and realises just ~0.48 x tau of risk.
//  5. NO STOP LOSS, BY DESIGN. The backtest has none. The risk being carried
//     is an overnight gap, which is precisely the risk a stop cannot stop --
//     you get filled through it. An optional disaster stop is exposed below
//     and defaults to OFF; switching it on means you are no longer trading
//     the rule that was tested.
//
//  MECHANICS THAT MAKE THIS MATCH THE BACKTEST
//  -------------------------------------------
//  * P&L runs the block's FIRST OPEN to its LAST CLOSE. The Sunday reopen and
//    every contract roll seam fall BETWEEN blocks and are never held. That is
//    the single most important detail in an overnight backtest: on a
//    non-adjusted continuous series a close-to-close P&L books the contango
//    roll step as profit the trader never earned. Use a back-adjusted
//    continuous contract or trade the front month outright.
//  * NinjaTrader stamps a bar at its CLOSE; the Python backtest labels bars at
//    their START. The block inputs below are bar-START times, and the code
//    converts. The 18:00 entry is the OPEN of the bar NinjaTrader stamps
//    18:05; the 06:00 exit is the CLOSE of the bar it stamps 06:00.
//  * ENTRY AND EXIT TIMING DIFFER BETWEEN BACKTEST AND LIVE, and both paths
//    are implemented so both hit the same price:
//      - Historical: CME halts 17:00-18:00, so no bar ends at 18:00. The entry
//        is submitted on the bar closing at 17:00 and fills at the next bar's
//        open, which IS the 18:00 print. The exit is submitted on the bar
//        closing at 06:00 and fills at the next bar's open, the 06:00 print.
//      - Realtime: the entry goes in on the session's first tick (18:00:00)
//        and the exit on the first tick at or after 06:00:00.
//  * Volatility is the Carver default: 25-session stdev of close-to-close
//    returns x 16, from closes through the prior 17:00 settlement. The 18:00
//    entry is sized with the settlement that just happened and nothing later.
//
//  SETUP
//    Instrument   : MNQ (MGC also positive at +0.61; MES weak, MCL negative)
//    Bars         : 5 Minute
//    Session      : CME US Index Futures ETH (18:00-17:00 ET)
//    Time zone    : set NinjaTrader to (UTC-05:00) Eastern, or shift the time
//                   inputs below by hand
//    Days to load : >= 120 (needs 26 sessions of closes before it can size)
//    Fill resol.  : Standard is adequate -- there are no intrabar orders.
// =============================================================================

namespace NinjaTrader.NinjaScript.Strategies
{
	public class OvernightDriftCarver : Strategy
	{
		// ---- Carver constants (published defaults, not fitted parameters) ----
		private const double Annualise           = 16.0;	// sqrt(256)
		private const int    VolWindow           = 25;		// business days
		private const double SpeedLimitPreCostSr = 0.30;	// single-instrument prior
		private const double SessionsPerYear     = 252.0;

		// ---- rolling session closes, appended once per session ---------------
		private readonly List<double> sessionCloses = new List<double>();

		// ---- state ------------------------------------------------------------
		private bool	wasInBlock;
		private bool	entrySubmitted;
		private double	annVol;
		private int		sizedQty;
		private int		barMinutes = 5;
		private bool	diagnosticsPrinted;

		#region Properties
		[NinjaScriptProperty]
		[Range(1000, double.MaxValue)]
		[Display(Name = "Trading capital ($)", Order = 1, GroupName = "1. Risk (Carver)",
			Description = "Money you can afford to lose. Fixed -- no compounding, matching the backtest.")]
		public double Capital { get; set; }

		[NinjaScriptProperty]
		[Range(0.01, 0.40)]
		[Display(Name = "Risk target (tau, annual)", Order = 2, GroupName = "1. Risk (Carver)",
			Description = "0.06 = the 12% Starter System target HALVED, because nightly skew is -0.35. Carver halves tau for negative-skew payoffs. Do not undo this to chase return.")]
		public double Tau { get; set; }

		[NinjaScriptProperty]
		[Range(0.5, 2.5)]
		[Display(Name = "IDM (diversification multiplier)", Order = 3, GroupName = "1. Risk (Carver)",
			Description = "1.0 for a single instrument. The measured IDM for the 4-instrument book in this workspace is ~1.6, and MES/MNQ correlate ~+0.9 -- two equity index futures are ONE bet wearing two tickers.")]
		public double Idm { get; set; }

		[NinjaScriptProperty]
		[Range(0.01, 1.0)]
		[Display(Name = "Instrument weight", Order = 4, GroupName = "1. Risk (Carver)",
			Description = "This instrument's share of the book. 1.0 when it is the only thing you trade; 0.25 in the handcrafted four.")]
		public double InstrumentWeight { get; set; }

		[NinjaScriptProperty]
		[Range(1, 1000)]
		[Display(Name = "Max contracts (hard cap)", Order = 5, GroupName = "1. Risk (Carver)",
			Description = "Backstop against a collapsed volatility estimate producing an absurd size.")]
		public int MaxContracts { get; set; }

		[NinjaScriptProperty]
		[Range(0, 235959)]
		[Display(Name = "Block start (bar-START, HHmmss)", Order = 1, GroupName = "2. Rule",
			Description = "180000 tested (SR_net +0.88). The other pre-specified window is 230000 -> 040000 (SR_net +0.81). Nothing else was searched; do not search it now.")]
		public int BlockStartTime { get; set; }

		[NinjaScriptProperty]
		[Range(0, 235959)]
		[Display(Name = "Block end (bar-START, HHmmss)", Order = 2, GroupName = "2. Rule",
			Description = "060000 tested. Exclusive: the last bar held is the one starting 05:55, and its close is the 06:00 print.")]
		public int BlockEndTime { get; set; }

		[NinjaScriptProperty]
		[Range(0, 235959)]
		[Display(Name = "Backtest submit time (bar-close, HHmmss)", Order = 3, GroupName = "2. Rule",
			Description = "170000, the CME daily halt. In HISTORICAL mode only, the entry is submitted on the bar closing at this time so the fill lands on the 18:00 open. No bar ends at 18:00, so there is no other way to hit that price. Ignored in realtime.")]
		public int BacktestEntrySubmitTime { get; set; }

		[NinjaScriptProperty]
		[Range(0, 20)]
		[Display(Name = "Disaster stop (x one-session vol, 0 = off)", Order = 4, GroupName = "2. Rule",
			Description = "OFF by default because the backtest has no stop. The risk here is a gap over a closed market, which fills THROUGH a stop rather than at it. Turning this on means you are not trading the rule that was tested.")]
		public double DisasterStopSessionVols { get; set; }

		[NinjaScriptProperty]
		[Range(0, double.MaxValue)]
		[Display(Name = "Commission, round turn ($)", Order = 1, GroupName = "3. Costs (diagnostics)",
			Description = "1.24 modelled. Used only to report cost in Sharpe units; it does not affect orders.")]
		public double CommissionRoundTurn { get; set; }

		[NinjaScriptProperty]
		[Range(0, 100)]
		[Display(Name = "Slippage, round turn (ticks)", Order = 2, GroupName = "3. Costs (diagnostics)",
			Description = "1.0 modelled -- the block enters and exits with market orders at liquid clock times, so it crosses less than a breakout does.")]
		public double SlippageTicksRoundTurn { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Log Carver diagnostics nightly", Order = 3, GroupName = "3. Costs (diagnostics)")]
		public bool VerboseLog { get; set; }
		#endregion

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description					 = "Long the Globex overnight block, volatility-targeted per Carver's Leveraged Trading with tau halved for negative skew. Ported from overnight_drift_carver_backtest.py (MNQ 18:00-06:00, SR_net +0.88).";
				Name						 = "OvernightDriftCarver";
				Calculate					 = Calculate.OnEachTick;
				EntriesPerDirection			 = 1;
				EntryHandling				 = EntryHandling.AllEntries;
				IsExitOnSessionCloseStrategy = true;	// failsafe for early closes
				ExitOnSessionCloseSeconds	 = 60;
				IsFillLimitOnTouch			 = false;
				MaximumBarsLookBack			 = MaximumBarsLookBack.TwoHundredFiftySix;
				OrderFillResolution			 = OrderFillResolution.Standard;
				Slippage					 = 0;
				StartBehavior				 = StartBehavior.WaitUntilFlat;
				TimeInForce					 = TimeInForce.Gtc;
				TraceOrders					 = false;
				RealtimeErrorHandling		 = RealtimeErrorHandling.StopCancelClose;
				StopTargetHandling			 = StopTargetHandling.PerEntryExecution;
				BarsRequiredToTrade			 = 20;
				IsInstantiatedOnEachOptimizationIteration = false;

				Capital					= 100000;
				Tau						= 0.06;		// 12% halved for skew -0.35
				Idm						= 1.0;
				InstrumentWeight		= 1.0;
				MaxContracts			= 50;
				BlockStartTime			= 180000;
				BlockEndTime			= 60000;
				BacktestEntrySubmitTime	= 170000;
				DisasterStopSessionVols	= 0.0;
				CommissionRoundTurn		= 1.24;
				SlippageTicksRoundTurn	= 1.0;
				VerboseLog				= false;
			}
			else if (State == State.DataLoaded)
			{
				if (BarsPeriod.BarsPeriodType != BarsPeriodType.Minute)
					Log("OvernightDriftCarver requires MINUTE bars (5 Minute is the tested "
						+ "resolution). The block clock cannot be reconstructed on any other "
						+ "bar type.", LogLevel.Error);
				else
					barMinutes = BarsPeriod.Value;

				if (Tau > 0.061)
					Log(string.Format("OvernightDriftCarver: tau is {0:P1}. Nightly skew is -0.35; "
						+ "Carver halves the risk target for negative-skew payoffs, which is why "
						+ "the default is 6%. You are running above the skew-adjusted target.",
						Tau), LogLevel.Warning);

				if (Idm > 1.0 && InstrumentWeight >= 1.0)
					Log("OvernightDriftCarver: IDM > 1.0 with a single instrument at full weight. "
						+ "A diversification multiplier on ONE market is fictional diversification "
						+ "-- you are simply trading above your stated risk target.",
						LogLevel.Warning);
			}
		}

		/// <summary>Wrap-aware clock window, half-open: start inclusive, end exclusive,
		/// crossing midnight when start &gt; end.</summary>
		private static bool InWindow(int t, int start, int end)
		{
			return start <= end ? (t >= start && t < end) : (t >= start || t < end);
		}

		/// <summary>
		/// The last <paramref name="count"/> session closes, oldest first.
		/// <paramref name="extraClose"/> is the settlement that has just printed but
		/// has not yet been appended to the list; pass double.NaN when there is none.
		/// Returns null when there is not enough history yet.
		/// </summary>
		private double[] TailCloses(int count, double extraClose)
		{
			var tail = new List<double>(count);
			if (!double.IsNaN(extraClose))
				tail.Add(extraClose);
			for (int i = sessionCloses.Count - 1; i >= 0 && tail.Count < count; i--)
				tail.Add(sessionCloses[i]);
			if (tail.Count < count)
				return null;
			tail.Reverse();
			return tail.ToArray();
		}

		// ---------------------------------------------------------------------
		//  Carver volatility: 25-session stdev of close-to-close returns x 16,
		//  from closes through the prior settlement and nothing later.
		// ---------------------------------------------------------------------
		private bool TryComputeVol(double extraClose, out double vol)
		{
			vol = 0;
			double[] c = TailCloses(VolWindow + 1, extraClose);
			if (c == null)
				return false;

			double[] r = new double[VolWindow];
			for (int i = 0; i < VolWindow; i++)
			{
				if (c[i] <= 0)
					return false;
				r[i] = c[i + 1] / c[i] - 1.0;
			}

			double mean = 0;
			for (int i = 0; i < VolWindow; i++)
				mean += r[i];
			mean /= VolWindow;

			double ss = 0;
			for (int i = 0; i < VolWindow; i++)
				ss += (r[i] - mean) * (r[i] - mean);

			vol = Math.Sqrt(ss / (VolWindow - 1)) * Annualise;	// ddof = 1, as pandas
			return vol > 0;
		}

		// ---------------------------------------------------------------------
		//  Position size, Carver's full portfolio form:
		//    contracts = (Capital x IDM x weight x tau) / (sigma_ann x price x multiplier)
		// ---------------------------------------------------------------------
		private int SizePosition(double price, double vol)
		{
			double mult = Instrument.MasterInstrument.PointValue;
			if (vol <= 0 || price <= 0 || mult <= 0)
				return 0;

			double raw = (Capital * Idm * InstrumentWeight * Tau) / (vol * price * mult);
			int qty = (int)Math.Round(raw, MidpointRounding.AwayFromZero);
			return Math.Max(0, Math.Min(qty, MaxContracts));
		}

		private void LogCarverDiagnostics(double price, double vol, int qty)
		{
			double mult      = Instrument.MasterInstrument.PointValue;
			double tickValue = TickSize * mult;
			double sideCost  = (CommissionRoundTurn + SlippageTicksRoundTurn * tickValue) / 2.0;
			double annVolCcy = price * mult * vol;

			double raw       = (Capital * Idm * InstrumentWeight * Tau) / (vol * price * mult);
			double roundErr  = raw > 0 ? Math.Abs(qty - raw) / raw : 0;
			double minCap1   = mult * price * vol / Tau;
			double minCap4   = 4.0 * minCap1;
			double costSrTr  = sideCost / annVolCcy;
			double costSrAnn = costSrTr * 2.0 * SessionsPerYear;	// 504 sides/yr
			double limit     = SpeedLimitPreCostSr / 3.0;
			double leverage  = Tau / vol;

			Print(string.Format(
				"{0:yyyy-MM-dd HH:mm}  [Overnight Carver]  px {1:N2}   sigma_ann {2:P1}   "
				+ "raw {3:N2} -> {4} lots (rounding error {5:P1})   leverage {6:N2}x   "
				+ "notional ${7:N0}",
				Time[0], price, vol, raw, qty, roundErr, leverage, qty * price * mult));

			Print(string.Format(
				"                    min capital: 1 lot ${0:N0}, Carver 4-lot floor ${1:N0}{2}",
				minCap1, minCap4,
				Capital < minCap4
					? "   <-- CAPITAL BELOW THE FLOOR. Rounding error above 12.5%. Fix with "
					  + "capital or a smaller contract, never by raising tau."
					: ""));

			Print(string.Format(
				"                    cost/side ${0:N2}  ->  {1:F6} SR/trade, {2:F3} SR/yr at 504 "
				+ "sides. Speed limit {3:F3}  ->  {4}",
				sideCost, costSrTr, costSrAnn, limit,
				costSrAnn > limit
					? "BREACH. Measured backtest drag was 0.147 against a 0.100 limit, and 3.5x "
					  + "the a-priori estimate: the block pays a full ticket for half a day's risk."
					: "pass"));

			Print(string.Format(
				"                    tau {0:P0} (12% halved for skew -0.35). Drawdown plan: {1:P0} "
				+ "is ORDINARY (2x tau), {2:P0} is planned for (3x tau). The benchmark to beat is "
				+ "NOT zero -- it is 24h buy-and-hold at SR +0.71 on ~8 trades a year.",
				Tau, 2 * Tau, 3 * Tau));
		}

		protected override void OnBarUpdate()
		{
			if (BarsInProgress != 0 || CurrentBar < 1)
				return;

			// -- rolling session closes, appended on the session's first bar ----
			if (IsFirstTickOfBar && Bars.IsFirstBarOfSession)
			{
				sessionCloses.Add(Close[1]);
				if (sessionCloses.Count > 400)
					sessionCloses.RemoveAt(0);
			}

			int  barEnd      = ToTime(Time[0]);
			int  barStart    = ToTime(Time[0].AddMinutes(-barMinutes));
			bool inBlock     = InWindow(barStart, BlockStartTime, BlockEndTime);
			bool nextInBlock = InWindow(barEnd,   BlockStartTime, BlockEndTime);
			bool live        = State == State.Realtime;

			// -- EXIT ------------------------------------------------------------
			//    Both paths land on the same 06:00:00 print: historically the order
			//    is submitted on the last in-block bar and fills at the next bar's
			//    open; live it is submitted on the first tick after the block ends.
			if (Position.MarketPosition == MarketPosition.Long)
			{
				bool exitNow = live
					? (IsFirstTickOfBar && !inBlock && wasInBlock)
					: (inBlock && !nextInBlock);

				if (exitNow)
					ExitLong("OnBlockExit", "OnBlockLong");
			}

			// -- ENTRY -----------------------------------------------------------
			if (IsFirstTickOfBar
				&& Position.MarketPosition == MarketPosition.Flat
				&& !entrySubmitted)
			{
				// Historically: the bar whose successor opens the block. Across the
				// CME halt no bar ends at 18:00, hence the explicit submit time.
				// Live: the block's own first tick.
				bool armNow = live
					? (inBlock && !wasInBlock && barStart == BlockStartTime)
					: (!inBlock && (nextInBlock || barEnd == BacktestEntrySubmitTime));

				if (armNow)
				{
					// The settlement that has just printed is Close[0] on the
					// historical path (it is not in the list yet) and is already in
					// the list on the live path, where it was appended at 18:00.
					double extra = live ? double.NaN : Close[0];

					if (!TryComputeVol(extra, out annVol))
						annVol = 0;

					if (annVol > 0)
					{
						sizedQty = SizePosition(Close[0], annVol);

						if (VerboseLog || !diagnosticsPrinted)
						{
							LogCarverDiagnostics(Close[0], annVol, sizedQty);
							diagnosticsPrinted = true;
						}

						if (sizedQty >= 1)
						{
							// Optional, OFF by default. Set before the entry so the
							// bracket is live from the moment the position exists.
							if (DisasterStopSessionVols > 0)
							{
								double gap  = DisasterStopSessionVols * Close[0] * annVol / Annualise;
								double stop = Instrument.MasterInstrument.RoundToTickSize(Close[0] - gap);
								SetStopLoss("OnBlockLong", CalculationMode.Price, stop, false);
							}

							EnterLong(sizedQty, "OnBlockLong");
							entrySubmitted = true;
						}
						else
						{
							// The backtest drops these sessions rather than trading a
							// lot the account cannot carry. So does this.
							Print(string.Format("{0:yyyy-MM-dd HH:mm}  [Overnight Carver] block "
								+ "skipped: vol-implied size rounds to zero at ${1:N0} capital.",
								Time[0], Capital));
							entrySubmitted = true;
						}
					}
				}
			}

			// -- block bookkeeping ------------------------------------------------
			if (IsFirstTickOfBar)
			{
				if (!inBlock && wasInBlock)
					entrySubmitted = false;		// block finished; re-arm for tonight
				wasInBlock = inBlock;
			}
		}
	}
}
