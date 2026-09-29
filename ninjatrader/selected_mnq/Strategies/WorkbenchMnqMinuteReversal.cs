using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;

namespace NinjaTrader.NinjaScript.Strategies
{
    // Port of the WORKING NQ 1m configuration, executed/signaled on MNQ.
    // Source: strategies/short_term_reversal_minute.py + short_term_reversal.py.
    // Fixed rules: decline >1.25%, close > SMA200, one open-to-open interval,
    // mandatory flat interval, 09:35 ET scheduling, latest new entry09:40 ET.
    // Holds overnight and sometimes weekends, WITHOUT a stop (as tested).
    // This is not a prop-firm intraday variant. Do not add a daily flatten and
    // describe its results as the tested configuration.
    public class WorkbenchMnqMinuteReversal : Strategy
    {
        private WorkbenchMnqReversalCore model;
        private TimeZoneInfo eastern;
        private bool pendingOrder;
        private DateTime exitIntentExpires;
        private const string EntrySignal = "WBReversalLong";

        [NinjaScriptProperty]
        [Range(1, 100)]
        [Display(Name = "MNQ contracts", Order = 1, GroupName = "Position")]
        public int Contracts { get; set; }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "WorkbenchMnqMinuteReversal";
                Description = "Tested NQ minute reversal transferred to MNQ. 1-minute ETH; SMA200 RTH days; 09:35 ET. Holds overnight, no stop.";
                Calculate = Calculate.OnBarClose;
                Contracts = 1;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                BarsRequiredToTrade = 0;
                IsExitOnSessionCloseStrategy = false;
                IsInstantiatedOnEachOptimizationIteration = true;
                StartBehavior = StartBehavior.WaitUntilFlat;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                TimeInForce = TimeInForce.Day;
                OrderFillResolution = OrderFillResolution.Standard;
                Slippage = 1;
            }
            else if (State == State.DataLoaded)
            {
                if (Instrument.MasterInstrument.Name != "MNQ"
                    || Math.Abs(Instrument.MasterInstrument.PointValue - 2.0) > 1e-9
                    || Math.Abs(TickSize - 0.25) > 1e-9)
                    throw new InvalidOperationException(Name + " requires MNQ ($2/point, 0.25 tick).");
                if (BarsPeriod.BarsPeriodType != BarsPeriodType.Minute || BarsPeriod.Value != 1)
                    throw new InvalidOperationException(Name + " requires 1-minute bars.");
                if (Bars.TradingHours.Name != "CME US Index Futures ETH")
                    throw new InvalidOperationException(Name + " requires CME US Index Futures ETH trading hours.");
                eastern = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
                model = new WorkbenchMnqReversalCore(200, 1.25);
                pendingOrder = false;
                exitIntentExpires = DateTime.MinValue;
                Print(Name + ": requires 201 completed RTH days before entry; load at least 600 calendar days. MNQ transfer is not MNQ performance validation.");
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0 || model == null)
                return;
            DateTime end = TimeZoneInfo.ConvertTime(DateTime.SpecifyKind(Time[0], DateTimeKind.Unspecified),
                NinjaTrader.Core.Globals.GeneralOptions.TimeZoneInfo, eastern);
            int? target = model.OnMinute(end.AddMinutes(-1), end, Close[0]);
            if (target.HasValue && target.Value == 0)
                exitIntentExpires = end.Date.AddHours(16);
            // Keep a scheduled flat target if an earlier order is still pending.
            // Retry only within that day's source exit-expiration window.
            ReconcileExit(end);
            if (!target.HasValue || pendingOrder)
                return;
            if (Position.MarketPosition == MarketPosition.Flat && target.Value == 1 && model.Ready)
            {
                // A market order cannot inherit the simulator's future quote
                // expiration. Suppress stale real-time bar callbacks before
                // submission; historical fill gap semantics require Replay QA.
                if (State == State.Realtime)
                {
                    DateTime clock = Connection.PlaybackConnection != null
                        ? Connection.PlaybackConnection.Now : NinjaTrader.Core.Globals.Now;
                    DateTime now = TimeZoneInfo.ConvertTime(DateTime.SpecifyKind(clock, DateTimeKind.Unspecified),
                        NinjaTrader.Core.Globals.GeneralOptions.TimeZoneInfo, eastern);
                    if (now.Date != end.Date || now > end.Date.AddMinutes(580))
                        return;
                }
                pendingOrder = true;
                EnterLong(Contracts, EntrySignal);
            }
        }

        private void ReconcileExit(DateTime easternTime)
        {
            if (!pendingOrder && easternTime <= exitIntentExpires
                && Position.MarketPosition == MarketPosition.Long)
            {
                pendingOrder = true;
                ExitLong("WBReversalExit", EntrySignal);
            }
        }

        protected override void OnExecutionUpdate(Execution execution, string executionId,
            double price, int quantity, MarketPosition marketPosition, string orderId, DateTime time)
        {
            if (eastern == null || execution.Order == null || execution.Order.Name != EntrySignal
                || marketPosition != MarketPosition.Long)
                return;
            DateTime executionTime = TimeZoneInfo.ConvertTime(DateTime.SpecifyKind(time, DateTimeKind.Unspecified),
                NinjaTrader.Core.Globals.GeneralOptions.TimeZoneInfo, eastern);
            ReconcileExit(executionTime);
        }

        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice,
            int quantity, int filled, double averageFillPrice, OrderState orderState,
            DateTime time, ErrorCode error, string comment)
        {
            if (order.Name != EntrySignal && order.Name != "WBReversalExit")
                return;
            if (orderState == OrderState.Filled || orderState == OrderState.Cancelled || orderState == OrderState.Rejected)
                pendingOrder = false;
            if (error != ErrorCode.NoError)
                Print(Name + ": " + order.Name + " " + error + " " + comment);
        }
    }
}
