import type {
  CollectiveItem,
  CollectiveSeries,
  DailyMark,
  GatePolicy,
  GateReplay,
  GateState,
  Trade,
} from "./portfolio.ts";

export type SizingSettings = {
  calibrationEnd: string;
  estimator: "legacy" | "session" | "ewma";
  fixedSize: number;
  floorFraction: number;
  maxChange: number;
  portfolioVolLimit: number;
  equityVolLimit: number;
  lossLimit: number;
  monitorWindow: number;
  monitorConfirm: number;
  monitorThreshold: number;
  wholeContracts: boolean;
  marginPerContract: number;
  marginBudget: number;
};

export const defaultSizing: SizingSettings = {
  calibrationEnd: "2023-12-31",
  estimator: "ewma",
  fixedSize: 0.75,
  floorFraction: 0.5,
  maxChange: 0.25,
  portfolioVolLimit: 0,
  equityVolLimit: 0,
  lossLimit: 0,
  monitorWindow: 30,
  monitorConfirm: 5,
  monitorThreshold: 2,
  wholeContracts: false,
  marginPerContract: 0,
  marginBudget: 0,
};

export const sizingSettings = (policy: GatePolicy): SizingSettings => ({
  ...defaultSizing,
  ...policy.sizing,
});
const average = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
const deviation = (xs: number[]) => {
  if (xs.length < 2) return NaN;
  const mean = average(xs);
  return Math.sqrt(
    xs.reduce((s, x) => s + (x - mean) ** 2, 0) / (xs.length - 1),
  );
};
const median = (xs: number[]) => {
  const sorted = [...xs].sort((a, b) => a - b);
  return sorted.length ? sorted[Math.floor(sorted.length / 2)] : NaN;
};
const band = (weight: number): GateState =>
  weight === 0
    ? "Paused"
    : weight < 1
      ? "Reduced"
      : weight > 1
        ? "Raised"
        : "Active";
const isDate = (value: string) =>
  /^\d{4}-\d{2}-\d{2}$/.test(value) &&
  Number.isFinite(Date.parse(value)) &&
  new Date(value).toISOString().slice(0, 10) === value;

export function validateSizing(policy: GatePolicy, start: string) {
  const s = sizingSettings(policy);
  if (!isDate(s.calibrationEnd))
    throw new Error("Choose a valid frozen calibration end date.");
  const calibrated =
    s.portfolioVolLimit > 0 ||
    s.equityVolLimit > 0 ||
    s.lossLimit > 0 ||
    policy.mode === "portfolio" ||
    policy.mode === "deterioration" ||
    (policy.mode === "volatility" &&
      policy.sizing?.estimator !== "legacy" &&
      policy.sizing);
  if (calibrated && s.calibrationEnd >= start)
    throw new Error(
      "The reporting period must start after the frozen calibration end date.",
    );
  if (!["legacy", "session", "ewma"].includes(s.estimator))
    throw new Error("Choose a valid volatility estimator.");
  for (const [name, min, max] of [
    ["fixedSize", 0, 4],
    ["floorFraction", 0.01, 1],
    ["maxChange", 0.01, 4],
    ["portfolioVolLimit", 0, 1e9],
    ["equityVolLimit", 0, 1e9],
    ["lossLimit", 0, 1e9],
    ["monitorWindow", 20, 250],
    ["monitorConfirm", 2, 50],
    ["monitorThreshold", 1, 10],
    ["marginPerContract", 0, 1e9],
    ["marginBudget", 0, 1e12],
  ] as const) {
    const value = s[name];
    if (!Number.isFinite(value) || value < min || value > max)
      throw new Error(`Invalid sizing setting: ${name}.`);
  }
  if (!Number.isInteger(s.monitorWindow) || !Number.isInteger(s.monitorConfirm))
    throw new Error(
      "Monitoring windows and confirmations must be whole numbers.",
    );
  if (s.marginBudget > 0 && (!s.wholeContracts || !s.marginPerContract))
    throw new Error(
      "A margin budget requires whole-contract sizing and an explicit margin per contract assumption.",
    );
}

