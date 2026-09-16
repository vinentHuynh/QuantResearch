export type Coverage = { start: string; end: string };
export type CollectiveItem = {
  id: string;
  key: string;
  name: string;
  symbol: string;
  timeframe: string;
  session: string;
  source: string;
  start: string;
  end: string;
  capital: number;
  working: boolean;
  feasible: boolean;
  tested: boolean;
  benchmark: boolean;
  reasons: string[];
  parameters: Record<string, unknown>;
  net_pnl: number;
  recent_pnl: number;
  trades: number;
  coverage: Coverage[];
  series_file: string;
  checksum: string;
};
export type CollectiveCatalog = {
  version: number;
  generated_at: string;
  items: CollectiveItem[];
  errors: { key: string; error: string }[];
  definitions: { working: string; feasible: string; pnl: string };
};
export type Trade = { entry: string; exit: string; pnl: number };
export type DailyMark = { date: string; pnl: number };
export type CollectiveSeries = {
  id: string;
  daily: DailyMark[];
  trades: Trade[];
  coverage: Coverage[];
};
export type GatePolicy = {
  enabled: boolean;
  mode: "rolling" | "streak" | "drawdown" | "volatility";
  lookback: number;
  lossLimit: number;
  streak: number;
  drawdown: number;
  cooldown: number;
  recovery: number;
  volLookback: number;
  volCap: number;
};
export const defaultPolicy: GatePolicy = {
  enabled: false,
  mode: "rolling",
  lookback: 10,
  lossLimit: 0,
  streak: 3,
  drawdown: 5000,
  cooldown: 5,
  recovery: 3,
  volLookback: 25,
  volCap: 2,
};
export type GateState = "Paused" | "Active" | "Reduced" | "Raised";
export type GateEvent = {
  timestamp: string;
  state: GateState;
  reason: string;
};
export type GateReplay = {
  accepted: Set<number>;
  weights: Map<number, number>;
  events: GateEvent[];
  state: GateState;
};

// Closed shadow outcomes only. Equal-timestamp exits are unavailable at entry.
// Rejected trades still feed shadow recovery; existing trades are never liquidated.
// The volatility mode never pauses: it sizes each entry from the book's own
// marked P&L volatility known before that entry (see replayVolatility).
export function replayGate(
  trades: Trade[],
  policy: GatePolicy,
  end: string,
  daily: DailyMark[] = [],
  start = "",
): GateReplay {
  if (policy.enabled && policy.mode === "volatility")
    return replayVolatility(trades, policy, end, daily, start);
  const cutoff = Date.parse(end + "T23:59:59.999Z");
  const entries = trades
    .map((t, i) => ({ ...t, index: i }))
    .sort((a, b) => Date.parse(a.entry) - Date.parse(b.entry));
  const exits = [...entries].sort(
    (a, b) => Date.parse(a.exit) - Date.parse(b.exit),
  );
  const accepted = new Set<number>();
  const weights = new Map<number, number>();
  const events: GateEvent[] = [];
  let cursor = 0,
    paused = false,
    until = 0,
    equity = 0,
    peak = 0,
    consecutive = 0;
  const recent: number[] = [];
  function observe(before: number) {
    while (cursor < exits.length && Date.parse(exits[cursor].exit) < before) {
      const t = exits[cursor++],
        time = Date.parse(t.exit);
      recent.push(t.pnl);
      equity += t.pnl;
      peak = Math.max(peak, equity);
      consecutive = t.pnl < 0 ? consecutive + 1 : 0;
      if (!policy.enabled) continue;
      if (paused) {
        if (
          time >= until &&
          recent.length >= policy.recovery &&
          recent.slice(-policy.recovery).reduce((a, b) => a + b, 0) > 0
        ) {
          paused = false;
          peak = equity;
          consecutive = 0;
          // Recovery establishes a new observation segment, preventing immediate
          // re-pausing on the same losses that caused the previous pause.
          recent.length = 0;
          events.push({
            timestamp: t.exit,
            state: "Active",
            reason: "Cooldown complete and shadow recovery is positive",
          });
        }
      } else {
        const rolling =
          recent.length >= policy.lookback &&
          recent.slice(-policy.lookback).reduce((a, b) => a + b, 0) <
            -policy.lossLimit;
        const breach =
          policy.mode === "rolling"
            ? rolling
            : policy.mode === "streak"
              ? consecutive >= policy.streak
              : peak - equity >= policy.drawdown;
        if (breach) {
          paused = true;
          until = time + policy.cooldown * 86400000;
          events.push({
            timestamp: t.exit,
            state: "Paused",
            reason:
              policy.mode === "rolling"
                ? `Last ${policy.lookback} shadow trades lost more than $${policy.lossLimit}`
                : policy.mode === "streak"
                  ? `${policy.streak} consecutive shadow losses`
                  : `Shadow drawdown reached $${policy.drawdown}`,
          });
        }
      }
    }
  }
  for (const t of entries) {
    const time = Date.parse(t.entry);
    if (time > cutoff) break;
    observe(time);
    if (!paused) accepted.add(t.index);
  }
  observe(cutoff + 1);
  return { accepted, weights, events, state: paused ? "Paused" : "Active" };
}

