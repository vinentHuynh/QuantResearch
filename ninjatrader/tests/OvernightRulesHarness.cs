using System;
using System.Globalization;
using NinjaTrader.NinjaScript.Strategies;

internal static class OvernightRulesHarness
{
    public static void Main(string[] args)
    {
        var rules = new WorkbenchMnqOvernightRules();
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            string[] fields = line.Split(';');
            DateTime timestamp = DateTime.ParseExact(fields[1], "yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
            if (fields[0] == "zone")
            {
                Console.WriteLine(WorkbenchMnqOvernightRules.ToEastern(timestamp,
                    TimeZoneInfo.FindSystemTimeZoneById(fields[2])).ToString("yyyy-MM-dd HH:mm:ss"));
                continue;
            }
            bool held = fields[2] == "1";
            Console.WriteLine(fields[0] == "block" ? rules.BlockSignal(timestamp, held) : rules.SessionSignal(timestamp, held));
        }
    }
}
