import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bars, mockApi, stockDetail } from "../test/fixtures";
import { Stocks } from "./Stocks";

const chart = vi.hoisted(() => {
  const markers = vi.fn();
  const setData = vi.fn();
  return { markers, setData };
});

// jsdom has no canvas; the chart library is replaced by a recorder of what it was asked to draw.
vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  CandlestickSeries: "candles",
  createChart: () => ({
    addSeries: () => ({ setData: chart.setData }),
    timeScale: () => ({ fitContent: vi.fn() }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }),
  createSeriesMarkers: chart.markers,
}));

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/stocks" element={<Stocks />} />
          <Route path="/stocks/:symbol" element={<Stocks />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  chart.markers.mockClear();
  chart.setData.mockClear();
});

describe("Stocks search", () => {
  it("invites a search, then lists matches", async () => {
    mockApi({
      "/api/stocks/search": [{ symbol: "RELIANCE", company: "Reliance Industries Limited", exch: "NSE", isin: "x" }],
    });
    renderAt("/stocks");
    expect(screen.getByText("Search for a stock")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Find a stock"), "rel");
    expect(await screen.findByText("Reliance Industries Limited")).toBeInTheDocument();
  });

  it("says when nothing matches", async () => {
    mockApi({ "/api/stocks/search": [] });
    renderAt("/stocks");
    await userEvent.type(screen.getByLabelText("Find a stock"), "zzz");
    expect(await screen.findByText("No match")).toBeInTheDocument();
  });
});

describe("Stock page", () => {
  const routes = () => ({
    "/api/stocks/RELIANCE": stockDetail(),
    "/api/stocks/RELIANCE/bars": bars,
  });

  it("shows the header with lakh-formatted price and coloured change", async () => {
    mockApi(routes());
    renderAt("/stocks/RELIANCE");
    expect(await screen.findByText("₹2,945.50")).toBeInTheDocument();
    expect(screen.getByText("+1.25%")).toBeInTheDocument();
    expect(screen.getByText("close 18 Sep 2026")).toBeInTheDocument();
  });

  it("draws our own adjusted bars and marks the day a strategy flagged the stock", async () => {
    mockApi(routes());
    renderAt("/stocks/RELIANCE");
    await screen.findByTestId("price-chart");
    expect(chart.setData).toHaveBeenCalledWith(expect.arrayContaining([expect.objectContaining({ time: "2026-09-15", close: 104 })]));
    const [, marks] = chart.markers.mock.calls.at(-1) as [unknown, { time: string; text: string }[]];
    expect(marks).toEqual([expect.objectContaining({ time: "2026-09-15", text: "Gap-and-hold" })]);
  });

  it("never asks the chart to mark a day it has no bar for", async () => {
    mockApi({
      ...routes(),
      "/api/stocks/RELIANCE": stockDetail({
        flaggedBy: [{ strategy: "S", strategyId: "s", horizon: "swing", signalDate: "2020-01-01", status: "open" }],
      }),
    });
    renderAt("/stocks/RELIANCE");
    await screen.findByTestId("price-chart");
    const [, marks] = chart.markers.mock.calls.at(-1) as [unknown, unknown[]];
    expect(marks).toEqual([]);
  });

  it("links out to TradingView instead of embedding it (the free widget has no NSE/BSE data)", async () => {
    mockApi(routes());
    renderAt("/stocks/RELIANCE");
    await screen.findByTestId("price-chart");
    const link = screen.getByRole("link", { name: /Open on TradingView/ });
    expect(link).toHaveAttribute("href", expect.stringMatching(/^https:\/\/www\.tradingview\.com\/chart\/\?symbol=NSE%3ARELIANCE$/));
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(document.querySelector("[data-testid=tv-widget]")).toBeNull();
  });

  it("says fundamentals are unavailable rather than showing zeros", async () => {
    mockApi(routes());
    renderAt("/stocks/RELIANCE");
    expect(await screen.findByText(/No parsed filings for this stock/)).toBeInTheDocument();
  });

  it("shows fundamentals as blanks where not computable, with the caveat", async () => {
    mockApi({
      ...routes(),
      "/api/stocks/RELIANCE": stockDetail({
        fundamentals: { asOf: "2026-05-20", roce: 0.142, deRatio: 0.35, salesCagr3: null,
          profitCagr3: null, epsTtm: 102.9, approx: true, note: "Shallow history." },
      }),
    });
    renderAt("/stocks/RELIANCE");
    expect(await screen.findByText("14.2%")).toBeInTheDocument();
    expect(screen.getByText("0.35")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2); // the two null CAGRs
    expect(screen.getByText(/Shallow history/)).toBeInTheDocument();
  });

  it("gives a clear message for an unknown symbol", async () => {
    mockApi({ "/api/stocks/NOPE": new Response(JSON.stringify({ detail: "no security" }), { status: 404 }) });
    renderAt("/stocks/NOPE");
    expect(await screen.findByText("No security called NOPE")).toBeInTheDocument();
  });
});
