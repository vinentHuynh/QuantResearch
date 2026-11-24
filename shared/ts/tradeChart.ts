import type { Trade } from "./portfolio.ts";

export type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
};
export type ChartTrade = Trade & {
  index: number;
  side?: "long" | "short";
  entryPrice?: number;
  exitPrice?: number;
  stop?: number;
  target?: number;
  changes?: { time: number; stop: number; target: number }[];
};
export type DayChart = {
  candles: Candle[];
  trades: ChartTrade[];
  reference: boolean;
  notes: string[];
};
