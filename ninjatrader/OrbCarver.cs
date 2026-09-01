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
//  OrbCarver  --  opening-range breakout, sized under Robert Carver's
//                 *Leveraged Trading* framework.
//
//  Direct port of the winning cell from orb_carver_backtest.py:
//
//      MNQ | OR15 | or_stop_2r | both directions | tau = 12%
//      SR_net +1.04, cost_SR 0.156, ann vol 6.8%, maxDD -8.2%,
//      6.6 years (2020-03 -> 2026-08), permutation p = 0.03 against the
//      best-of-18 search null.
//
//  WHAT YOU MUST KNOW BEFORE RUNNING THIS WITH MONEY
//  -------------------------------------------------
//  1. IT BREACHES CARVER'S SPEED LIMIT. Measured cost drag is 0.156 SR/yr
//     against a limit of 0.30 / 3 = 0.100. The rule only pays if the gross
//     edge (+1.19 SR) is real -- and the gross edge is the part you cannot
//     verify. This is logged at startup, not hidden.
//  2. MINIMUM CAPITAL IS NOT $100,000. Carver's 4-contract floor on MNQ at
//     2026 prices is ~$338,000. At $100k, ~84% of 2026 trades round to ONE
//     lot, which is a fixed-size system wearing a vol-target's clothes.
//     The floor is logged every session. Fix it with capital or a smaller
//     contract -- NEVER by raising the risk target.
//  3. RECENT PERFORMANCE IS NEGATIVE AND THAT MEANS NOTHING. 2026 YTD ran
//     SR -0.18 over 156 sessions: the 7th percentile of history, inside the
//     normal range. SE(SR) over one year is ~1.0. Do not react to it.
//  4. Expect a 24% drawdown as ORDINARY (2 x tau) and plan for 36% (3 x tau).
//     Realised maxDD has been -8.2% only because the rule is flat ~18h of
//     every 24 and therefore realises just ~0.57 x tau of risk.
//
//  MECHANICS THAT MAKE THIS MATCH THE BACKTEST
//  -------------------------------------------
//  * NinjaTrader stamps a bar at its CLOSE; the Python backtest labels bars
//    at their START. Every time input below is therefore an NT bar-CLOSE
//    time. The 15-minute opening range 09:30-09:45 is the bars stamped
//    09:35, 09:40 and 09:45.
//  * Signal on a bar CLOSE, fill at the NEXT bar's OPEN. Calculate.OnBarClose
//    plus a market order gives exactly that. A signal computed on a close
//    cannot be traded at that close; pretending otherwise is the most common
//    way an intraday backtest lies.
//  * The stop is a STOP MARKET at the opposite edge of the range. On a gap
//    through the level you are filled at the open, not at the level. The
//    backtest models that; a stop LIMIT would not. Assuming the exact level
//    always fills once manufactured a Sharpe of 3.80 in this workspace which
//    collapsed to zero when fills were made gap-aware.
//  * The target is a resting LIMIT at 2R, where R = |entry - stop| measured
//    from the FILL, not from the range width, so it runs ~1.14x the range.
//    Measured 2R hit rate 15.5%, carrying 52% of gross profit.
//  * Volatility is the Carver default: 25-session stdev of close-to-close
//    returns x 16, from closes through the PRIOR session only. A day is never
//    sized with knowledge of its own outcome.
//  * Exit at the RTH close is a CORE exit, not a fallback: 42% of trades end
//    that way.
//
//  SETUP
//    Instrument   : MNQ (also valid on MES / MGC -- their numbers are much
//                   weaker; see orb_carver_summary.csv)
//    Bars         : 5 Minute
//    Session      : CME US Index Futures ETH (18:00-17:00 ET)
//    Time zone    : set NinjaTrader to (UTC-05:00) Eastern, or shift the time
//                   inputs below by hand
//    Days to load : >= 120 (needs 26 sessions of closes before it can size)
//    Fill resol.  : High / 1 Minute recommended. On Standard resolution
//                   NinjaTrader fills the stop before the target when both
//                   could hit inside one bar, which matches the backtest's
//                   deliberately conservative tie-break.
// =============================================================================

