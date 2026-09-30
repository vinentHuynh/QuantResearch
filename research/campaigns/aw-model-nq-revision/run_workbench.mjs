// Launch the preregistered AW revision variants through the Workbench API.
// Usage: node run_workbench.mjs preview|launch|status INTERVAL_LABEL [variant_label]
// Campaign files default to WORKBENCH_ARTIFACTS/research/aw-model-nq-2026-09-29/revision.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadWorkbenchLayout } from "../../../server/layout.ts";

const folder = dirname(fileURLToPath(import.meta.url));
const root = resolve(folder, "../../..");
const artifactsRoot = loadWorkbenchLayout(root).artifactsRoot;
const campaignFolder = process.env.AW_REVISION_CAMPAIGN_DIR
  ? resolve(root, process.env.AW_REVISION_CAMPAIGN_DIR)
  : join(artifactsRoot, "research", "aw-model-nq-2026-09-29", "revision");
const plan = JSON.parse(readFileSync(join(campaignFolder, "RUN_PLAN.json"), "utf8"));
const campaign = plan.campaign_id || "initial_v1";
const mode = process.argv[2];
const label = process.argv[3];
const onlyVariant = process.argv[4];
const period = plan.intervals_in_order.find((item) => item.label === label);
const selectedVariants = plan.variants_in_order.filter((item) => !onlyVariant || item.label === onlyVariant);
const base = process.env.WORKBENCH_URL || "http://127.0.0.1:8001";
const receiptPath = join(campaignFolder, "LAUNCH_RECEIPTS.json");
if (!["preview", "launch", "status"].includes(mode) || !period || !selectedVariants.length) {
  throw new Error("Usage: node run_workbench.mjs preview|launch|status INTERVAL_LABEL [variant_label]");
}

async function api(path, init) {
  const response = await fetch(base + path, init);
  const data = await response.json();
  if (!response.ok) throw new Error(`${response.status} ${path}: ${JSON.stringify(data)}`);
  return data;
}
function bodyFor(variant) {
  return {
    strategy_id: plan.strategy_id,
    dataset_id: plan.dataset_id,
    timeframe: plan.timeframe,
    session: plan.session,
    start: period.start,
    end: period.end,
    stage: plan.stage,
    capital: plan.capital,
    warmup_days: plan.warmup_days,
    timeout: plan.timeout,
    delay_bars: plan.delay_bars,
    fee: variant.fee,
    slippage: variant.slippage,
    parameters: { ...plan.common_parameters, ...variant.parameters },
    hypothesis: `AW Reversal frozen revision | ${campaign} | ${period.label} | ${variant.label} | $500 planned structural risk | see revision/PROTOCOL.md and RUN_PLAN.json`,
  };
}
function readReceipts() {
  try { return JSON.parse(readFileSync(receiptPath, "utf8")); }
  catch (error) { if (error.code === "ENOENT") return { recorded_at_utc: new Date().toISOString(), attempts: [] }; throw error; }
}
function save(receipts) {
  writeFileSync(receiptPath, JSON.stringify(receipts, null, 2) + "\n");
}
function post(data) {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) };
}

if (mode === "status") {
  const receipts = readReceipts();
  const state = await api("/api/workbench/state");
  const byId = new Map(state.runs.map((run) => [run.id, run]));
  const records = receipts.attempts.filter((item) => item.interval === label &&
    (item.campaign || "initial_v1") === campaign).map((item) => ({
    variant: item.variant, run_id: item.run_id,
    status: byId.get(item.run_id)?.status || "missing",
    error: byId.get(item.run_id)?.error || null,
  }));
  console.log(JSON.stringify(records, null, 2));
} else {
  await api("/api/workbench/discover", post({}));
  const state = await api("/api/workbench/state");
  const strategy = state.strategies.find((item) => item.id === plan.strategy_id);
  const dataset = state.datasets.find((item) => item.id === plan.dataset_id);
  if (!strategy || !dataset) throw new Error("Frozen strategy or dataset is unavailable");
  const previews = [];
  for (const variant of selectedVariants) {
    const body = bodyFor(variant);
    const preview = await api("/api/workbench/preview", post(body));
    if (preview.jobs !== 1 || preview.parameters.length !== 1) {
      throw new Error(`Unexpected preview for ${variant.label}: ${JSON.stringify(preview)}`);
    }
    previews.push({ variant: variant.label, jobs: preview.jobs, parameters: preview.parameters[0], warmup: preview.warmup });
    console.log(`Previewed ${label}/${variant.label}: 1 job`);
  }
  const previewPath = join(campaignFolder, `PREVIEW_${campaign}_${label}.json`);
  writeFileSync(previewPath, JSON.stringify({ strategy_file_hash: strategy.file_hash, dataset_id: dataset.id, previews }, null, 2) + "\n");
  if (mode === "launch") {
    const receipts = readReceipts();
    for (const variant of selectedVariants) {
      const prior = receipts.attempts.find((item) => item.interval === label &&
        item.variant === variant.label && (item.campaign || "initial_v1") === campaign && item.run_id);
      if (prior) { console.log(`Already launched ${label}/${variant.label}: ${prior.run_id}`); continue; }
      const runs = await api("/api/workbench/runs", post(bodyFor(variant)));
      if (runs.length !== 1) throw new Error(`Unexpected launch count for ${variant.label}`);
      const run = runs[0];
      receipts.attempts.push({ campaign, interval: label, variant: variant.label, run_id: run.id,
        created_at: run.created_at, source_hash: run.input?.source_hash,
        strategy_file_hash: run.input?.strategy?.file_hash,
        dataset_id: run.input?.dataset?.id });
      save(receipts);
      console.log(`Launched ${label}/${variant.label}: ${run.id}`);
    }
  }
}
