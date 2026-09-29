using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;

namespace NinjaTrader.NinjaScript.Strategies
{
    // Port: strategies/pine_tsmom_orb.py + _pine_models.IntradayORB, with the
    // explicit September2026 session-calendar repair. Research provenance is
    // the NQ5m configuration; actual decisions here use MNQ prices, not NQ.
    // Defaults: one MNQ, $250 stop-risk budget ($2/point) = original NQ $2500
    // at $20/point, preserving the125-point one-contract cutoff. No10x sizing.
    //
    // Normal timing is preserved: OR bars close09:35/09:40/09:45 ET, first
    // entry decision09:50, normal flat decision15:50. Early-close deadline:
    // min(15:50, Trading Hours actual session end minus5 minutes). The native
    // 60-second session-close feature is a separate real-time fallback.
    // Requires the current CME US Index Futures ETH holiday template.
    //
    // Simulation differences: Python fills at the decision close; NT submits a
    // market order for the next available quote. Fixed brackets remain anchored
    // to the SIGNAL close, never silently changed to fill-relative2R. Native
    // stop/target fill priority, queueing, gaps, tick rounding and partial fills
    // differ from the workbench's one-minute stop-first simulator. Configure NT
    // commissions explicitly; Slippage=1 is an Analyzer assumption, not a cap.
    // Load >=600 calendar days /253 completed ETH sessions. Warmup daily closes
    // are aggregated from intraday last-observed prices, not settlement bars.
    // Compilation and core tests are not brokerage or Playback validation.
    public class WorkbenchMnqTsmomOrb : Strategy
    {
        private const string EntrySignal = "WBOrbEntry";
        private const string ExitSignal = "WBOrbFlat";
        private WorkbenchMnqTsmomOrbCore model;
        private SessionIterator sessions;
        private TimeZoneInfo platformZone;
        private DateTime deadlineEt = DateTime.MinValue;
        private DateTime entryCalendarDate = DateTime.MinValue;
        private DateTime lastBarDate = DateTime.MinValue;
        private Order entryOrder;
        private bool entryPending, exitPending, cancelRequested, flattenRequested, fatalOrderError;
        private double activeStop;
        private int activeDirection;

        [NinjaScriptProperty]
        [Range(1, 20)]
        [Display(Name = "Maximum MNQ contracts", Order = 1, GroupName = "Risk",
            Description = "Hard cap; default1 micro. Increasing it changes the selected position size.")]
        public int MaximumContracts { get; set; }

        [NinjaScriptProperty]
        [Range(1.0, 100000.0)]
        [Display(Name = "MNQ stop-risk budget ($)", Order = 2, GroupName = "Risk",
            Description = "$250 preserves the tested NQ $2500 point-distance cutoff. Excludes costs, gaps and slippage.")]
        public double RiskBudget { get; set; }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "WorkbenchMnqTsmomOrb";
                Description = "MNQ5m TSMOM ORB with explicit early-close calendar repair;1 micro/$250 default; ET clocks and signal-close brackets.";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                BarsRequiredToTrade = 0;
                StartBehavior = StartBehavior.WaitUntilFlat;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling = StopTargetHandling.PerEntryExecution;
                TimeInForce = TimeInForce.Gtc;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 60;
                IsFillLimitOnTouch = false;
                OrderFillResolution = OrderFillResolution.Standard;
                Slippage = 1;
                IsInstantiatedOnEachOptimizationIteration = true;
                MaximumContracts = 1;
                RiskBudget = 250;
            }
            else if (State == State.DataLoaded)
            {
                if (Instrument.MasterInstrument.Name != "MNQ"
                    || Math.Abs(Instrument.MasterInstrument.PointValue - 2.0) > 1e-9
                    || Math.Abs(TickSize - .25) > 1e-9
                    || BarsPeriod.BarsPeriodType != BarsPeriodType.Minute || BarsPeriod.Value != 5
                    || Bars.TradingHours.Name != "CME US Index Futures ETH")
                    throw new InvalidOperationException(Name + " requires MNQ ($2/point,0.25tick),5 Minute,CME US Index Futures ETH.");
                if (Calculate != Calculate.OnBarClose)
                    throw new InvalidOperationException(Name + " requires Calculate.OnBarClose.");
                if (!IsExitOnSessionCloseStrategy || ExitOnSessionCloseSeconds < 60)
                    throw new InvalidOperationException(Name + " requires native session-close safety enabled at least60seconds before close.");
                platformZone = NinjaTrader.Core.Globals.GeneralOptions.TimeZoneInfo;
                sessions = new SessionIterator(Bars);
                model = new WorkbenchMnqTsmomOrbCore(RiskBudget, MaximumContracts);
                entryPending = exitPending = cancelRequested = flattenRequested = fatalOrderError = false;
                entryOrder = null;
                deadlineEt = entryCalendarDate = lastBarDate = DateTime.MinValue;
                Print(Name + ": needs253 completed ETH sessions; load600+calendar days. $250/1MNQ preserves NQ $2500/1 contract point cutoff. Update Trading Hours holiday definitions; paper/Playback execution review remains required.");
            }
            else if (State == State.Realtime && entryOrder != null && !Terminal(entryOrder.OrderState))
            {
                // Historical order references must be remapped before canceling.
                entryOrder = GetRealtimeOrder(entryOrder);
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0 || model == null) return;
            DateTime end = WorkbenchMnqTsmomOrbCore.ToEastern(Time[0], platformZone);
            DateTime start = WorkbenchMnqTsmomOrbCore.BarOpenEastern(Time[0], platformZone);
            if (CurrentBar == 0 || Bars.IsFirstBarOfSession)
                sessions.GetNextSession(Time[0], true);
            DateTime sessionEnd = WorkbenchMnqTsmomOrbCore.ToEastern(sessions.ActualSessionEnd, platformZone);
            deadlineEt = WorkbenchMnqTsmomOrbCore.FlattenDeadline(start.Date, sessionEnd);

