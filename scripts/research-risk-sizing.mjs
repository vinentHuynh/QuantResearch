import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createCollective } from "../server/collective.ts";
import { calculatePortfolio, defaultPolicy } from "../src/collectiveModel.ts";
import { defaultSizing, summarizeDaily } from "../src/riskSizing.ts";

const stamp = new Date()
  .toISOString()
  .replaceAll(":", "-")
  .replaceAll(".", "-");
const folder = join("reports", `sizing-research-${stamp}`);
mkdirSync(folder, { recursive: true });
const api = createCollective(
  process.cwd(),
  join(process.cwd(), "data/workbench"),
  "python",
);
const catalog = api.catalog(),
  items = catalog.items.filter((i) => i.working);
const histories = api.series(items.map((i) => i.id));
const copies = Object.fromEntries(items.map((i) => [i.id, 1]));
const base = {
  ...defaultPolicy,
  enabled: true,
  volCap: 1,
  sizing: { ...defaultSizing, calibrationEnd: "2023-12-31" },
};
const variants = [
  ...[0.5, 0.75, 1].map((size) => ({
    name: `Constant ${size * 100}%`,
    policy: {
      ...base,
      mode: "fixed",
      sizing: { ...base.sizing, fixedSize: size },
    },
  })),
  {
    name: "Observed-session volatility",
    policy: {
      ...base,
      mode: "volatility",
      sizing: { ...base.sizing, estimator: "session" },
    },
  },
  { name: "EWMA volatility", policy: { ...base, mode: "volatility" } },
  { name: "Portfolio EWMA", policy: { ...base, mode: "portfolio" } },
  {
    name: "Portfolio EWMA whole contracts",
    policy: {
      ...base,
      mode: "portfolio",
      sizing: { ...base.sizing, wholeContracts: true },
    },
  },
  {
    name: "Deterioration review diagnostic",
    policy: { ...base, mode: "deterioration" },
  },
];
// Declare every variant before evaluating. This previously inspected interval is development evidence.
const plan = {
  created_at: new Date().toISOString(),
  hypothesis:
    "Compare simple fixed exposure with session/EWMA and portfolio caps; determine whether adaptive sizing improves on reduced constant exposure.",
  start: "2024-01-01",
  end: "2026-08-31",
  calibration_end: "2023-12-31",
  evidence:
    "Development comparison on previously inspected and selected books; not a fresh holdout",
  variants,
  sources: items.map((i) => ({
    id: i.id,
    checksum: i.checksum,
    file: i.series_file,
  })),
  assumptions: {
    copies,
    accounting: "closed",
    costs: "Recorded net costs scaled with exposure",
    margin:
      "Not configured: user budget and contract-specific requirements are absent",
    stateful_execution: false,
    intraday_open_risk: false,
  },
};
writeFileSync(join(folder, "plan.json"), JSON.stringify(plan, null, 2), {
  flag: "wx",
});
const results = [];
for (const variant of variants) {
  try {
    const result = calculatePortfolio(
      items,
      histories,
      copies,
      plan.start,
      plan.end,
      "closed",
      variant.policy,
    );
    const years = [
      ...new Set(result.points.map((p) => p.date.slice(0, 4))),
    ].map((year) => ({
      year,
      ...summarizeDaily(
        result.points.filter((p) => p.date.startsWith(year)).map((p) => p.pnl),
      ),
    }));
    results.push({
      name: variant.name,
      status: "Succeeded",
      ...result.comparison,
      trades: result.trades,
      skipped: result.components.reduce((n, c) => n + c.skipped, 0),
      exposure: result.exposure,
      years,
      execution: result.execution,
    });
    writeFileSync(
      join(folder, `decisions-${results.length}.json`),
      JSON.stringify(result.events, null, 2),
    );
  } catch (error) {
    results.push({
      name: variant.name,
      status: "Unavailable",
      error: error.message,
    });
  }
}
writeFileSync(
  join(folder, "results.json"),
  JSON.stringify({ plan, results }, null, 2),
);
writeFileSync(
  join(folder, "findings.md"),
  [
    "# Sizing development comparison",
    "",
    plan.evidence,
    "",
    "| Variant | Net P&L | Max closed drawdown | Worst day | Recovery | Trades |",
    "| --- | ---: | ---: | ---: | ---: | ---: |",
    ...results.map((r) =>
      r.status === "Succeeded"
        ? `| ${r.name} | ${r.net.toFixed(2)} | ${r.drawdown.toFixed(2)} | ${r.worstDay.toFixed(2)} | ${r.recovery?.toFixed(2) ?? "n/a"} | ${r.trades} |`
        : `| ${r.name} | Unavailable: ${r.error} | | | | |`,
    ),
    "",
    "All variants, including unavailable and zero-trade outcomes, are retained. Whole-contract rounding is a fixed-ledger feasibility replay; it does not rerun strategy state, intraday risk, micro fills, nonlinear costs or brokerage margin. No margin budget or per-trade stop-risk budget was supplied. No configuration is promoted or auto-selected. Exact settings and source checksums are frozen in plan.json before evaluation.",
    "",
  ].join("\n"),
);
console.log(JSON.stringify({ folder, results }, null, 2));