// Volatility scaling (Carver; Harvey et al. 2018): size = target ÷ recent
// volatility, fixed at entry. Volatility is the standard deviation of the
// book's last `volLookback` non-zero marked daily P&L values dated strictly
// before the entry date. The target is the median of that estimate over
// entries dated before the reporting window, so no window data sets it.
function replayVolatility(
  trades: Trade[],
  policy: GatePolicy,
  end: string,
  daily: DailyMark[],
  start: string,
): GateReplay {
  const cutoff = Date.parse(end + "T23:59:59.999Z");
  const lookback = Math.max(10, Math.round(policy.volLookback));
  const cap = Math.max(0.25, policy.volCap);
  const positioned = daily
    .filter((p) => p.pnl !== 0)
    .sort((a, b) => a.date.localeCompare(b.date));
  const sigmaBefore = (date: string) => {
    let lo = 0,
      hi = positioned.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (positioned[mid].date < date) lo = mid + 1;
      else hi = mid;
    }
    const window = positioned.slice(Math.max(0, lo - lookback), lo);
    if (window.length < 10) return NaN;
    const mean = window.reduce((a, p) => a + p.pnl, 0) / window.length;
    return Math.sqrt(
      window.reduce((a, p) => a + (p.pnl - mean) ** 2, 0) /
        (window.length - 1),
    );
  };
  const entries = trades
    .map((t, i) => ({ ...t, index: i, sigma: sigmaBefore(t.entry.slice(0, 10)) }))
    .sort((a, b) => Date.parse(a.entry) - Date.parse(b.entry));
  const prior = entries
    .filter((t) => t.entry.slice(0, 10) < start && Number.isFinite(t.sigma))
    .map((t) => t.sigma)
    .sort((a, b) => a - b);
  const accepted = new Set<number>();
  const weights = new Map<number, number>();
  const events: GateEvent[] = [];
  if (prior.length < 10) {
    for (const t of entries) {
      if (Date.parse(t.entry) > cutoff) break;
      accepted.add(t.index);
      weights.set(t.index, 1);
    }
    events.push({
      timestamp: start ? `${start}T00:00:00Z` : (entries[0]?.entry ?? ""),
      state: "Active",
      reason:
        "Fewer than 10 sized entries before the window; sizes left unchanged",
    });
    return { accepted, weights, events, state: "Active" };
  }
  const target = prior[Math.floor(prior.length / 2)];
  let band: GateState = "Active";
  for (const t of entries) {
    if (Date.parse(t.entry) > cutoff) break;
    const weight =
      Number.isFinite(t.sigma) && t.sigma > 0
        ? Math.min(cap, Math.max(0, target / t.sigma))
        : 1;
    accepted.add(t.index);
    weights.set(t.index, weight);
    const next: GateState =
      weight < 0.5 ? "Reduced" : weight > 1.5 ? "Raised" : "Active";
    if (next !== band) {
      band = next;
      events.push({
        timestamp: t.entry,
        state: next,
        reason: `Size ×${weight.toFixed(2)}: target $${Math.round(target)} ÷ recent $${Math.round(t.sigma)} per positioned day`,
      });
    }
  }
  return { accepted, weights, events, state: band };
}

