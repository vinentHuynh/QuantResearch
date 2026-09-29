using System;
using System.Collections.Generic;

namespace NinjaTrader.NinjaScript.Strategies
{
    public enum WorkbenchOrbAction { None, Long, Short, RiskSkipped, Flatten, EmergencyFlatten }

    public sealed class WorkbenchOrbDecision
    {
        public WorkbenchOrbAction Action;
        public int Quantity;
        public double Stop, Target, Score;
        public DateTime Deadline;
    }

    // System-only streaming port of _pine_models.daily_features / IntradayORB.
    // Selected rules: 20/60/120/252 daily votes, |score| >= .5, close breakout,
    // OR09:30-09:45, entry09:45-15:00, 2R. The calendar fix adds a deadline
    // at min(normal15:50 completed-bar time, actual ETH close minus5 minutes),
    // catches missed flat windows, and prevents a previous date's OR reuse.
    public sealed class WorkbenchMnqTsmomOrbCore
    {
        private readonly int[] lengths;
        private readonly int longest;
        private readonly double riskBudget;
        private readonly int maximumContracts;
        private readonly List<double> dailyCloses = new List<double>();
        private DateTime dailyDate = DateTime.MinValue;
        private DateTime rangeDate = DateTime.MinValue;
        private DateTime lastBarOpen = DateTime.MinValue;
        private DateTime entrySessionEnd = DateTime.MinValue;
        private double dailyClose;
        private bool attempted;
        private double rangeHigh = double.NaN, rangeLow = double.NaN;

        public WorkbenchMnqTsmomOrbCore(double budget, int cap,
            int fast = 20, int medium = 60, int slow = 120, int annual = 252)
        {
            if (!Finite(budget) || budget < 1 || budget > 100000 || cap < 1 || cap > 20)
                throw new ArgumentException("ORB budget must be $1..100000; cap must be 1..20 MNQ.");
            lengths = new int[] { fast, medium, slow, annual };
            foreach (int length in lengths)
            {
                if (length < 2 || length > 500) throw new ArgumentException("Daily lookbacks must be 2..500.");
                longest = Math.Max(longest, length);
            }
            riskBudget = budget;
            maximumContracts = cap;
            DailyScore = double.NaN;
        }

        public double DailyScore { get; private set; }
        public int CompletedSessions { get; private set; }
        public bool Ready { get { return CompletedSessions > longest; } }
        public double OpeningHigh { get { return rangeHigh; } }
        public double OpeningLow { get { return rangeLow; } }
        public bool Attempted { get { return attempted; } }

