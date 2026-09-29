import { mkdirSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const folder = resolve("reports/workbench-review-2026-09-16");
mkdirSync(folder, { recursive: true });
const save = (name, value) =>
  writeFileSync(resolve(folder, name), JSON.stringify(value, null, 2));
const api = async (path, body) => {
  const r = await fetch(
    "http://127.0.0.1:8001/api/workbench" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await r.json();
  if (!r.ok) throw new Error(JSON.stringify(data));
  return data;
};
await api("/discover", {});
const state = await api("/state");
if (!existsSync(resolve(folder, "state-before.json")))
  save("state-before.json", state);
save("source-inventory.json", state.library);
const plan = [];
for (const strategy of state.strategies) {
  const datasets =
    strategy.id === "snd"
      ? state.datasets
      : state.datasets.filter((d) => d.symbol === "MNQ");
  for (const dataset of datasets)
    for (const timeframe of strategy.timeframes) {
      const variants =
        strategy.id === "snd"
          ? [
              "original_multi_tf",
              "phase6",
              "phase7_prior_1m",
              "phase7_prior_5m",
            ]
          : [null];
      for (const variant of variants) {
        const parameters = Object.fromEntries(
          Object.entries(strategy.parameters).map(([key, spec]) => [
            key,
            spec.default,
          ]),
        );
        if ("sizing_mode" in parameters)
          parameters.sizing_mode = "Fixed contracts";
        if (strategy.id === "pine-tsmom-orb")
          Object.assign(parameters, {
            risk_budget: 2500,
            maximum_contracts: 1,
          });
        if (variant) parameters.variant = variant;
        plan.push({
          strategy_id: strategy.id,
          dataset_id: dataset.id,
          timeframe,
          session: strategy.default_session || "full-trading-day",
          start: strategy.id === "snd" ? "2026-01-01" : "2022-01-01",
          end: "2026-08-31",
          capital: 100000,
          fee: 1.25,
          slippage: 1,
          warmup_days: strategy.default_warmup_days || 30,
          timeout: 1800,
          parameters,
          hypothesis:
            "Coverage audit: frozen adapter defaults, MNQ supported charts and SND 2026 variants on five markets. Descriptive historical analysis; already inspected dates, no fresh holdout or selection claim.",
          tags: ["coverage-audit-2026-09-16"],
        });
      }
    }
}
save("protocol.json", {
  created_at: new Date().toISOString(),
  selection: "No optimization or winner selection. Preserve every attempt.",
  requests: plan,
});
const recordPath = resolve(folder, "campaign.json");
const campaign = existsSync(recordPath)
  ? JSON.parse(readFileSync(recordPath, "utf8"))
  : { runs: {}, previews: {} };
for (const [index, request] of plan.entries()) {
  if (campaign.runs[index]) continue;
  campaign.previews[index] = await api("/preview", request);
  save("campaign.json", campaign);
  const runs = await api("/runs", request);
  campaign.runs[index] = runs[0].id;
  save("campaign.json", campaign);
  console.log(
    "Queued",
    index + 1,
    "/",
    plan.length,
    request.strategy_id,
    request.timeframe,
    request.parameters.variant || "",
  );
}
console.log("All requests validated and queued.");