// Observed daily marks, including zeros. Missing dates are never synthesized.
// Everything used for an entry is dated strictly before that entry's UTC date.
export function volatilityModel(daily: DailyMark[], policy: GatePolicy) {
  const settings = sizingSettings(policy);
  const marks = [...daily].sort((a, b) => a.date.localeCompare(b.date));
  const cache = new Map<string, number>();
  function sigma(date: string) {
    if (cache.has(date)) return cache.get(date)!;
    let lo = 0,
      hi = marks.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (marks[mid].date < date) lo = mid + 1;
      else hi = mid;
    }
    const xs = marks
      .slice(Math.max(0, lo - policy.volLookback), lo)
      .map((p) => p.pnl);
    let value = NaN;
    if (xs.length >= policy.volLookback) {
      if (settings.estimator === "ewma") {
        const decay = 1 - 2 / (policy.volLookback + 1);
        const ws = xs.map((_, i) => decay ** (xs.length - i - 1));
        const sum = ws.reduce((a, b) => a + b, 0);
        const mean = xs.reduce((a, x, i) => a + ws[i] * x, 0) / sum;
        const denominator = sum - ws.reduce((a, w) => a + w * w, 0) / sum;
        value = Math.sqrt(
          xs.reduce((a, x, i) => a + ws[i] * (x - mean) ** 2, 0) / denominator,
        );
      } else value = deviation(xs);
    }
    cache.set(date, value);
    return value;
  }
  const estimates = marks
    .filter((p) => p.date <= settings.calibrationEnd)
    .map((p) => sigma(p.date))
    .filter((x) => Number.isFinite(x) && x > 0);
  const target = estimates.length >= 20 ? median(estimates) : NaN;
  return { sigma, target, observations: estimates.length };
}

export function replaySizing(
  trades: Trade[],
  policy: GatePolicy,
  end: string,
  daily: DailyMark[],
  start: string,
): GateReplay {
  validateSizing(policy, start);
  const settings = sizingSettings(policy);
  const model = volatilityModel(daily, policy);
  if (policy.mode !== "fixed" && !Number.isFinite(model.target))
    throw new Error(
      "Sizing needs at least 20 valid volatility estimates before the frozen calibration end. Extend calibration history.",
    );
  const weights = new Map<number, number>(),
    accepted = new Set<number>();
  const events: GateReplay["events"] = [];
  let previous = 1,
    state: GateState = "Active";
  for (const { t, index } of trades
    .map((t, index) => ({ t, index }))
    .sort((a, b) => Date.parse(a.t.entry) - Date.parse(b.t.entry))) {
    if (t.entry.slice(0, 10) > end) break;
    let weight = 1;
    if (policy.mode === "fixed") weight = settings.fixedSize;
    else if (t.entry.slice(0, 10) > settings.calibrationEnd) {
      const sigma = model.sigma(t.entry.slice(0, 10));
      if (!Number.isFinite(sigma))
        throw new Error(
          "Insufficient observed daily marks before a sized entry.",
        );
      const desired = Math.min(
        policy.volCap,
        model.target / Math.max(sigma, model.target * settings.floorFraction),
      );
      weight = Math.min(
        policy.volCap,
        Math.max(
          previous - settings.maxChange,
          Math.min(previous + settings.maxChange, desired),
        ),
      );
      previous = weight;
    }
    weights.set(index, weight);
    if (weight > 0) accepted.add(index);
    const next = band(weight);
    if (next !== state)
      events.push({
        timestamp: t.entry,
        state: next,
        reason: `Entry size ×${weight.toFixed(3)}; ${policy.mode === "fixed" ? "constant exposure" : `calibration frozen at ${settings.calibrationEnd}`}`,
      });
    state = next;
  }
  return { weights, accepted, events, state };
}