        public static DateTime ToEastern(DateTime platformTime, TimeZoneInfo platformZone)
        {
            DateTime local = DateTime.SpecifyKind(platformTime, DateTimeKind.Unspecified);
            if (platformZone.IsInvalidTime(local) || platformZone.IsAmbiguousTime(local))
                throw new InvalidOperationException("Ambiguous/invalid platform timestamp; use UTC or a US market timezone.");
            return TimeZoneInfo.ConvertTime(local, platformZone,
                TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"));
        }

        public static DateTime BarOpenEastern(DateTime platformClose, TimeZoneInfo platformZone)
        {
            DateTime local = DateTime.SpecifyKind(platformClose, DateTimeKind.Unspecified);
            if (platformZone.IsInvalidTime(local) || platformZone.IsAmbiguousTime(local))
                throw new InvalidOperationException("Ambiguous/invalid platform timestamp; use UTC or a US market timezone.");
            // Subtract elapsed minutes in UTC, avoiding wall-clock DST arithmetic.
            DateTime utc = TimeZoneInfo.ConvertTimeToUtc(local, platformZone).AddMinutes(-5);
            return TimeZoneInfo.ConvertTimeFromUtc(utc, TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"));
        }

        public static DateTime FlattenDeadline(DateTime easternDate, DateTime scheduledSessionEnd)
        {
            DateTime normal = easternDate.Date.AddMinutes(950); // 15:45-start bar closes15:50
            DateTime beforeSessionEnd = scheduledSessionEnd.AddMinutes(-5);
            return beforeSessionEnd < normal ? beforeSessionEnd : normal;
        }

        public WorkbenchOrbDecision OnBar(DateTime barOpen, DateTime barClose, DateTime scheduledSessionEnd,
            double high, double low, double close, int position, bool allowEntry)
        {
            if (!Finite(high) || !Finite(low) || !Finite(close) || high < low || close < low || close > high)
                throw new ArgumentException("Invalid ORB OHLC.");
            if (barClose <= barOpen || scheduledSessionEnd < barClose)
                throw new ArgumentException("Invalid completed bar / scheduled session end.");
            if (lastBarOpen != DateTime.MinValue && barOpen < lastBarOpen)
                throw new ArgumentException("ORB bars must be chronological.");
            WorkbenchOrbDecision result = new WorkbenchOrbDecision();
            result.Score = DailyScore;
            result.Deadline = FlattenDeadline(barOpen.Date, scheduledSessionEnd);
            if (barOpen == lastBarOpen) return result;
            lastBarOpen = barOpen;

            int minute = barOpen.Hour * 60 + barOpen.Minute;
            // Full trading day is fixed18:00-17:00 ET. Daily signal publication
            // remains nominal17:00, including early-close last-observed prices.
            if (minute >= 1020 && minute < 1080) return result;
            DateTime date = minute >= 1080 ? barOpen.Date.AddDays(1) : barOpen.Date;
            if (date != dailyDate)
            {
                if (dailyDate != DateTime.MinValue)
                {
                    if (barOpen < dailyDate.AddHours(17))
                        throw new ArgumentException("Daily close cannot publish before nominal17:00 ET.");
                    dailyCloses.Add(dailyClose);
                    CompletedSessions++;
                    if (dailyCloses.Count > longest + 1) dailyCloses.RemoveAt(0);
                    DailyScore = CalculateScore();
                }
                dailyDate = date;
            }
            dailyClose = close;
            result.Score = DailyScore;

            bool newDate = rangeDate != barOpen.Date;
            if (newDate)
            {
                rangeDate = barOpen.Date;
                rangeHigh = rangeLow = double.NaN;
                attempted = false;
            }
            bool opening = minute >= 570 && minute < 585;
            if (opening)
            {
                rangeHigh = double.IsNaN(rangeHigh) ? high : Math.Max(rangeHigh, high);
                rangeLow = double.IsNaN(rangeLow) ? low : Math.Min(rangeLow, low);
            }

            if (position != 0 && (newDate || (entrySessionEnd != DateTime.MinValue && barOpen >= entrySessionEnd)))
            {
                // Python rejects these missing-exit-data histories. A running
                // adapter must instead request an emergency close, never claim
                // its fill reproduces a successful before-close exit.
                result.Action = WorkbenchOrbAction.EmergencyFlatten;
                return result;
            }
            if (position != 0 && barClose >= result.Deadline)
            {
                result.Action = WorkbenchOrbAction.Flatten;
                return result;
            }
            if (!allowEntry || position != 0 || opening || attempted || !(rangeHigh > rangeLow)
                || minute < 585 || minute >= 900 || barClose >= result.Deadline)
                return result;

            int direction = DailyScore >= .5 ? 1 : DailyScore <= -.5 ? -1 : 0;
            bool longBreak = direction > 0 && close > rangeHigh;
            bool shortBreak = direction < 0 && close < rangeLow;
            if (!(longBreak || shortBreak)) return result;
            attempted = true; // an unaffordable first attempt consumes the day
            double stop = longBreak ? rangeLow : rangeHigh;
            double risk = Math.Abs(close - stop);
            int quantity = risk > 0 ? (int)Math.Min(maximumContracts, Math.Floor(riskBudget / (risk * 2.0))) : 0;
            result.Action = quantity > 0 ? (longBreak ? WorkbenchOrbAction.Long : WorkbenchOrbAction.Short)
                : WorkbenchOrbAction.RiskSkipped;
            result.Quantity = quantity;
            result.Stop = stop;
            result.Target = close + direction * 2.0 * risk;
            if (quantity > 0) entrySessionEnd = scheduledSessionEnd;
            return result;
        }

        private double CalculateScore()
        {
            int last = dailyCloses.Count - 1;
            if (last < longest) return double.NaN;
            int votes = 0;
            foreach (int length in lengths) votes += Math.Sign(dailyCloses[last] - dailyCloses[last - length]);
            return votes / 4.0;
        }

        private static bool Finite(double value) { return !double.IsNaN(value) && !double.IsInfinity(value); }
    }
}
