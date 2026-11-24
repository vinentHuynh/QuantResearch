import { execFile } from "node:child_process";
import type { Dataset, Run } from "../../core/contracts.ts";
import type {
  CollectiveItem,
  CollectiveSeries,
} from "../../../shared/ts/portfolio.ts";
import type { DayChart } from "../../../shared/ts/tradeChart.ts";

export async function loadTradeChart({
  root,
  python,
  env,
  item,
  history,
  day,
  signal,
  datasets,
  findRun,
}: {
  root: string;
  python: string;
  env: NodeJS.ProcessEnv;
  item: CollectiveItem;
  history: CollectiveSeries;
  day: string;
  signal: AbortSignal;
  datasets: Dataset[];
  findRun: (id: string) => Run | undefined;
}): Promise<DayChart> {
  const start = Date.parse(day);
  const trades = history.trades.flatMap((trade, index) =>
    Date.parse(trade.entry) < start + 86400000 &&
    Date.parse(trade.exit) >= start
      ? [{ ...trade, index }]
      : [],
  );
  const ids = new Set([
    ...(item.source_run_ids || []),
    ...trades.map((t) => t.source_run),
    item.verified_replay?.source_run_id,
  ]);
  const runs = [...ids].flatMap((id) => {
    if (!id) return [];
    const run = findRun(id);
    if (
      !run ||
      run.status !== "Succeeded" ||
      run.input.dataset.symbol !== item.symbol ||
      run.input.start > day ||
      run.input.end < day
    )
      return [];
    return [
      {
        id,
        dataset: run.input.dataset,
        artifacts: run.result?.artifacts || [],
      },
    ];
  });
  const request = {
    day,
    item,
    trades,
    runs,
    datasets: datasets.filter((d) => d.symbol === item.symbol),
  };
  return new Promise((resolve, reject) => {
    const child = execFile(
      python,
      ["-m", "workbench.trade_chart"],
      {
        cwd: root,
        env,
        windowsHide: true,
        signal,
        timeout: 45000,
        maxBuffer: 8 * 1024 * 1024,
      },
      (error, stdout) => {
        if (error)
          return reject(
            new Error(
              "The chart reader could not load this day. Check the workbench Python environment and retry.",
            ),
          );
        try {
          resolve(JSON.parse(stdout));
        } catch {
          reject(new Error("The chart reader returned an invalid response."));
        }
      },
    );
    child.stdin?.on("error", () => {
      /* The completion callback reports early exits. */
    });
    child.stdin?.end(JSON.stringify(request));
  });
}
