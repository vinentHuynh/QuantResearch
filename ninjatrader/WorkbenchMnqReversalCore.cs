using System;
using System.Collections.Generic;

namespace NinjaTrader.NinjaScript.Strategies
{
    // System-only streaming port of short_term_reversal_minute.schedule and
    // short_term_reversal.signals: inclusive SMA, strict decline, one flat interval.
    public sealed class WorkbenchMnqReversalCore
    {
        private readonly int lookback;
        private readonly double declinePercent;
        private readonly Queue<double> closes = new Queue<double>();
        private double closeSum, previousClose;
        private int dailyTarget;
        private DateTime firstOpen = DateTime.MinValue;
        private DateTime rthDate = DateTime.MinValue;
        private DateTime lastScheduleDate = DateTime.MinValue;
        private double rthClose;
        private bool rthIncluded, rthPublished;

        public WorkbenchMnqReversalCore(int trendLookback, double declinePct)
        {
            if (trendLookback < 2 || declinePct <= 0)
                throw new ArgumentException("Invalid reversal settings.");
            lookback = trendLookback;
            declinePercent = declinePct;
        }

        public int CompletedDays { get; private set; }
        public bool Ready { get { return CompletedDays >= lookback + 1; } }
        public int DailyTarget { get { return dailyTarget; } }

        // Both timestamps are Eastern wall-clock times. Return null except on
        // the first completed minute >=09:35 and <16:00 of each weekday.
        public int? OnMinute(DateTime barOpen, DateTime barClose, double close)
        {
            if (firstOpen == DateTime.MinValue)
                firstOpen = barOpen;
            // Publish a sparse/early-close prior day only after its nominal16:00.
            if (rthDate != DateTime.MinValue && barOpen >= rthDate.AddHours(16))
                PublishDay();
            int openingMinute = barOpen.Hour * 60 + barOpen.Minute;
            bool weekday = barOpen.DayOfWeek != DayOfWeek.Saturday
                && barOpen.DayOfWeek != DayOfWeek.Sunday;
            if (weekday && openingMinute >= 570 && openingMinute < 960)
            {
                if (rthDate != barOpen.Date)
                {
                    rthDate = barOpen.Date;
                    rthPublished = false;
                    rthIncluded = firstOpen <= rthDate.AddMinutes(570);
                }
                rthClose = close;
            }
            if (rthDate != DateTime.MinValue && barClose >= rthDate.AddHours(16))
                PublishDay();

            int minute = barClose.Hour * 60 + barClose.Minute;
            if (barClose.DayOfWeek == DayOfWeek.Saturday || barClose.DayOfWeek == DayOfWeek.Sunday
                || minute < 575 || minute >= 960 || lastScheduleDate == barClose.Date)
                return null;
            lastScheduleDate = barClose.Date;
            // Source permits five minutes of entry lateness; exits always remain
            // eligible at the first available completed morning/RTH minute.
            return minute <= 580 ? dailyTarget : 0;
        }

        private void PublishDay()
        {
            if (rthPublished)
                return;
            rthPublished = true;
            if (!rthIncluded)
                return;
            closes.Enqueue(rthClose);
            closeSum += rthClose;
            if (closes.Count > lookback)
                closeSum -= closes.Dequeue();
            bool signal = closes.Count == lookback && previousClose > 0 && rthClose > 0
                && previousClose - rthClose > previousClose * (declinePercent / 100.0)
                && rthClose > closeSum / lookback;
            // Expiry wins over today's signal: renewal is disabled in the source.
            dailyTarget = dailyTarget != 0 ? 0 : (signal ? 1 : 0);
            previousClose = rthClose;
            CompletedDays++;
        }
    }
}