namespace NinjaTrader.NinjaScript.Strategies
{
	public enum OrbExitStyle
	{
		CloseOnly,		// "close"      -- flat at the RTH close, no stop
		OrStop,			// "or_stop"    -- stop at the far edge, flat at close
		OrStopTarget	// "or_stop_2r" -- stop + 2R target  <-- the tested cell
	}

	public enum OrbDirectionMode
	{
		Both,			// "both"  -- the winning MNQ cell, SR_net +1.04
		TrendFilter		// "trend" -- only with prior daily MAC(16,64), SR_net +0.71
	}

	public class OrbCarver : Strategy
	{
		// ---- Carver constants (published defaults, not fitted parameters) ----
		private const double Annualise           = 16.0;	// sqrt(256)
		private const int    VolWindow           = 25;		// business days
		private const double SpeedLimitPreCostSr = 0.30;	// single-instrument prior
		private const int    MacFast             = 16;
		private const int    MacSlow             = 64;

		// ---- rolling session closes, appended once per session ---------------
		private readonly List<double> sessionCloses = new List<double>();

		// ---- per-session state -----------------------------------------------
		private bool	wasInRth;
		private bool	orComplete;
		private bool	tradeTaken;
		private double	orHigh, orLow;
		private int		orEndTime;			// NT bar-close time, HHmmss
		private double	annVol;
		private double	macSign;
		private int		sizedQty;
		private double	pendingStop;
		private int		orEndBar;
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
			Description = "0.12 = Starter System. Trade skew here is +0.84 (positive), so NO skew haircut applies.")]
		public double Tau { get; set; }

		[NinjaScriptProperty]
		[Range(0.5, 2.5)]
		[Display(Name = "IDM (diversification multiplier)", Order = 3, GroupName = "1. Risk (Carver)",
			Description = "1.0 for a single instrument. Raising it on one market is a red flag, not a feature. The measured multi-instrument book IDM in this workspace is ~1.6.")]
		public double Idm { get; set; }

		[NinjaScriptProperty]
		[Range(0.01, 1.0)]
		[Display(Name = "Instrument weight", Order = 4, GroupName = "1. Risk (Carver)",
			Description = "This instrument's share of the book. 1.0 when it is the only thing you trade.")]
		public double InstrumentWeight { get; set; }

		[NinjaScriptProperty]
		[Range(1, 1000)]
		[Display(Name = "Max contracts (hard cap)", Order = 5, GroupName = "1. Risk (Carver)",
			Description = "Backstop against a collapsed volatility estimate producing an absurd size.")]
		public int MaxContracts { get; set; }

		[NinjaScriptProperty]
		[Range(5, 240)]
		[Display(Name = "Opening range (minutes)", Order = 1, GroupName = "2. Rule",
			Description = "15 is the tested cell on MNQ; 30 wins on MGC. Not a knob to turn while live.")]
		public int OpeningRangeMinutes { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Exit style", Order = 2, GroupName = "2. Rule")]
		public OrbExitStyle ExitStyle { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Direction", Order = 3, GroupName = "2. Rule")]
		public OrbDirectionMode DirectionMode { get; set; }

		[NinjaScriptProperty]
		[Range(0.5, 10.0)]
		[Display(Name = "Target (R multiple)", Order = 4, GroupName = "2. Rule",
			Description = "2.0 tested. Tighter targets cut return faster than drawdown: 1R costs 30% of the return to save 25% of the drawdown.")]
		public double TargetR { get; set; }

		[NinjaScriptProperty]
		[Range(0, 235959)]
		[Display(Name = "RTH open (bar-close, HHmmss)", Order = 1, GroupName = "3. Session clock",
			Description = "093000. The first RTH bar is the one stamped 09:35.")]
		public int SessionStartTime { get; set; }

		[NinjaScriptProperty]
		[Range(0, 235959)]
		[Display(Name = "Last signal bar (bar-close, HHmmss)", Order = 2, GroupName = "3. Session clock",
			Description = "143500. No new entry is armed on a bar closing after this.")]
		public int EntryCutoffTime { get; set; }

		[NinjaScriptProperty]
		[Range(0, 235959)]
		[Display(Name = "RTH close (bar-close, HHmmss)", Order = 3, GroupName = "3. Session clock",
			Description = "160000. Flatten is submitted on this bar's close and fills at the next bar's open -- the same instant the backtest marks its exit.")]
		public int SessionEndTime { get; set; }

		[NinjaScriptProperty]
		[Range(0, double.MaxValue)]
		[Display(Name = "Commission, round turn ($)", Order = 1, GroupName = "4. Costs (diagnostics)",
			Description = "1.24 modelled. Used only to report cost in Sharpe units; it does not affect orders.")]
		public double CommissionRoundTurn { get; set; }

		[NinjaScriptProperty]
		[Range(0, 100)]
		[Display(Name = "Slippage, round turn (ticks)", Order = 2, GroupName = "4. Costs (diagnostics)",
			Description = "2.0 modelled. Breakouts cross the spread; do not model this at 0.")]
		public double SlippageTicksRoundTurn { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Log Carver diagnostics daily", Order = 3, GroupName = "4. Costs (diagnostics)")]
		public bool VerboseLog { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Draw the opening range", Order = 1, GroupName = "5. Display")]
		public bool DrawRange { get; set; }
		#endregion

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description					 = "Opening-range breakout, volatility-targeted per Carver's Leveraged Trading. Ported from orb_carver_backtest.py (MNQ OR15 / stop+2R / both, SR_net +1.04).";
				Name						 = "OrbCarver";
				Calculate					 = Calculate.OnBarClose;
				EntriesPerDirection			 = 1;
				EntryHandling				 = EntryHandling.AllEntries;
				IsExitOnSessionCloseStrategy = true;	// failsafe only; we exit at 16:00
				ExitOnSessionCloseSeconds	 = 60;
				IsFillLimitOnTouch			 = false;
				MaximumBarsLookBack			 = MaximumBarsLookBack.TwoHundredFiftySix;
				OrderFillResolution			 = OrderFillResolution.Standard;
				Slippage					 = 0;
				StartBehavior				 = StartBehavior.WaitUntilFlat;
				TimeInForce					 = TimeInForce.Day;
				TraceOrders					 = false;
				RealtimeErrorHandling		 = RealtimeErrorHandling.StopCancelClose;
				StopTargetHandling			 = StopTargetHandling.PerEntryExecution;
				BarsRequiredToTrade			 = 20;
				IsInstantiatedOnEachOptimizationIteration = false;

				Capital					= 100000;
				Tau						= 0.12;
				Idm						= 1.0;
				InstrumentWeight		= 1.0;
				MaxContracts			= 50;
				OpeningRangeMinutes		= 15;
				ExitStyle				= OrbExitStyle.OrStopTarget;
				DirectionMode			= OrbDirectionMode.Both;
				TargetR					= 2.0;
				SessionStartTime		= 93000;
				EntryCutoffTime			= 143500;
				SessionEndTime			= 160000;
				CommissionRoundTurn		= 1.24;
				SlippageTicksRoundTurn	= 2.0;
				VerboseLog				= false;
				DrawRange				= true;
			}
			else if (State == State.DataLoaded)
			{
				if (BarsPeriod.BarsPeriodType != BarsPeriodType.Minute)
					Log("OrbCarver requires MINUTE bars (5 Minute is the tested resolution). "
						+ "The session clock cannot be reconstructed on any other bar type.",
						LogLevel.Error);

				if (Idm > 1.0 && InstrumentWeight >= 1.0)
					Log("OrbCarver: IDM > 1.0 with a single instrument at full weight. A "
						+ "diversification multiplier on ONE market is fictional diversification "
						+ "-- you are simply trading above your stated risk target.",
						LogLevel.Warning);
			}
		}

		// ---------------------------------------------------------------------
		//  Carver volatility: 25-session stdev of close-to-close returns x 16,
		//  computed from closes through the PRIOR session only.
		// ---------------------------------------------------------------------
		private bool TryComputeVol(out double vol)
		{
			vol = 0;
			int n = sessionCloses.Count;
			if (n < VolWindow + 1)
				return false;

			double[] r = new double[VolWindow];
			for (int i = 0; i < VolWindow; i++)
			{
				double c1 = sessionCloses[n - 1 - i];
				double c0 = sessionCloses[n - 2 - i];
				if (c0 <= 0)
					return false;
				r[i] = c1 / c0 - 1.0;
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

		// sign(SMA16 - SMA64) over session closes through the prior session
		private double TryComputeMac()
		{
			int n = sessionCloses.Count;
			if (n < MacSlow)
				return 0;

			double fast = 0, slow = 0;
			for (int i = 0; i < MacSlow; i++)
			{
				double c = sessionCloses[n - 1 - i];
				slow += c;
				if (i < MacFast)
					fast += c;
			}
			return Math.Sign(fast / MacFast - slow / MacSlow);
		}

		// ---------------------------------------------------------------------
		//  Position size, Carver's full portfolio form:
		//    contracts = (Capital x IDM x weight x tau) / (sigma_ann x price x multiplier)
		//  Computed on the signal bar's close and held constant for the life of
		//  the trade.
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
			double costSrAnn = costSrTr * 504.0;			// ~252 round turns/yr
			double limit     = SpeedLimitPreCostSr / 3.0;
			double leverage  = Tau / vol;

			Print(string.Format(
				"{0:yyyy-MM-dd}  [ORB Carver]  px {1:N2}   sigma_ann {2:P1}   raw {3:N2} -> {4} lots "
				+ "(rounding error {5:P1})   leverage {6:N2}x",
				Time[0], price, vol, raw, qty, roundErr, leverage));

			Print(string.Format(
				"              min capital: 1 lot ${0:N0}, Carver 4-lot floor ${1:N0}{2}",
				minCap1, minCap4,
				Capital < minCap4
					? "   <-- CAPITAL BELOW THE FLOOR. Rounding error above 12.5%. Fix with "
					  + "capital or a smaller contract, never by raising tau."
					: ""));

			Print(string.Format(
				"              cost/side ${0:N2}  ->  {1:F4} SR/trade, {2:F3} SR/yr at 504 sides. "
				+ "Speed limit {3:F3}  ->  {4}",
				sideCost, costSrTr, costSrAnn, limit,
				costSrAnn > limit
					? "BREACH. Backtested drag was 0.156 against a 0.100 limit. This rule only "
					  + "pays if the +1.19 gross SR is real, and that is the part you cannot verify."
					: "pass"));

			Print(string.Format(
				"              drawdown plan at tau {0:P0}: {1:P0} is ORDINARY (2x tau), {2:P0} is "
				+ "planned for (3x tau). Backtested maxDD was -8.2% only because the rule is flat "
				+ "~18h of every 24.",
				Tau, 2 * Tau, 3 * Tau));
		}

		protected override void OnBarUpdate()
		{
			if (BarsInProgress != 0 || CurrentBar < 1)
				return;

			// -- rolling session closes. Appended on the session's first bar, so
			//    the list always ends at the PRIOR session's close.
			if (Bars.IsFirstBarOfSession)
			{
				sessionCloses.Add(Close[1]);
				if (sessionCloses.Count > 400)
					sessionCloses.RemoveAt(0);
			}

			int barEnd = ToTime(Time[0]);
			bool inRth = barEnd > SessionStartTime && barEnd <= SessionEndTime;

			// -- new RTH day: reset, size, open the range ----------------------
			if (inRth && !wasInRth)
			{
				orHigh		= High[0];
				orLow		= Low[0];
				orComplete	= false;
				tradeTaken	= false;
				sizedQty	= 0;
				orEndBar	= CurrentBar;

				DateTime orEnd = Time[0].Date
									.AddHours(SessionStartTime / 10000)
									.AddMinutes((SessionStartTime / 100) % 100)
									.AddMinutes(OpeningRangeMinutes);
				orEndTime = ToTime(orEnd);

				macSign = TryComputeMac();
				if (!TryComputeVol(out annVol))
					annVol = 0;

				if (annVol > 0 && (VerboseLog || !diagnosticsPrinted))
				{
					LogCarverDiagnostics(Close[0], annVol, SizePosition(Close[0], annVol));
					diagnosticsPrinted = true;
				}
			}
			else if (inRth && !orComplete)
			{
				orHigh = Math.Max(orHigh, High[0]);
				orLow  = Math.Min(orLow,  Low[0]);
			}

			wasInRth = inRth;

			if (inRth && !orComplete && barEnd >= orEndTime)
			{
				orComplete = true;
				orEndBar   = CurrentBar;
			}

			if (DrawRange && inRth && orComplete && orHigh > orLow)
			{
				int back = CurrentBar - orEndBar;
				string tag = "OR" + Time[0].ToString("yyyyMMdd");
				Draw.Line(this, tag + "H", false, back, orHigh, 0, orHigh,
					Brushes.SteelBlue, DashStyleHelper.Solid, 1);
				Draw.Line(this, tag + "L", false, back, orLow, 0, orLow,
					Brushes.SteelBlue, DashStyleHelper.Solid, 1);
			}

			// -- flatten at the RTH close --------------------------------------
			//    Submitted on the bar stamped 16:00 and filled at the next bar's
			//    open -- the same 16:00:00 print the backtest exits on. 42% of
			//    trades end here; it is a core exit, not a fallback.
			if (Position.MarketPosition != MarketPosition.Flat && barEnd >= SessionEndTime)
			{
				if (Position.MarketPosition == MarketPosition.Long)
					ExitLong("OrbEod", "OrbLong");
				else
					ExitShort("OrbEod", "OrbShort");
				return;
			}

			// -- breakout -------------------------------------------------------
			if (!inRth || !orComplete || tradeTaken || barEnd > EntryCutoffTime)
				return;
			if (Position.MarketPosition != MarketPosition.Flat)
				return;
			if (annVol <= 0 || orHigh <= orLow)
				return;

			bool allowLong  = DirectionMode == OrbDirectionMode.Both || macSign > 0;
			bool allowShort = DirectionMode == OrbDirectionMode.Both || macSign < 0;
			if (DirectionMode == OrbDirectionMode.TrendFilter && macSign == 0)
				return;

			// Long is tested first, exactly as in the backtest, so a bar closing
			// outside both edges resolves identically.
			int side = 0;
			if (Close[0] > orHigh && allowLong)
				side = 1;
			else if (Close[0] < orLow && allowShort)
				side = -1;

			if (side == 0)
				return;

			sizedQty = SizePosition(Close[0], annVol);
			if (sizedQty < 1)
			{
				// The backtest drops these sessions rather than trading one lot
				// of something the account cannot afford. So does this.
				Print(string.Format("{0:yyyy-MM-dd HH:mm}  [ORB Carver] breakout skipped: "
					+ "vol-implied size rounds to zero at ${1:N0} capital.", Time[0], Capital));
				tradeTaken = true;
				return;
			}

			tradeTaken  = true;
			pendingStop = Instrument.MasterInstrument.RoundToTickSize(side > 0 ? orLow : orHigh);

			// The stop price is known before the fill, so arm it before the entry:
			// the bracket is live from the moment the position exists. The target
			// depends on the fill and is set in OnExecutionUpdate.
			if (ExitStyle != OrbExitStyle.CloseOnly)
			{
				if (side > 0)
					SetStopLoss("OrbLong",  CalculationMode.Price, pendingStop, false);
				else
					SetStopLoss("OrbShort", CalculationMode.Price, pendingStop, false);
			}

			if (side > 0)
				EnterLong(sizedQty, "OrbLong");
			else
				EnterShort(sizedQty, "OrbShort");
		}

		// ---------------------------------------------------------------------
		//  R is measured from the ACTUAL FILL, not from the range width. The
		//  fill lands beyond the level, so R runs ~1.14x the range on MNQ
		//  (median 90 pts against a 76 pt range).
		// ---------------------------------------------------------------------
		protected override void OnExecutionUpdate(Execution execution, string executionId,
			double price, int quantity, MarketPosition marketPosition, string orderId, DateTime time)
		{
			if (ExitStyle != OrbExitStyle.OrStopTarget)
				return;
			if (execution.Order == null || execution.Order.OrderState != OrderState.Filled)
				return;

			string n = execution.Order.Name;
			if (n != "OrbLong" && n != "OrbShort")
				return;

			double fill = execution.Order.AverageFillPrice;
			double r    = Math.Abs(fill - pendingStop);
			if (r <= 0)
				return;

			double target = n == "OrbLong" ? fill + TargetR * r : fill - TargetR * r;
			SetProfitTarget(n, CalculationMode.Price,
				Instrument.MasterInstrument.RoundToTickSize(target));
		}
	}
}
