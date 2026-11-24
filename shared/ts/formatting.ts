// Source snapshots keep their recorded names and hashes. Only presentation uses
// these cleaned titles, including the older catalog's misencoded middle dot.
//
// Naming rules for display:
// 1. Say what it does, in sentence case.
// 2. No market in the name: market and timeframe are shown beside it.
// 3. Source (Pine) and author become tags, see strategySourceTags().
// 4. One separator: variants follow an em dash.
const DOT = "(?:\\u00c2?\\u00b7)";
const pinePrefix = new RegExp(`^Pine\\s*${DOT}\\s*`);
const marketPrefix = new RegExp(`^(?:MNQ|NQ|MES|ES|YM|MYM|CL|MCL|MGC|GC)\\s*(?:${DOT}|-)\\s*`);
const authorTag = /\s*\[([^\]]+)\]/;

// Names whose wording the general rules can't fix. Keys are the cleaned name
// (after the Pine and market prefixes are removed).
const titleOverrides: Record<string, string> = {
  "Overnight Session": "Overnight session",
  "Prior Range Fill": "Prior range fill",
  "Opening Range Breakout": "Opening range breakout",
  "Canonical opening-range breakout": "Opening range breakout — canonical",
  "Market intraday momentum — last 30 minutes": "Intraday momentum — last 30 minutes",
  "Remaining zone detectors — common failure test": "Zone detectors — failure test",
  "Session extremes failure test": "Session extremes — failure test",
  "Multi-touch cluster failure test": "Multi-touch cluster — failure test",
  "overnight exit clocks": "Overnight exit clocks",
  "Sunday/Tuesday/Wednesday overnight": "Overnight — Sun/Tue/Wed only",
  "RTH close-location overnight": "Overnight — RTH close location",
  "18:00–03:00 clock scenario": "Overnight — 18:00–03:00 clock",
  "Overnight except red low-close RTH": "Overnight — skip red low-close days",
  "Unconditional RTH close-to-open": "Overnight — unconditional close to open",
  "SND — Supply and demand": "Supply & demand",
  "SND — Opposing zone exit experiment": "Supply & demand — opposing-zone exit",
  "Wyckoff — NQ research": "Wyckoff",
};

export function strategyTitle(name: string): string {
  const cleaned = name
    .replace(pinePrefix, "")
    .replace(marketPrefix, "")
    .replace(authorTag, "")
    .replace(/\s+-\s+/g, " — ")
    .replace(/^SND — Supply and demand \/ /, "Supply & demand — ")
    .replace(/— phase(\d+)/i, "— Phase $1")
    .replace(/\s+/g, " ")
    .trim();
  return titleOverrides[cleaned] || cleaned;
}

/** Small tags that used to be part of a name: its source and its author. */
export function strategySourceTags(name: string): string[] {
  const tags: string[] = [];
  if (pinePrefix.test(name)) tags.push("Pine");
  const author = name.match(authorTag)?.[1];
  if (author) tags.push(`by ${author}`);
  return tags;
}

/** Evaluation and scenario outcomes, in the shared Passed / Failed / Incomplete wording. */
export function outcomeLabel(outcome?: string | null): string {
  if (!outcome) return "Incomplete";
  if (outcome === "Meets criteria") return "Passed";
  if (["Does not meet criteria", "Criteria not met", "Failed criteria"].includes(outcome)) return "Failed";
  if (["Not scored", "Evaluation incomplete", "Incomplete"].includes(outcome)) return "Incomplete";
  return outcome;
}

/** The first sentence of a finding, used when a review has no summary. */
export function firstSentence(text: string): string {
  const trimmed = text.trim();
  const match = trimmed.match(/^[\s\S]*?[.!?](?=\s|$)/);
  return (match ? match[0] : trimmed).trim();
}
