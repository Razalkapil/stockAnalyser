import type { Pick, StrategyDetail, StrategySummary } from "../lib/api/types";

export const pick = (over: Partial<Pick> = {}): Pick => ({
  id: 1,
  symbol: "RELIANCE",
  company: "Reliance Industries Limited",
  exch: "NSE",
  sector: null,
  horizon: "short_term",
  strategy: "Gap-and-hold",
  strategyId: "short_gap_and_hold",
  score: 78.4,
  ref: 2945,
  stop: 2870.5,
  target: 3120,
  window: "up to 5 trading days",
  holdDays: 5,
  signalDate: "2026-09-18",
  status: "pending_entry",
  pickReturn: null,
  btCagr: 0.31,
  btWinRate: 0.55,
  liveReturn: 0.09,
  hitRate: 0.42,
  approx: false,
  reason: "Gap up 2.4% on 1.8x volume and held the close near the high.",
  conflict: null,
  ...over,
});

export const summary = (over: Partial<StrategySummary> = {}): StrategySummary => ({
  id: "short_gap_and_hold",
  name: "Gap-and-hold",
  horizon: "short_term",
  status: "live",
  statusReason: null,
  origin: "seed",
  btCagr: 0.31,
  winRate: 0.55,
  maxDd: -0.12,
  sharpe: 1.4,
  trades: 120,
  liveReturn: 0.02,
  hitRate: 0.5,
  liveClosed: 12,
  avgHold: 4,
  approx: false,
  gateVerdict: "pass",
  ...over,
});

export const detail = (over: Partial<StrategyDetail> = {}): StrategyDetail => ({
  ...summary(),
  notes: "",
  rules: ["gap_pct >= 2", "vol_ratio20 >= 1.5", "Stop: 1 x ATR%"],
  approxReasons: [],
  curveDates: ["2025-01-01", "2025-06-01", "2025-12-01"],
  equityCurve: [100, 110, 125],
  niftyCurve: [100, 104, 108],
  walkForward: [
    { label: "W1", result: "pass", testStart: "2024-01-01", testEnd: "2024-06-30", stratReturn: 0.1, benchReturn: 0.05 },
    { label: "W2", result: "fail", testStart: "2024-07-01", testEnd: "2024-12-31", stratReturn: -0.02, benchReturn: 0.03 },
    { label: "W3", result: "no_benchmark", testStart: "2025-01-01", testEnd: "2025-06-30", stratReturn: 0.04, benchReturn: null },
  ],
  tradeList: [{ symbol: "TITAN", date: "2026-09-10", ret: 0.031 }],
  tradeListSource: "live",
  ...over,
});

/**
 * Route a mocked fetch by EXACT path (query string ignored). Anything unlisted fails the test
 * loudly: a prefix match once let `/api/strategies/a` silently fall through to the list route.
 */
export function mockApi(routes: Record<string, unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input).split("?")[0] ?? "";
    if (!(path in routes)) throw new Error(`unmocked request: ${String(input)}`);
    const body = routes[path];
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export const stockDetail = (over: Record<string, unknown> = {}) => ({
  symbol: "RELIANCE",
  company: "Reliance Industries Limited",
  exch: "NSE",
  isin: "INE002A01018",
  tvSymbol: "NSE:RELIANCE",
  lastClose: 2945.5,
  changePct: 1.25,
  lastDate: "2026-09-18",
  fundamentals: null,
  flaggedBy: [
    { strategy: "Gap-and-hold", strategyId: "g", horizon: "short_term", signalDate: "2026-09-15", status: "open" },
  ],
  ...over,
});

export const bars = [
  { time: "2026-09-15", open: 100, high: 105, low: 99, close: 104, volume: 1000 },
  { time: "2026-09-16", open: 104, high: 106, low: 103, close: 105, volume: 1100 },
];
