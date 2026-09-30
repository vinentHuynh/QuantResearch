import type {
  CollectiveItem,
  CollectiveSeries,
  DailyMark,
  Trade,
} from "./portfolio.ts";

// Frozen research protocol. Changing these requires a new calibration.
export const CONDITION_VERSION = "session-cusum-v1";
export const conditionProtocol = {
  version: CONDITION_VERSION,
  calibrationEnd: "2023-12-31",
  lookback: 25,
  minimumReference: 250,
  k: 0.25,
  recoverySessions: 20,
  tradeWindows: [10, 30],
  markedWindow: 20,
} as const;
export type Reference = {
  location: number;
  scale: number;
  floor: number;
  count: number;
  start: string;
  end: string;
  sourceVersion: string | null;
};
export type ConditionCalibration = {
  version: string;
  createdAt: string;
  calibrationEnd: string;
  lookback: number;
  k: number;
  h: number;
  recoverySessions: number;
  sources: { id: string; checksum: string }[];
  books: Record<string, Reference>;
  validation: {
    accepted: boolean;
    target: number;
    horizon: number;
    paths: number;
    worstRate: number;
    worstUpper: number;
    residualVolatilityAlarmRate?: number;
    note: string;
  };
  report: string;
};
const mean = (a: number[]) => a.reduce((s, x) => s + x, 0) / a.length;
const sd = (a: number[]) => {
  if (a.length < 2) return 0;
  const center = mean(a);
  return Math.sqrt(
    a.reduce((s, x) => s + (x - center) ** 2, 0) / (a.length - 1),
  );
};
export type NormalizedMark = { date: string; value: number; segment: string };

