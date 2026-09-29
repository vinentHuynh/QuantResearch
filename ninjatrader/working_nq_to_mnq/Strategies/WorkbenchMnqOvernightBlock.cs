using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;

namespace NinjaTrader.NinjaScript.Strategies
{
    // NQ research source: strategies/_pine_models.py:OvernightBlock, 15m,
    // full-trading-day; entry 17:00 ET, exit 06:00 ET, long one contract.
    // MNQ conversion preserves price/time rules, defaults to ONE micro ($2/point).
    // There is no tested stop or target. No new stop is silently added here.
    // A 17:00 completed-bar signal fills the next tradable open (normally 18:00).
    // Real-time OnBarClose arrives with the first tick of the next bar; a market
    // order then receives an actual fill, never the already completed close.
    // Missing bars retain the source's observed-window transitions: a delayed
    // next available quote can therefore produce a delayed entry or exit.
    public class WorkbenchMnqOvernightBlock : Strategy
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
                Name = "WorkbenchMnqOvernightBlock";
                Description = "NQ tested overnight block adapted to MNQ: 15m, 17:00/06:00 Eastern, one micro by default; no stop.";
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
                    && BarsPeriod.BarsPeriodType == BarsPeriodType.Minute && BarsPeriod.Value == 15
                    && Bars.TradingHours.Name == "CME US Index Futures ETH";
                if (!validSetup)
                    throw new InvalidOperationException(Name + " requires MNQ ($2/point, 0.25 tick), 15 Minute, CME US Index Futures ETH.");
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0 || !validSetup)
                return;
            DateTime eastern = WorkbenchMnqOvernightRules.ToEastern(Time[0], platformZone);
            int signal = rules.BlockSignal(eastern, Position.MarketPosition == MarketPosition.Long);
            if (signal < 0 && !exitPending)
            {
                exitPending = true;
                ExitLong("Block0600", "BlockLong");
            }
            else if (signal > 0 && !entryPending && !exitPending && Position.MarketPosition == MarketPosition.Flat)
            {
                SubmitEntry();
            }
        }

        private void SubmitEntry()
        {
            entryPending = true;
            EnterLong(Contracts, "BlockLong");
        }

        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice,
            int quantity, int filled, double averageFillPrice, OrderState orderState,
            DateTime time, ErrorCode error, string comment)
        {
            bool terminal = orderState == OrderState.Filled || orderState == OrderState.Cancelled
                || orderState == OrderState.Rejected;
            if (terminal && order.Name == "BlockLong") entryPending = false;
            if (terminal && order.Name == "Block0600") exitPending = false;
        }
    }
}
