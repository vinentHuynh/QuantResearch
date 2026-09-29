using System;
using System.Globalization;
using System.IO;
using NinjaTrader.NinjaScript.Strategies;

public static class ReversalReplay
{
    public static int Main(string[] args)
    {
        var core = new WorkbenchMnqReversalCore(int.Parse(args[2]), 1.25);
        using (var input = new BinaryReader(File.OpenRead(args[0])))
        using (var output = new StreamWriter(args[1]))
        {
            int index = 0;
            while (input.BaseStream.Position < input.BaseStream.Length)
            {
                var open = new DateTime(input.ReadInt64());
                var close = new DateTime(input.ReadInt64());
                int? decision = core.OnMinute(open, close, input.ReadDouble());
                if (decision.HasValue)
                    output.WriteLine(index.ToString(CultureInfo.InvariantCulture) + "," + decision.Value + "," + core.CompletedDays);
                index++;
            }
        }
        return 0;
    }
}
