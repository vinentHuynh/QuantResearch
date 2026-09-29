import { readFileSync, writeFileSync, mkdirSync, renameSync } from "node:fs";
import { resolve, join } from "node:path";
import { createHash } from "node:crypto";
import {
  conditionProtocol,
  fitReference,
  normalizedMarks,
  assessCondition,
} from "../src/strategyCondition.ts";

const root = resolve(
  process.env.WORKBENCH_HOME || "data/workbench",
  "collective",
);
const read = (p) => JSON.parse(readFileSync(p, "utf8"));
const hash = (b) => createHash("sha256").update(b).digest("hex");
const catalog = read(join(root, "index.json"));
const items = catalog.items.filter((i) => i.working && !i.benchmark);
const folder = `reports/condition-calibration-${new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-")}`;
mkdirSync(folder, { recursive: true });
// Write before simulation. No threshold or rule is chosen from 2024+ outcomes.
const plan = {
  ...conditionProtocol,
  code: [
    "src/strategyCondition.ts",
    "scripts/calibrate-strategy-condition.mjs",
  ].map((path) => ({ path, checksum: hash(readFileSync(path)) })),
  books: items.map((i) => ({ id: i.id, name: i.name, checksum: i.checksum })),
  blocks: [5, 10, 20],
  paths: 1000,
  horizon: 252,
  target: 0.05,
  upperAcceptance: 0.08,
  trainingSeed: 73001,
  validationSeed: 93113,
  stressSeed: 151121,
  method:
    "Joint circular moving blocks on common observed UTC days; reference-mean uncertainty resampled independently per path. Threshold is maximum 95th percentile across block lengths. Family is the frozen selected books, one 252-observation horizon.",
  limitation:
    "Already selected strategies and inspected history. Conditional bootstrap research, not a prospective probability guarantee; coverage does not extend to different books, indefinite monitoring, or all risk rules.",
  shifts: [0.5, 1],
  shiftStart: 63,
  recoveryStart: 126,
};
writeFileSync(`${folder}/protocol.json`, JSON.stringify(plan, null, 2));
const histories = items.map((i) => {
  const bytes = readFileSync(join(root, i.series_file));
  if (hash(bytes) !== i.checksum) throw Error(`Checksum mismatch: ${i.id}`);
  return JSON.parse(bytes);
});
const refs = histories.map(fitReference);
if (refs.some((r) => !r))
  throw Error(
    "At least one selected book lacks reference evidence; calibration not published.",
  );
const vectors = histories.map(
  (s, i) =>
    new Map(
      normalizedMarks(s, refs[i], plan.calibrationEnd).map((p) => [
        p.date,
        p.value,
      ]),
    ),
);
const dates = [...vectors[0].keys()]
  .filter((d) => vectors.every((v) => v.has(d)))
  .sort();
if (dates.length < 500)
  throw Error(
    "Fewer than 500 shared reference days; calibration not published.",
  );
let rows = dates.map((d) => vectors.map((v) => v.get(d)));
const means = items.map(
  (_, i) => rows.reduce((s, r) => s + r[i], 0) / rows.length,
);
rows = rows.map((r) => r.map((v, i) => v - means[i]));
const rng = (seed) => () => {
  seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
  return seed / 4294967296;
};
const quantile = (a, q) =>
  [...a].sort((x, y) => x - y)[
    Math.min(a.length - 1, Math.ceil(q * a.length) - 1)
  ];