// A sustained mean shortfall is a review trigger, not a calibrated probability.
// The scale at each trade's ENTRY is used even when the trade closes much later.
export function replayDeterioration(
  trades: Trade[],
  policy: GatePolicy,
  end: string,
  daily: DailyMark[],
  start: string,
  manual: { timestamp: string; action: "pause" | "resume"; reason: string }[],
): GateReplay {
  validateSizing(policy, start);
  const s = sizingSettings(policy),
    model = volatilityModel(daily, policy);
  if (!Number.isFinite(model.target))
    throw new Error(
      "Deterioration monitoring needs sufficient pre-calibration volatility history.",
    );
  const normalized = (t: Trade) => {
    const sigma = model.sigma(t.entry.slice(0, 10));
    return Number.isFinite(sigma)
      ? t.pnl / Math.max(model.target * s.floorFraction, sigma)
      : NaN;
  };
  const reference = trades
    .filter((t) => t.synthetic_exit !== true && t.exit.slice(0, 10) <= s.calibrationEnd)
    .map(normalized)
    .filter(Number.isFinite);
  if (reference.length < 50 || !(deviation(reference) > 0))
    throw new Error(
      "Deterioration monitoring needs at least 50 normalized calibration trades with nonzero variation.",
    );
  const mean = average(reference),
    sd = deviation(reference);
  const entries = trades
    .map((t, index) => ({ ...t, index }))
    .sort((a, b) => Date.parse(a.entry) - Date.parse(b.entry));
  const exits = [...entries].sort(
    (a, b) => Date.parse(a.exit) - Date.parse(b.exit),
  );
  const controls = [...manual].sort(
    (a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp),
  );
  const weights = new Map<number, number>(),
    accepted = new Set<number>(),
    events: GateReplay["events"] = [];
  let cursor = 0,
    control = 0,
    paused = false,
    confirmations = 0;
  const recent: number[] = [];
  function observe(before: number) {
    while (cursor < exits.length || control < controls.length) {
      const exit = exits[cursor],
        decision = controls[control];
      const exitTime = exit ? Date.parse(exit.exit) : Infinity;
      const decisionTime = decision ? Date.parse(decision.timestamp) : Infinity;
      if (decisionTime <= before && decisionTime <= exitTime) {
        control++;
        paused = decision.action === "pause";
        recent.length = 0;
        confirmations = 0;
        events.push({
          timestamp: decision.timestamp,
          state: paused ? "Paused" : "Active",
          reason: `Manual ${decision.action}: ${decision.reason}`,
        });
      } else if (exitTime < before) {
        cursor++;
        if (exit.synthetic_exit === true || exit.exit.slice(0, 10) <= s.calibrationEnd) continue;
        const value = normalized(exit);
        if (!Number.isFinite(value)) continue;
        recent.push(value);
        if (recent.length > s.monitorWindow) recent.shift();
        if (recent.length < s.monitorWindow || paused) continue;
        const shortfall =
          (mean - average(recent)) / (sd / Math.sqrt(s.monitorWindow));
        confirmations = shortfall >= s.monitorThreshold ? confirmations + 1 : 0;
        if (confirmations >= s.monitorConfirm) {
          paused = true;
          events.push({
            timestamp: exit.exit,
            state: "Paused",
            reason: `Normalized outcome shortfall persisted for ${confirmations} observations; dated manual review/resume required`,
          });
        }
      } else break;
    }
  }
  for (const t of entries) {
    if (t.entry.slice(0, 10) > end) break;
    observe(Date.parse(t.entry));
    if (!paused) {
      accepted.add(t.index);
      weights.set(t.index, 1);
    }
  }
  observe(Date.parse(end + "T23:59:59.999Z"));
  return {
    accepted,
    weights,
    events,
    state: paused ? "Paused" : "Active",
    status: {
      reason: paused
        ? "Deterioration review: dated manual resume required"
        : "Monitoring normalized outcomes",
      cooldownUntil: null,
      recoveryTrades: 0,
      recoveryPnl: 0,
      required: 0,
    },
  };
}

export type CorrelationRow = {
  a: string;
  b: string;
  observations: number;
  correlation: number | null;
};
export function correlationRows(
  items: CollectiveItem[],
  series: CollectiveSeries[],
  end: string,
  lookback?: number,
): CorrelationRow[] {
  const maps = new Map(
    series.map((s) => [
      s.id,
      new Map(s.daily.filter((p) => p.date <= end).map((p) => [p.date, p.pnl])),
    ]),
  );
  const rows: CorrelationRow[] = [];
  for (let i = 0; i < items.length; i++)
    for (let j = i + 1; j < items.length; j++) {
      const a = maps.get(items[i].id)!,
        b = maps.get(items[j].id)!;
      let dates = [...a.keys()].filter((d) => b.has(d)).sort();
      if (lookback) dates = dates.slice(-lookback);
      const x = dates.map((d) => a.get(d)!),
        y = dates.map((d) => b.get(d)!);
      const xm = average(x),
        ym = average(y),
        xs = deviation(x),
        ys = deviation(y);
      rows.push({
        a: items[i].id,
        b: items[j].id,
        observations: dates.length,
        correlation:
          dates.length >= 20 && xs > 0 && ys > 0
            ? x.reduce((n, v, k) => n + (v - xm) * (y[k] - ym), 0) /
              ((dates.length - 1) * xs * ys)
            : null,
      });
    }
  return rows;
}

