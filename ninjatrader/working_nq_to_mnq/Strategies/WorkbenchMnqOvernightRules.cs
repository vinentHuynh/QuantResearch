using System;

namespace NinjaTrader.NinjaScript.Strategies
{
    // Pure clock decisions shared by the two overnight adapters and their tests.
    // Return +1 to buy, -1 to flatten, 0 to leave the current position unchanged.
    public sealed class WorkbenchMnqOvernightRules
    {
        private bool previousBlockInside;
        private DateTime sessionAttemptDate = DateTime.MinValue;

        public static DateTime ToEastern(DateTime platformTime, TimeZoneInfo platformZone)
        {
            return TimeZoneInfo.ConvertTime(DateTime.SpecifyKind(platformTime, DateTimeKind.Unspecified),
                platformZone, TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"));
        }

        public static bool BlockWindow(DateTime easternClose)
        {
            int minute = easternClose.Hour * 60 + easternClose.Minute;
            return minute >= 17 * 60 || minute < 6 * 60;
        }

        public int BlockSignal(DateTime easternClose, bool longPosition)
        {
            bool prior = previousBlockInside;
            bool inside = BlockWindow(easternClose);
            previousBlockInside = inside;
            if (longPosition && !inside)
                return -1;
            // Match OvernightBlock.on_close exactly: transition on the observed
            // completed-bar clock, with initial prior=false. No invented
            // continuity, weekday or holiday filter is added to the source.
            if (!longPosition && inside && !prior)
                return 1;
            return 0;
        }

        public int SessionSignal(DateTime easternClose, bool longPosition)
        {
            int minute = easternClose.Hour * 60 + easternClose.Minute;
            if (longPosition && ((minute >= 6 * 60 && minute < 18 * 60)
                || (sessionAttemptDate != DateTime.MinValue
                    && easternClose >= sessionAttemptDate.AddDays(1).AddHours(6))))
                return -1;

            // Conservative-execution scenario: complete the opening minute,
            // then buy its next open (normally 18:01). Never chase a missing bar.
            bool evening = easternClose.DayOfWeek != DayOfWeek.Friday
                && easternClose.DayOfWeek != DayOfWeek.Saturday;
            if (!longPosition && evening && easternClose.TimeOfDay == new TimeSpan(18, 1, 0)
                && sessionAttemptDate != easternClose.Date)
            {
                sessionAttemptDate = easternClose.Date;
                return 1;
            }
            return 0;
        }
    }
}
