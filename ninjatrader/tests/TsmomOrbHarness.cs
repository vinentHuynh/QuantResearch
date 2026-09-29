using System;
using System.Globalization;
using NinjaTrader.NinjaScript.Strategies;

// Standalone console harness; compiled with the actual System-only core.
public static class TsmomOrbHarness
{
    private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
    private static DateTime Date(string value) { return DateTime.Parse(value, Invariant); }
    private static double Number(string value) { return double.Parse(value, Invariant); }

    public static int Main()
    {
        WorkbenchMnqTsmomOrbCore model = new WorkbenchMnqTsmomOrbCore(250, 1);
        string row;
        while ((row = Console.ReadLine()) != null)
        {
            if (row.Length == 0) continue;
            string[] f = row.Split(';');
            if (f[0] == "config")
            {
                model = new WorkbenchMnqTsmomOrbCore(Number(f[1]), int.Parse(f[2]),
                    int.Parse(f[3]), int.Parse(f[4]), int.Parse(f[5]), int.Parse(f[6]));
                continue;
            }
            if (f[0] == "zone")
            {
                try
                {
                    TimeZoneInfo zone = TimeZoneInfo.FindSystemTimeZoneById(f[2]);
                    Console.WriteLine(WorkbenchMnqTsmomOrbCore.ToEastern(Date(f[1]), zone).ToString("s")
                        + ";" + WorkbenchMnqTsmomOrbCore.BarOpenEastern(Date(f[1]), zone).ToString("s"));
                }
                catch (InvalidOperationException) { Console.WriteLine("INVALID_TIME"); }
                continue;
            }
            WorkbenchOrbDecision result = model.OnBar(Date(f[1]), Date(f[2]), Date(f[3]),
                Number(f[4]), Number(f[5]), Number(f[6]), int.Parse(f[7]), f[8] == "1");
            Console.WriteLine(result.Action + ";" + result.Quantity + ";"
                + result.Stop.ToString("R", Invariant) + ";" + result.Target.ToString("R", Invariant) + ";"
                + result.Score.ToString("R", Invariant) + ";" + result.Deadline.ToString("s") + ";"
                + model.CompletedSessions + ";" + model.OpeningHigh.ToString("R", Invariant) + ";"
                + model.OpeningLow.ToString("R", Invariant));
        }
        return 0;
    }
}