// Kaminski & Lo (2014): a loss-triggered stop can only add expected return when
// outcomes persist (positive serial dependence). This reports the evidence for
// one book from trades closed before the window when at least 30 exist, else
// from the window itself. Runs test on win/loss signs; z below -1.96 means
// fewer runs than chance (streaks), above +1.96 means alternation.
export type Dependence = {
  trades: number;
  prior: boolean;
  autocorrelation: number;
  runsZ: number;
  afterLoss: number;
  afterWin: number;
  verdict: "cluster" | "alternate" | "none" | "insufficient";
};
export function tradeDependence(
  trades: Trade[],
  start: string,
  end: string,
): Dependence {
  const sorted = [...trades].sort((a, b) => a.exit.localeCompare(b.exit));
  const before = sorted.filter((t) => t.exit.slice(0, 10) < start);
  const within = sorted.filter((t) => {
    const d = t.exit.slice(0, 10);
    return d >= start && d <= end;
  });
  const prior = before.length >= 30;
  const sample = prior ? before : within;
  const n = sample.length;
  if (n < 30)
    return {
      trades: n,
      prior,
      autocorrelation: NaN,
      runsZ: NaN,
      afterLoss: NaN,
      afterWin: NaN,
      verdict: "insufficient",
    };
  const p = sample.map((t) => t.pnl);
  const mean = p.reduce((a, b) => a + b, 0) / n;
  const variance = p.reduce((a, b) => a + (b - mean) ** 2, 0) / n;
  let cross = 0;
  for (let i = 1; i < n; i++) cross += (p[i] - mean) * (p[i - 1] - mean);
  const autocorrelation = variance ? cross / (n * variance) : 0;
  const wins = p.map((x) => x > 0);
  const n1 = wins.filter(Boolean).length,
    n0 = n - n1;
  let runs = 1;
  for (let i = 1; i < n; i++) if (wins[i] !== wins[i - 1]) runs++;
  const expected = (2 * n1 * n0) / n + 1;
  const spread = Math.sqrt(
    (2 * n1 * n0 * (2 * n1 * n0 - n)) / (n * n * (n - 1)),
  );
  const runsZ = n1 && n0 && spread ? (runs - expected) / spread : 0;
  const afterLoss: number[] = [],
    afterWin: number[] = [];
  for (let i = 1; i < n; i++) (wins[i - 1] ? afterWin : afterLoss).push(p[i]);
  const average = (xs: number[]) =>
    xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : NaN;
  return {
    trades: n,
    prior,
    autocorrelation,
    runsZ,
    afterLoss: average(afterLoss),
    afterWin: average(afterWin),
    verdict: runsZ <= -1.96 ? "cluster" : runsZ >= 1.96 ? "alternate" : "none",
  };
}