// Each denominator uses only preceding marks within the same independent run.
// Terminal accounting marks are retained in reports, excluded from inference.
function lagged(marks: DailyMark[], lookback: number) {
  let previous = "",
    buffer: number[] = [];
  const values: { mark: DailyMark; sigma: number }[] = [];
  for (const mark of [...marks].sort((a, b) => a.date.localeCompare(b.date))) {
    const segment = mark.segment || "unknown";
    if (segment !== previous) buffer = [];
    previous = segment;
    if (!Number.isFinite(mark.pnl)) {
      buffer = [];
      continue;
    }
    if (mark.terminal) {
      buffer = [];
      continue;
    }
    if (buffer.length === lookback) values.push({ mark, sigma: sd(buffer) });
    buffer.push(mark.pnl);
    if (buffer.length > lookback) buffer.shift();
  }
  return values;
}
export function fitReference(series: CollectiveSeries): Reference | null {
  if (series.provenance_version !== 2) return null;
  const versions = new Set(
    series.trades
      .filter((t) => t.exit.slice(0, 10) <= conditionProtocol.calibrationEnd)
      .map((t) => t.source_version)
      .filter((v) => v && v !== "unknown"),
  );
  if (versions.size > 1) return null;
  const points = lagged(
    series.daily.filter((d) => d.date <= conditionProtocol.calibrationEnd),
    conditionProtocol.lookback,
  );
  const positive = points
    .map((p) => p.sigma)
    .filter((x) => x > 0)
    .sort((a, b) => a - b);
  if (positive.length < conditionProtocol.minimumReference) return null;
  const floor = positive[Math.floor(positive.length / 2)] * 0.5;
  const values = points.map((p) => p.mark.pnl / Math.max(floor, p.sigma));
  const scale = sd(values);
  if (!(scale > 0) || !Number.isFinite(scale)) return null;
  return {
    location: mean(values),
    scale,
    floor,
    count: values.length,
    start: points[0].mark.date,
    end: points.at(-1)!.mark.date,
    sourceVersion: [...versions][0] || null,
  };
}
export function normalizedMarks(
  series: CollectiveSeries,
  reference: Reference,
  cutoff: string,
  lookback = 25,
): NormalizedMark[] {
  return lagged(
    series.daily.filter((d) => d.date <= cutoff),
    lookback,
  ).map(({ mark, sigma }) => ({
    date: mark.date,
    segment: mark.segment || "unknown",
    value:
      (mark.pnl / Math.max(reference.floor, sigma) - reference.location) /
      reference.scale,
  }));
}
export function monitor(
  points: NormalizedMark[],
  k: number,
  h: number,
  recoverySessions = 20,
) {
  let cusum = 0,
    ewma = 0,
    alarm = false,
    recovery = false,
    recoveryAge = 0,
    segmentCount = 0,
    segment = "",
    sinceAlarm: number[] = [];
  const events: {
    date: string;
    kind: "weakness" | "recovery" | "new segment";
  }[] = [];
  for (const p of points) {
    if (segment && p.segment !== segment) {
      cusum = 0;
      ewma = 0;
      alarm = false;
      recovery = false;
      sinceAlarm = [];
      segmentCount = 0;
      events.push({ date: p.date, kind: "new segment" });
    }
    segment = p.segment;
    segmentCount++;
    if (recovery && ++recoveryAge >= recoverySessions) recovery = false;
    cusum = Math.max(0, cusum - p.value - k);
    ewma = 0.1 * p.value + 0.9 * ewma;
    if (!alarm && cusum >= h) {
      alarm = true;
      recovery = false;
      sinceAlarm = [];
      events.push({ date: p.date, kind: "weakness" });
    } else if (alarm) {
      sinceAlarm.push(p.value);
      if (sinceAlarm.length > recoverySessions) sinceAlarm.shift();
      if (
        sinceAlarm.length === recoverySessions &&
        mean(sinceAlarm) >= 0 &&
        cusum < h * 0.5
      ) {
        alarm = false;
        recovery = true;
        recoveryAge = 0;
        events.push({ date: p.date, kind: "recovery" });
      }
    }
  }
  return {
    cusum,
    ewma,
    alarm,
    recovery,
    events,
    count: points.length,
    segmentCount,
    segment,
    through: points.at(-1)?.date || null,
  };
}
function windowSummary(
  rows: { date: string; pnl: number }[],
  requested: number,
) {
  const window = rows.slice(-requested);
  return {
    requested,
    count: window.length,
    pnl: window.reduce((s, t) => s + t.pnl, 0),
    start: window[0]?.date || null,
    end: window.at(-1)?.date || null,
  };
}
export function assessCondition(
  item: CollectiveItem,
  series: CollectiveSeries | undefined,
  requested: string,
  calibration?: ConditionCalibration,
  marketThrough?: string,
) {
  const coverage = [...(series?.coverage || [])].sort((a, b) =>
    a.start.localeCompare(b.start),
  );
  const segment = coverage.find(
    (c) => c.start <= requested && requested <= c.end,
  );
  const prior = coverage.filter((c) => c.end <= requested).at(-1);
  const asOf = segment ? requested : prior?.end || null;
  const marks = [...(series?.daily || [])]
    .filter((d) => asOf && d.date <= asOf)
    .sort((a, b) => a.date.localeCompare(b.date));
  const closed = [...(series?.trades || [])]
    .filter((t) => asOf && t.exit.slice(0, 10) <= asOf)
    .sort((a, b) => a.exit.localeCompare(b.exit));
  const natural = closed.filter((t) => t.synthetic_exit === false);
  const unknown = closed.filter((t) => t.synthetic_exit === undefined).length;
  const trades = natural.map((t) => ({
    date: t.exit.slice(0, 10),
    pnl: t.pnl,
  }));
  const last10 = windowSummary(trades, 10),
    last30 = windowSummary(trades, 30),
    last20 = windowSummary(marks, 20);
  let streak = 0;
  for (let i = natural.length - 1; i >= 0 && natural[i].pnl < 0; i--) streak++;
  let equity = 0,
    peak = 0,
    peakDate = marks[0]?.date || null;
  for (const m of marks) {
    equity += m.pnl;
    if (equity >= peak) {
      peak = equity;
      peakDate = m.date;
    }
  }
  const drawdown = peak - equity;
  const underwaterDays =
    drawdown > 0 && peakDate && last20.end
      ? Math.round((Date.parse(last20.end) - Date.parse(peakDate)) / 86400000)
      : 0;
  const reference = calibration?.books[item.id];
  const versionChanged =
    !!reference?.sourceVersion &&
    closed.some(
      (t) =>
        t.source_version &&
        t.source_version !== "unknown" &&
        t.source_version !== reference.sourceVersion,
    );
  const verified =
    calibration?.version === CONDITION_VERSION &&
    calibration.calibrationEnd === conditionProtocol.calibrationEnd &&
    calibration.sources.some(
      (s) => s.id === item.id && s.checksum === item.checksum,
    ) &&
    calibration.lookback === conditionProtocol.lookback &&
    calibration.k === conditionProtocol.k &&
    Number.isFinite(calibration.h) &&
    calibration.h > 0 &&
    reference &&
    reference.scale > 0 &&
    reference.floor > 0;
  const ready = !!(
    verified &&
    !versionChanged &&
    series?.provenance_version === 2 &&
    asOf &&
    asOf > calibration!.calibrationEnd
  );
  const detector = ready
    ? monitor(
        normalizedMarks(
          series!,
          reference!,
          asOf!,
          calibration!.lookback,
        ).filter((p) => p.date > calibration!.calibrationEnd),
        calibration!.k,
        calibration!.h,
        calibration!.recoverySessions,
      )
    : null;
  const recentLosses =
    (last10.count === 10 && last10.pnl < 0) ||
    (last20.count === 20 && last20.pnl < 0);
  const calibrated = !!(
    ready &&
    calibration!.validation.accepted &&
    detector &&
    detector.segmentCount >= 20 &&
    detector.segment === marks.at(-1)?.segment
  );
  const condition = !marks.length
    ? "Insufficient evidence"
    : calibrated && detector!.alarm
      ? "Unusual weakness"
      : calibrated && detector!.recovery
        ? "Recovery developing"
        : recentLosses
          ? "Watch — recent losses"
          : !calibrated
            ? "Insufficient evidence"
            : "Within reference range";
  const available = !!segment && marks.length > 0;
  const explanation = !marks.length
    ? "No replay observations at this cutoff."
    : detector?.alarm && calibrated
      ? "The research CUSUM crossed its reference threshold. This does not establish negative future expectancy."
      : detector?.recovery && calibrated
        ? "At least 20 new observed days recovered toward the reference after a warning. Entry permission is separate."
        : recentLosses
          ? `Losses in ${[last10.count === 10 && last10.pnl < 0 ? "the last 10 natural trades" : "", last20.count === 20 && last20.pnl < 0 ? "the last 20 observed days" : ""].filter(Boolean).join(" and ")}. This is descriptive, not a forecast.`
          : calibrated
            ? "No calibrated CUSUM warning at this cutoff; losses can still occur."
            : "No matching, sufficiently supported detector calibration. The dated P&L remains descriptive.";
  const exposure = (rows: DailyMark[], ledger: Trade[]) =>
    rows.filter((d) =>
      ledger.some(
        (t) => t.entry.slice(0, 10) <= d.date && t.exit.slice(0, 10) >= d.date,
      ),
    ).length;
  return {
    id: item.id,
    name: `${item.symbol} ${item.name} ${item.timeframe}`,
    checksum: item.checksum,
    requested,
    asOf,
    available,
    condition,
    explanation,
    availability: available
      ? "Replay covers requested date"
      : `Status unavailable at requested date${asOf ? ` — historical snapshot through ${asOf}` : ""}`,
    simulationThrough: coverage.at(-1)?.end || null,
    latestMark: marks.at(-1)?.date || null,
    marketThrough: marketThrough || null,
    lastNaturalExit: natural.at(-1)?.exit || null,
    last10,
    last30,
    last20,
    exposedDays: exposure(
      marks.slice(-20),
      closed.concat(
        (series?.trades || []).filter(
          (t) =>
            asOf && t.entry.slice(0, 10) <= asOf && t.exit.slice(0, 10) > asOf,
        ),
      ),
    ),
    lossStreak: unknown ? null : streak,
    excludedSynthetic: closed.filter((t) => t.synthetic_exit === true).length,
    unknownExits: unknown,
    inferredExits: closed.filter(
      (t) => t.exit_provenance === "legacy-worker-timing",
    ).length,
    drawdown,
    peakDate,
    underwaterDays,
    equityStart: marks[0]?.date || null,
    detector,
    calibrated,
    reference: ready ? reference : null,
    threshold: ready ? calibration!.h : null,
    // A selected strategy set and inspected history are not prospective validation.
    evidence:
      "Historical development research; no untouched holdout or live validation.",
    versionChanged,
  };
}