// Conservative gross covariance proxy, not margin or a marked open-position loss.
// Negative sample correlations receive no hedge credit. Existing positions retain size.
export function applyPortfolioControls(
  items: CollectiveItem[],
  series: CollectiveSeries[],
  copies: Record<string, number>,
  replays: Map<string, GateReplay>,
  policy: GatePolicy,
  end: string,
) {
  const s = sizingSettings(policy);
  const enabled =
    policy.mode === "portfolio" ||
    s.portfolioVolLimit > 0 ||
    s.equityVolLimit > 0 ||
    s.lossLimit > 0 ||
    s.wholeContracts;
  if (!enabled) return;
  const data = new Map(series.map((x) => [x.id, x]));
  const models = new Map(
    items.map((i) => [i.id, volatilityModel(data.get(i.id)!.daily, policy)]),
  );
  const needsVol =
    policy.mode === "portfolio" ||
    s.portfolioVolLimit > 0 ||
    s.equityVolLimit > 0;
  const calibrationCorrelations = correlationRows(
    items,
    series,
    s.calibrationEnd,
  );
  const equity = new Set(
    items
      .filter((i) => /^(M?ES|M?NQ|M?YM|M?2K|RTY)$/.test(i.symbol))
      .map((i) => i.id),
  );
  const entries = items
    .flatMap((i) =>
      data.get(i.id)!.trades.map((t, index) => ({ ...t, index, id: i.id })),
    )
    .sort(
      (a, b) =>
        Date.parse(a.entry) - Date.parse(b.entry) ||
        a.id.localeCompare(b.id) ||
        a.index - b.index,
    );
  type Position = (typeof entries)[number] & {
    weight: number;
    quantity: number;
  };
  const open: Position[] = [];
  const originalStates = new Map(
    [...replays].map(([id, replay]) => [id, replay.state]),
  );
  let realized = 0,
    peak = 0,
    stopped = false;
  function settle(before: number) {
    const exits = open
      .filter((p) => Date.parse(p.exit) < before)
      .sort((a, b) => Date.parse(a.exit) - Date.parse(b.exit));
    for (let x = 0; x < exits.length;) {
      let z = x + 1;
      while (
        z < exits.length &&
        Date.parse(exits[z].exit) === Date.parse(exits[x].exit)
      )
        z++;
      if (exits[x].exit.slice(0, 10) > s.calibrationEnd) {
        realized += exits
          .slice(x, z)
          .reduce((n, p) => n + p.pnl * p.weight * copies[p.id], 0);
        peak = Math.max(peak, realized);
        if (!stopped && s.lossLimit > 0 && peak - realized >= s.lossLimit) {
          stopped = true;
          for (const replay of replays.values())
            replay.events.push({
              timestamp: exits[x].exit,
              state: "Paused",
              reason: `Portfolio closed drawdown breached $${s.lossLimit}; entries remain blocked for this replay`,
            });
        }
      }
      x = z;
    }
    for (let n = open.length - 1; n >= 0; n--)
      if (Date.parse(open[n].exit) < before) open.splice(n, 1);
  }
  const currentCorrelation = new Map<string, CorrelationRow[]>();
  function correlations(date: string) {
    if (!currentCorrelation.has(date)) {
      const before = new Date(Date.parse(date) - 86400000)
        .toISOString()
        .slice(0, 10);
      currentCorrelation.set(
        date,
        correlationRows(items, series, before, policy.volLookback),
      );
    }
    return currentCorrelation.get(date)!;
  }
  function risk(
    exposure: Map<string, number>,
    date?: string,
    onlyEquity = false,
  ) {
    let variance = 0;
    const rows = date ? correlations(date) : calibrationCorrelations;
    const sigmas = items.map((i) => {
      const model = models.get(i.id)!;
      if (!Number.isFinite(model.target))
        throw new Error(
          `Insufficient frozen risk calibration for ${i.name} / ${i.symbol}.`,
        );
      const sigma = date ? model.sigma(date) : model.target;
      if (!Number.isFinite(sigma))
        throw new Error(
          `Insufficient daily marks for portfolio risk: ${i.name}.`,
        );
      return (
        (onlyEquity && !equity.has(i.id) ? 0 : exposure.get(i.id) || 0) *
        Math.max(sigma, model.target * s.floorFraction)
      );
    });
    for (let i = 0; i < items.length; i++) {
      variance += sigmas[i] ** 2;
      for (let j = i + 1; j < items.length; j++) {
        const row = rows.find(
          (r) => r.a === items[i].id && r.b === items[j].id,
        );
        // Shrink toward full positive correlation to avoid optimistic hedge credit.
        const rho =
          row?.correlation == null
            ? 1
            : 0.5 + 0.5 * Math.max(0, Math.min(1, row.correlation));
        variance += 2 * sigmas[i] * sigmas[j] * rho;
      }
    }
    return Math.sqrt(variance);
  }
  const target = needsVol
    ? s.portfolioVolLimit ||
      risk(new Map(items.map((i) => [i.id, copies[i.id]])))
    : Infinity;
  for (let k = 0; k < entries.length;) {
    const first = entries[k],
      time = Date.parse(first.entry),
      date = first.entry.slice(0, 10);
    if (date > end) break;
    // All equal-timestamp entries share a budget; input ordering gives no priority.
    let stop = k + 1;
    while (stop < entries.length && Date.parse(entries[stop].entry) === time)
      stop++;
    settle(time);
    const group = entries
      .slice(k, stop)
      .filter((t) => replays.get(t.id)!.accepted.has(t.index));
    if (!group.length) {
      k = stop;
      continue;
    }
    const exposure = new Map<string, number>();
    for (const p of open)
      exposure.set(p.id, (exposure.get(p.id) || 0) + p.weight * copies[p.id]);
    const requested = group.map(
      (t) => replays.get(t.id)!.weights.get(t.index) ?? 1,
    );
    const within = (factor: number) => {
      const candidate = new Map(exposure);
      group.forEach((t, n) =>
        candidate.set(
          t.id,
          (candidate.get(t.id) || 0) + requested[n] * copies[t.id] * factor,
        ),
      );
      return (
        (!needsVol || risk(candidate, date) <= target + 1e-8) &&
        (!s.equityVolLimit ||
          risk(candidate, date, true) <= s.equityVolLimit + 1e-8)
      );
    };
    let factor = stopped ? 0 : 1;
    if (!stopped && needsVol && date > s.calibrationEnd && !within(1)) {
      let low = 0,
        high = 1;
      for (let n = 0; n < 36; n++) {
        const mid = (low + high) / 2;
        if (within(mid)) low = mid;
        else high = mid;
      }
      factor = low;
    }
    if (s.wholeContracts)
      for (const t of group)
        if (!Number.isInteger(t.quantity) || !(t.quantity! > 0))
          throw new Error(
            "Whole-contract replay requires recorded quantities. Refresh evidence to import quantities; unavailable ledgers cannot be rounded safely.",
          );
    const availableMargin = Math.max(
      0,
      s.marginBudget -
        open.reduce((n, p) => n + p.quantity * s.marginPerContract, 0),
    );
    const desiredMargin = group.reduce(
      (n, t, i) =>
        n +
        (t.quantity || 0) *
          copies[t.id] *
          requested[i] *
          factor *
          s.marginPerContract,
      0,
    );
    if (s.marginBudget && desiredMargin > availableMargin)
      factor *= availableMargin / desiredMargin;
    group.forEach((t, n) => {
      const replay = replays.get(t.id)!;
      let weight = requested[n] * factor;
      const quantity = s.wholeContracts
        ? Math.floor(t.quantity! * copies[t.id] * weight + 1e-10)
        : 0;
      if (s.wholeContracts) weight = quantity / (t.quantity! * copies[t.id]);
      if (weight < 1e-9) weight = 0;
      replay.weights.set(t.index, weight);
      if (!weight) replay.accepted.delete(t.index);
      if (Math.abs(weight - requested[n]) > 1e-8)
        replay.events.push({
          timestamp: t.entry,
          state: band(weight),
          reason: stopped
            ? "Portfolio closed-loss limit breached; new entries remain blocked for this replay"
            : `Portfolio risk / contract / margin cap: entry size ×${weight.toFixed(3)}`,
        });
      if (weight) open.push({ ...t, weight, quantity });
      replay.state = stopped ? "Paused" : band(weight);
      if (stopped)
        replay.status = {
          reason: "Portfolio closed-loss limit breached; review required",
          cooldownUntil: null,
          recoveryTrades: 0,
          recoveryPnl: 0,
          required: 0,
        };
    });
    k = stop;
  }
  settle(Date.parse(end + "T23:59:59.999Z") + 1);
  for (const [id, replay] of replays) {
    if (originalStates.get(id) === "Paused") replay.state = "Paused";
    if (stopped) {
      replay.state = "Paused";
      replay.status = {
        reason: "Portfolio closed-loss limit breached; review required",
        cooldownUntil: null,
        recoveryTrades: 0,
        recoveryPnl: 0,
        required: 0,
      };
    }
  }
}

export function summarizeDaily(values: number[]) {
  let net = 0,
    peak = 0,
    drawdown = 0;
  for (const x of values) {
    net += x;
    peak = Math.max(peak, net);
    drawdown = Math.max(drawdown, peak - net);
  }
  return {
    net,
    drawdown,
    worstDay: Math.min(0, ...values),
    recovery: drawdown ? net / drawdown : null,
  };
}
