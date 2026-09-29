using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;

namespace NinjaTrader.NinjaScript.Strategies
{
    // Source: strategy_engine/strategies/session_drift.py, NQ, 1m,
    // globex-overnight, Long, no bracket/range filter. This wrapper uses the
    // tested conservative_execution entry in reports/expanded-search-2026-09-16/
    // expanded.py: second minute's open (18:01 ET), not baseline first open18:00.
    // Exit is a market order after the completed 05:59-06:00 minute, so its fill
    // may differ from Python's final-close mark. Full ETH bars are required to
    // provide the 06:00 successor quote. Missing opening minute means no entry;
    // a late callback for an existing bar still fills at the next observed quote.
    // Default one MNQ ($2/point); no stop/target because none was in this test.
    public class WorkbenchMnqOvernightSession : Strategy
    {
        private WorkbenchMnqOvernightRules rules;
        private TimeZoneInfo platformZone;
        private bool entryPending;
        private bool exitPending;
        private bool validSetup;

        [NinjaScriptProperty]
        [Range(1, 100)]
        [Display(Name = "MNQ contracts", Order = 1, GroupName = "Position")]
        public int Contracts { get; set; }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "WorkbenchMnqOvernightSession";
                Description = "NQ tested session drift adapted to MNQ: 1m, conservative18:01/06:00 Eastern, one micro by default; no stop.";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = false;
                StartBehavior = StartBehavior.WaitUntilFlat;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                TimeInForce = TimeInForce.Gtc;
                BarsRequiredToTrade = 0;
                IsInstantiatedOnEachOptimizationIteration = true;
                Contracts = 1;
            }
            else if (State == State.DataLoaded)
            {
                rules = new WorkbenchMnqOvernightRules();
                platformZone = NinjaTrader.Core.Globals.GeneralOptions.TimeZoneInfo;
                entryPending = exitPending = false;
                validSetup = Instrument.MasterInstrument.Name == "MNQ"
                    && Math.Abs(Instrument.MasterInstrument.PointValue - 2.0) < 0.000001
                    && Math.Abs(TickSize - 0.25) < 0.000001
                    && BarsPeriod.BarsPeriodType == BarsPeriodType.Minute && BarsPeriod.Value == 1
                    && Bars.TradingHours.Name == "CME US Index Futures ETH";
                if (!validSetup)
                    throw new InvalidOperationException(Name + " requires MNQ ($2/point, 0.25 tick), 1 Minute, CME US Index Futures ETH.");
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0 || !validSetup)
                return;
            DateTime eastern = WorkbenchMnqOvernightRules.ToEastern(Time[0], platformZone);
            int signal = rules.SessionSignal(eastern, Position.MarketPosition == MarketPosition.Long);
            if (signal < 0 && !exitPending)
            {
                exitPending = true;
                ExitLong("Session0600", "SessionLong");
            }
            else if (signal > 0 && !entryPending && !exitPending && Position.MarketPosition == MarketPosition.Flat)
            {
                SubmitEntry();
            }
        }

        private void SubmitEntry()
        {
            entryPending = true;
            EnterLong(Contracts, "SessionLong");
        }

        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice,
            int quantity, int filled, double averageFillPrice, OrderState orderState,
            DateTime time, ErrorCode error, string comment)
        {
            bool terminal = orderState == OrderState.Filled || orderState == OrderState.Cancelled
                || orderState == OrderState.Rejected;
            if (terminal && order.Name == "SessionLong") entryPending = false;
            if (terminal && order.Name == "Session0600") exitPending = false;
        }
    }
}