const wilson = (n, total) => {
  const p = n / total,
    z = 1.96;
  return (
    (p +
      (z * z) / (2 * total) +
      z * Math.sqrt((p * (1 - p)) / total + (z * z) / (4 * total * total))) /
    (1 + (z * z) / total)
  );
};
function simulate(
  block,
  seed,
  threshold = Infinity,
  shift = 0,
  recover = false,
  volatility = 1,
) {
  const random = rng(seed),
    maxima = [],
    delays = [],
    recoveryDelays = [];
  let alarms = 0,
    falseRecovery = 0;
  for (let path = 0; path < plan.paths; path++) {
    const drift = items.map(() => 0);
    let index = 0;
    for (let t = 0; t < rows.length; t++) {
      if (t % block === 0) index = Math.floor(random() * rows.length);
      rows[index++ % rows.length].forEach((v, i) => {
        drift[i] += v / rows.length;
      });
    }
    const cusum = items.map(() => 0),
      active = items.map(() => false),
      recent = items.map(() => []);
    let maximum = 0,
      detected = false,
      firstDetection = -1,
      recovered = false;
    for (let t = 0; t < plan.horizon; t++) {
      if (t % block === 0) index = Math.floor(random() * rows.length);
      const row = rows[index++ % rows.length];
      row.forEach((raw, i) => {
        // Stress one book per path, rotate equally; preserve cross-book noise.
        const affected = i === path % items.length;
        const shifted =
          t >= plan.shiftStart && (!recover || t < plan.recoveryStart);
        const value =
          raw * (t >= plan.shiftStart ? volatility : 1) -
          drift[i] -
          (affected && shifted ? shift : 0);
        cusum[i] = Math.max(0, cusum[i] - value - plan.k);
        maximum = Math.max(maximum, cusum[i]);
        if (!active[i] && cusum[i] >= threshold) {
          active[i] = true;
          recent[i] = [];
          if (affected && shifted && !detected) {
            detected = true;
            firstDetection = t;
            delays.push(t - plan.shiftStart + 1);
          }
        } else if (active[i]) {
          recent[i].push(value);
          if (recent[i].length > plan.recoverySessions) recent[i].shift();
          if (
            recent[i].length === plan.recoverySessions &&
            recent[i].reduce((a, b) => a + b, 0) >= 0 &&
            cusum[i] < threshold / 2
          ) {
            active[i] = false;
            if (affected && detected && !recovered) {
              recovered = true;
              if (
                recover &&
                t >= plan.recoveryStart &&
                firstDetection < plan.recoveryStart
              )
                recoveryDelays.push(t - plan.recoveryStart + 1);
              else if (shifted) falseRecovery++;
            }
          }
        }
      });
    }
    maxima.push(maximum);
    if (maximum >= threshold) alarms++;
  }
  return {
    maxima,
    alarms,
    rate: alarms / plan.paths,
    upper: wilson(alarms, plan.paths),
    detected: delays.length,
    detectionRate: delays.length / plan.paths,
    medianDelay: delays.length ? quantile(delays, 0.5) : null,
    recovered: recoveryDelays.length,
    medianRecoveryDelay: recoveryDelays.length
      ? quantile(recoveryDelays, 0.5)
      : null,
    falseRecovery,
  };
}
const training = plan.blocks.map((block) => ({
  block,
  threshold: quantile(simulate(block, plan.trainingSeed + block).maxima, 0.95),
}));
const h = Math.max(...training.map((r) => r.threshold));
const compact = (r) => {
  const { maxima, ...rest } = r;
  return rest;
};
const validation = plan.blocks.map((block) => ({
  block,
  ...compact(simulate(block, plan.validationSeed + block, h)),
}));
const stresses = plan.blocks.flatMap((block) =>
  plan.shifts.map((shift) => ({
    block,
    shift,
    sustained: compact(
      simulate(block, plan.stressSeed + block + shift * 100, h, shift),
    ),
    recovery: compact(
      simulate(block, plan.stressSeed + block + shift * 200, h, shift, true),
    ),
  })),
);
const volatility = plan.blocks.map((block) => ({
  block,
  ...compact(simulate(block, plan.stressSeed + block + 900, h, 0, false, 2)),
}));
const calibration = {
  version: plan.version,
  createdAt: new Date().toISOString(),
  calibrationEnd: plan.calibrationEnd,
  lookback: plan.lookback,
  k: plan.k,
  h,
  recoverySessions: plan.recoverySessions,
  sources: items.map((i) => ({ id: i.id, checksum: i.checksum })),
  books: Object.fromEntries(items.map((i, n) => [i.id, refs[n]])),
  validation: {
    accepted: validation.every((r) => r.upper <= plan.upperAcceptance),
    target: plan.target,
    horizon: plan.horizon,
    paths: plan.paths,
    worstRate: Math.max(...validation.map((r) => r.rate)),
    worstUpper: Math.max(...validation.map((r) => r.upper)),
    residualVolatilityAlarmRate: Math.max(...volatility.map((r) => r.rate)),
    note: plan.limitation,
  },
  report: folder,
};
const snapshots = items.map((i, n) =>
  assessCondition(
    i,
    histories[n],
    i.end,
    calibration,
    catalog.market_data_through?.[i.symbol],
  ),
);
const report = {
  plan,
  commonReference: { count: dates.length, start: dates[0], end: dates.at(-1) },
  training,
  calibration,
  validation,
  stresses,
  volatility,
  snapshots,
};
const bytes = JSON.stringify(report, null, 2);
writeFileSync(`${folder}/evaluation.json`, bytes);
writeFileSync(
  `${folder}/findings.md`,
  [
    "Strategy condition detector — historical development evaluation",
    "",
    `Reference ends ${plan.calibrationEnd}; ${dates.length} common observed UTC days. Frozen ${items.length}-book family. CUSUM k=${plan.k}, h=${h.toFixed(3)}.`,
    "",
    `Independent bootstrap validation: worst family alarm rate ${(calibration.validation.worstRate * 100).toFixed(1)}% over ${plan.horizon} observations; 95% Wilson upper ${(calibration.validation.worstUpper * 100).toFixed(1)}%. Prespecified 8% upper-bound development check ${calibration.validation.accepted ? "passed" : "failed"}. Nominal target 5%.`,
    "",
    "Block | Shift (reference SD/day) | Detection rate | Median delay among detected | False recovery count",
    "--- | --- | --- | --- | ---",
    ...stresses.map(
      (r) =>
        `${r.block} | ${r.shift} | ${(r.sustained.detectionRate * 100).toFixed(1)}% | ${r.sustained.medianDelay ?? "none"} days | ${r.sustained.falseRecovery}`,
    ),
    "",
    `Doubled standardized-residual volatility (not doubled raw market volatility): up to ${(calibration.validation.residualVolatilityAlarmRate * 100).toFixed(1)}% of paths alarmed despite no mean deterioration. The detector cannot separate changed residual variance from a weakening mean. This stress is deliberately outside the fitted null and prevents interpreting a warning as proof of lost edge.`,
    "Delays exclude missed shifts; full missed-detection and recovery results are in evaluation.json. The nominal false-alarm target covers one 252-observation horizon under the fitted null, not the entire multi-year replay. Joint sampling uses common observed reference dates; heterogeneous observation calendars remain a limitation. Structural changes, variance shifts, selection effects and model uncertainty can invalidate the target. Recovery is a descriptive research state and never authorizes entries.",
    "",
    plan.limitation,
    "",
    ...snapshots.map(
      (s) =>
        `- ${s.name}: ${s.condition}; as of ${s.asOf}; last 10 natural trades ${s.last10.pnl.toFixed(2)}, last 20 observed days ${s.last20.pnl.toFixed(2)}; detector through ${s.detector?.through || "unavailable"}.`,
    ),
  ].join("\n"),
);
// Publish only if the source index still matches. Originals and prior reports remain immutable.
const current = read(join(root, "index.json"));
if (
  !items.every((i) =>
    current.items.some((c) => c.id === i.id && c.checksum === i.checksum),
  )
)
  throw Error("Sources changed during evaluation; publication aborted.");
const archive = join(root, `condition-${hash(bytes).slice(0, 16)}.json`);
writeFileSync(archive, bytes, { flag: "wx" });
current.condition_calibration = calibration;
const temporary = join(root, `index-condition-${process.pid}.tmp`);
writeFileSync(temporary, JSON.stringify(current));
renameSync(temporary, join(root, "index.json"));
console.log(
  JSON.stringify(
    {
      folder,
      h,
      validation: calibration.validation,
      snapshots: snapshots.map((s) => ({
        name: s.name,
        condition: s.condition,
        last10: s.last10.pnl,
        last20: s.last20.pnl,
      })),
    },
    null,
    2,
  ),
);