            if (lastBarDate != start.Date)
            {
                // Never clear a close request while fills/orders remain in flight.
                if (Position.MarketPosition == MarketPosition.Flat && !entryPending && !exitPending)
                    flattenRequested = false;
                else if (lastBarDate != DateTime.MinValue)
                    flattenRequested = true;
                lastBarDate = start.Date;
            }

            int position = Position.MarketPosition == MarketPosition.Long ? Position.Quantity
                : Position.MarketPosition == MarketPosition.Short ? -Position.Quantity : 0;
            WorkbenchOrbDecision decision = model.OnBar(start, end, sessionEnd,
                High[0], Low[0], Close[0], position,
                !entryPending && !exitPending && !flattenRequested && !fatalOrderError);
            if (end >= deadlineEt || decision.Action == WorkbenchOrbAction.Flatten
                || decision.Action == WorkbenchOrbAction.EmergencyFlatten)
            {
                flattenRequested = true;
                if (decision.Action == WorkbenchOrbAction.EmergencyFlatten)
                    Print(Name + ": unexpected carry at " + end.ToString("s") + "; emergency close requested. This is an execution/data failure, not an equivalent before-close fill.");
            }
            ReconcileFlatten();
            if (flattenRequested || fatalOrderError || entryPending || exitPending
                || Position.MarketPosition != MarketPosition.Flat)
                return;
            if (decision.Action != WorkbenchOrbAction.Long && decision.Action != WorkbenchOrbAction.Short)
                return;

            // The bar may arrive late after a disconnect. Use the same Playback-
            // aware application clock as NT's shipped BarTimer indicator.
            if (State == State.Realtime)
            {
                DateTime now = CurrentEasternTime();
                if (now.Date != end.Date || now >= deadlineEt) return;
            }
            activeDirection = decision.Action == WorkbenchOrbAction.Long ? 1 : -1;
            activeStop = Instrument.MasterInstrument.RoundToTickSize(decision.Stop);
            double target = Instrument.MasterInstrument.RoundToTickSize(decision.Target);
            entryCalendarDate = start.Date;
            // Set methods arm real stop-market/OCO target protection before
            // submission. PerEntryExecution protects each partial entry fill.
            SetStopLoss(EntrySignal, CalculationMode.Price, activeStop, false);
            SetProfitTarget(EntrySignal, CalculationMode.Price, target);
            entryOrder = null;
            cancelRequested = false;
            entryPending = true; // set BEFORE submitting: Playback can fill synchronously
            if (activeDirection > 0) EnterLong(decision.Quantity, EntrySignal);
            else EnterShort(decision.Quantity, EntrySignal);
        }

        private DateTime CurrentEasternTime()
        {
            DateTime now = Connection.PlaybackConnection != null
                ? Connection.PlaybackConnection.Now : NinjaTrader.Core.Globals.Now;
            return WorkbenchMnqTsmomOrbCore.ToEastern(now, platformZone);
        }

        private void ReconcileFlatten()
        {
            if (!flattenRequested) return;
            if (entryPending && entryOrder != null && !Terminal(entryOrder.OrderState) && !cancelRequested)
            {
                cancelRequested = true;
                CancelOrder(entryOrder); // cancel remainder; filled quantity remains protected
            }
            if (exitPending) return;
            if (Position.MarketPosition == MarketPosition.Long)
            {
                exitPending = true;
                ExitLong(ExitSignal, EntrySignal);
            }
            else if (Position.MarketPosition == MarketPosition.Short)
            {
                exitPending = true;
                ExitShort(ExitSignal, EntrySignal);
            }
        }

        protected override void OnExecutionUpdate(Execution execution, string executionId,
            double price, int quantity, MarketPosition marketPosition, string orderId, DateTime time)
        {
            if (model == null || execution.Order == null) return;
            if (execution.Order.Name == EntrySignal)
            {
                DateTime fillTime = WorkbenchMnqTsmomOrbCore.ToEastern(time, platformZone);
                // A delayed fill after the deadline/date or through its original
                // stop must never leave an intentionally unprotected position.
                if (fillTime.Date != entryCalendarDate || fillTime >= deadlineEt
                    || (activeDirection > 0 ? price <= activeStop : price >= activeStop))
                    flattenRequested = true;
            }
            // Late entry partial fills after an exit was requested, and residual
            // quantity after a partial exit, retain the same flat intent.
            ReconcileFlatten();
        }

        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice,
            int quantity, int filled, double averageFillPrice, OrderState orderState,
            DateTime time, ErrorCode error, string comment)
        {
            if (order.Name == EntrySignal)
            {
                entryOrder = order;
                if (Terminal(orderState)) entryPending = false;
                else if (flattenRequested && !cancelRequested)
                {
                    // An async acceptance can arrive after the close request,
                    // when the first cancellation attempt had no order reference.
                    cancelRequested = true;
                    CancelOrder(order);
                }
            }
            else if (order.Name == ExitSignal && Terminal(orderState))
                exitPending = false;
            if (error != ErrorCode.NoError || orderState == OrderState.Rejected)
            {
                fatalOrderError = true; // no subsequent entries after ANY rejection
                flattenRequested = true;
                Print(Name + ": order error " + order.Name + " " + error + " " + comment
                    + "; native StopCancelClose handles rejected orders.");
            }
        }

        private static bool Terminal(OrderState state)
        {
            return state == OrderState.Filled || state == OrderState.Cancelled || state == OrderState.Rejected;
        }
    }
}