export function calendarDates(start: string, end: string): string[] {
  const first = Date.parse(start + "T00:00:00Z"),
    last = Date.parse(end + "T00:00:00Z");
  if (
    !Number.isFinite(first) ||
    !Number.isFinite(last) ||
    last < first ||
    last - first > 40 * 366 * 86400000
  )
    return [];
  return Array.from(
    { length: Math.round((last - first) / 86400000) + 1 },
    (_, i) => new Date(first + i * 86400000).toISOString().slice(0, 10),
  );
}
export function covered(date: string, spans: Coverage[]) {
  return spans.some((s) => s.start <= date && date <= s.end);
}
export function commonWindow(items: CollectiveItem[]) {
  return {
    start:
      items
        .map((i) => i.start)
        .sort()
        .at(-1) || "",
    end: items.map((i) => i.end).sort()[0] || "",
  };
}
export type DailyPoint = {
  date: string;
  pnl: number;
  baseline: number;
  cumulative: number;
  baselineCumulative: number;
  equity: number;
  drawdown: number;
  trades: number;
  bySymbol: Record<string, number>;
  byStrategy: Record<string, number>;
};
export function calculatePortfolio(
  items: CollectiveItem[],
  series: CollectiveSeries[],
  copies: Record<string, number>,
  start: string,
  end: string,
  basis: "marked" | "closed",
  policy: GatePolicy,
) {
  const dates = calendarDates(start, end);
  const active = items.filter((i) => (copies[i.id] || 0) > 0);
  if (!active.length)
    throw new Error("Select at least one strategy configuration.");
  if (!dates.length) throw new Error("Choose a valid start and end date.");
  if (
    active.some(
      (i) =>
        !Number.isInteger(copies[i.id]) ||
        copies[i.id] < 1 ||
        copies[i.id] > 100,
    )
  )
    throw new Error("Copies must be whole numbers from 1 to 100.");
  const data = new Map(series.map((s) => [s.id, s]));
  const missing = active.filter((i) => !data.has(i.id));
  if (missing.length) throw new Error("Loading selected strategy histories…");
  const gaps = active.filter((i) =>
    dates.some((d) => !covered(d, data.get(i.id)!.coverage)),
  );
  if (gaps.length)
    throw new Error(
      `The selected period is not covered by ${gaps.map((i) => i.name + " / " + i.symbol + " / " + i.timeframe).join(", ")}. Use the common tested window or remove those configurations.`,
    );
  if (basis === "marked" && policy.enabled)
    throw new Error("Pause/resume replay uses closed-trade accounting.");
  const byDate = new Map(
    dates.map((date) => [
      date,
      {
        date,
        pnl: 0,
        baseline: 0,
        cumulative: 0,
        baselineCumulative: 0,
        equity: 0,
        drawdown: 0,
        trades: 0,
        bySymbol: {},
        byStrategy: {},
      } as DailyPoint,
    ]),
  );
  const events: (GateEvent & { id: string; name: string })[] = [];
  const components: {
    id: string;
    name: string;
    symbol: string;
    pnl: number;
    baseline: number;
    trades: number;
    skipped: number;
    exposure: number;
    state: GateState;
  }[] = [];
  const dependence: (Dependence & {
    id: string;
    name: string;
    symbol: string;
  })[] = [];
  let totalTrades = 0,
    wins = 0,
    profit = 0,
    loss = 0,
    weightSum = 0;
  for (const item of active) {
    const s = data.get(item.id)!,
      multiplier = copies[item.id];
    const replay = replayGate(s.trades, policy, end, s.daily, start);
    events.push(
      ...replay.events
        .filter(
          (e) =>
            e.timestamp.slice(0, 10) >= start &&
            e.timestamp.slice(0, 10) <= end,
        )
        .map((e) => ({
          ...e,
          id: item.id,
          name: item.name + " / " + item.symbol,
        })),
    );
    if (policy.enabled)
      dependence.push({
        ...tradeDependence(s.trades, start, end),
        id: item.id,
        name: item.name,
        symbol: item.symbol,
      });
    const daily = new Map<string, number>(),
      base = new Map<string, number>(),
      counts = new Map<string, number>();
    let trades = 0,
      skipped = 0,
      weightTotal = 0;
    s.trades.forEach((t, index) => {
      const date = new Date(t.exit).toISOString().slice(0, 10);
      if (!byDate.has(date)) return;
      base.set(date, (base.get(date) || 0) + t.pnl * multiplier);
      if (replay.accepted.has(index)) {
        const weight = replay.weights.get(index) ?? 1,
          value = t.pnl * multiplier * weight;
        trades++;
        totalTrades++;
        weightTotal += weight;
        if (value > 0) wins++;
        profit += Math.max(0, value);
        loss += Math.max(0, -value);
        daily.set(date, (daily.get(date) || 0) + value);
        counts.set(date, (counts.get(date) || 0) + 1);
      } else skipped++;
    });
    weightSum += weightTotal;
    if (basis === "marked") {
      daily.clear();
      base.clear();
      for (const p of s.daily) {
        daily.set(p.date, p.pnl * multiplier);
        base.set(p.date, p.pnl * multiplier);
      }
    }
    let pnl = 0,
      baseline = 0;
    for (const date of dates) {
      const point = byDate.get(date)!,
        value = daily.get(date) || 0,
        original = base.get(date) || 0;
      point.pnl += value;
      point.baseline += original;
      point.trades += counts.get(date) || 0;
      point.bySymbol[item.symbol] = (point.bySymbol[item.symbol] || 0) + value;
      point.byStrategy[item.id] = value;
      pnl += value;
      baseline += original;
    }
    components.push({
      id: item.id,
      name: item.name,
      symbol: item.symbol,
      pnl,
      baseline,
      trades,
      skipped,
      exposure: trades ? weightTotal / trades : 1,
      state: replay.state,
    });
  }
  const capital = active.reduce((n, i) => n + i.capital * copies[i.id], 0);
  let cumulative = 0,
    original = 0,
    peak = capital,
    maxDrawdown = 0,
    maxDrawdownDollars = 0;
  const points = [...byDate.values()].map((p) => {
    cumulative += p.pnl;
    original += p.baseline;
    const equity = capital + cumulative;
    peak = Math.max(peak, equity);
    const drawdown = equity / peak - 1;
    maxDrawdown = Math.min(maxDrawdown, drawdown);
    maxDrawdownDollars = Math.max(maxDrawdownDollars, peak - equity);
    return { ...p, cumulative, baselineCumulative: original, equity, drawdown };
  });
  const activity = points.filter((p) => p.pnl !== 0 || p.trades > 0);
  return {
    points,
    components,
    dependence,
    events: events.sort((a, b) => a.timestamp.localeCompare(b.timestamp)),
    capital,
    net: cumulative,
    baseline: original,
    maxDrawdown,
    maxDrawdownDollars,
    profitFactor: loss > 0 ? profit / loss : null,
    winRate: totalTrades ? wins / totalTrades : null,
    trades: totalTrades,
    exposure: totalTrades ? weightSum / totalTrades : 1,
    positiveDays: activity.filter((p) => p.pnl > 0).length,
    activeDays: activity.length,
    returnOnCapital: cumulative / capital,
    recoveryFactor: maxDrawdownDollars ? cumulative / maxDrawdownDollars : null,
  };
}
