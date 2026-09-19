import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { detail, mockApi, pick, summary } from "../test/fixtures";
import { Brief } from "./Brief";
import { Login } from "./Login";
import { StrategyLab } from "./StrategyLab";
import { Today } from "./Today";

function renderWith(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("Today", () => {
  const picks = [
    pick({ id: 1, symbol: "AAA", horizon: "short_term", score: 60 }),
    pick({ id: 2, symbol: "BBB", horizon: "short_term", score: 90 }),
    pick({ id: 3, symbol: "CCC", horizon: "swing", score: 70, strategy: "Pullback" }),
  ];

  it("shows the horizon tabs with counts, and only the active horizon's cards", async () => {
    mockApi({ "/api/picks": picks });
    renderWith(<Today />);
    expect(await screen.findByText("AAA")).toBeInTheDocument();
    expect(screen.queryByText("CCC")).not.toBeInTheDocument(); // swing is not the active tab
    expect(screen.getByRole("tab", { name: /Short-term\s*2/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Swing\s*1/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Momentum\s*0/ })).toBeInTheDocument();
  });

  it("sorts by score, highest first", async () => {
    mockApi({ "/api/picks": picks });
    renderWith(<Today />);
    await screen.findByText("AAA");
    const symbols = screen.getAllByTestId("pick-symbol").map((el) => el.textContent);
    expect(symbols).toEqual(["BBB", "AAA"]);
  });

  it("shows the design's empty state for a horizon with no picks", async () => {
    mockApi({ "/api/picks": picks });
    renderWith(<Today />);
    await screen.findByText("AAA");
    await userEvent.click(screen.getByRole("tab", { name: /Momentum/ }));
    expect(screen.getByText("No qualifying picks today")).toBeInTheDocument();
  });

  it("switches to columns and remembers the choice", async () => {
    mockApi({ "/api/picks": picks });
    renderWith(<Today />);
    await screen.findByText("AAA");
    await userEvent.click(screen.getByRole("button", { name: "Columns" }));
    expect(screen.getByText("CCC")).toBeInTheDocument(); // every horizon is visible at once
    expect(screen.getAllByText("No picks today")).toHaveLength(2); // momentum + long-term
    expect(localStorage.getItem("stk.todayLayout")).toBe("columns");
  });

  it("says what to do when nothing has been scanned", async () => {
    mockApi({ "/api/picks": [] });
    renderWith(<Today />);
    expect(await screen.findByText("No picks yet")).toBeInTheDocument();
    expect(screen.getByText(/stk scan/)).toBeInTheDocument();
  });

  it("reports a failed load instead of an empty page", async () => {
    mockApi({ "/api/picks": new Response(JSON.stringify({ detail: "boom" }), { status: 500 }) });
    renderWith(<Today />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });

  it("states the signal date", async () => {
    mockApi({ "/api/picks": picks });
    renderWith(<Today />);
    expect(await screen.findByText(/Signals from the 18 Sep 2026 close/)).toBeInTheDocument();
  });
});

describe("StrategyLab", () => {
  const rows = [
    summary({ id: "a", name: "Alpha", status: "live" }),
    summary({ id: "b", name: "Beta", status: "candidate", approx: true, gateVerdict: "insufficient_evidence" }),
  ];

  it("lists strategies with status, approx tag and metrics; selects the first", async () => {
    mockApi({
      "/api/strategies/a": detail({ id: "a", name: "Alpha" }),
      "/api/strategies": rows,
    });
    renderWith(<StrategyLab />);
    expect(await screen.findByText("2 strategies", { exact: false })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(screen.getByText("approx")).toBeInTheDocument();
    expect(await screen.findByText("gap_pct >= 2")).toBeInTheDocument();
    expect(screen.getByText(/120 backtest trades/)).toBeInTheDocument();
  });

  it("renders walk-forward windows including the third, no-benchmark state", async () => {
    mockApi({ "/api/strategies/a": detail({ id: "a" }), "/api/strategies": rows });
    renderWith(<StrategyLab />);
    await screen.findByText("W1");
    expect(screen.getByText("W2").getAttribute("title")).toMatch(/fail/);
    expect(screen.getByText("W3").getAttribute("title")).toMatch(/no benchmark/);
  });

  it("will not approve a candidate that has not passed the gate", async () => {
    mockApi({
      "/api/strategies/a": detail({ id: "a", name: "Alpha" }),
      "/api/strategies/b": detail({ id: "b", name: "Beta", status: "candidate",
        gateVerdict: "insufficient_evidence", approxReasons: ["benchmark did not cover some windows"] }),
      "/api/strategies": rows,
    });
    renderWith(<StrategyLab />);
    await userEvent.click(await screen.findByText("Beta"));
    expect(await screen.findByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByText(/Read with care/)).toBeInTheDocument();
    expect(screen.getByText(/benchmark did not cover some windows/)).toBeInTheDocument();
  });

  it("enables approval once the gate has passed, and posts it", async () => {
    const fn = mockApi({
      "/api/strategies/a": detail({ id: "a", name: "Alpha" }),
      "/api/strategies/b/approve": summary({ id: "b", status: "live" }),
      "/api/strategies/b": detail({ id: "b", name: "Beta", status: "candidate", gateVerdict: "pass" }),
      "/api/strategies": rows,
    });
    renderWith(<StrategyLab />);
    await userEvent.click(await screen.findByText("Beta"));
    const btn = await screen.findByRole("button", { name: "Approve" });
    expect(btn).toBeEnabled();
    await userEvent.click(btn);
    await waitFor(() =>
      expect(fn).toHaveBeenCalledWith("/api/strategies/b/approve", expect.objectContaining({ method: "POST" })),
    );
  });

  it("asks before retiring, and does nothing if declined", async () => {
    const fn = mockApi({ "/api/strategies/a": detail({ id: "a" }), "/api/strategies": rows });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWith(<StrategyLab />);
    await userEvent.click(await screen.findByRole("button", { name: "Retire" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(fn.mock.calls.some(([u]) => String(u).endsWith("/retire"))).toBe(false);
  });

  it("tells you when nothing is registered", async () => {
    mockApi({ "/api/strategies": [] });
    renderWith(<StrategyLab />);
    expect(await screen.findByText("No strategies registered")).toBeInTheDocument();
  });
});

describe("Brief", () => {
  it("is honestly pending until the AI review writes one", async () => {
    mockApi({
      "/api/briefs/2026-09-18": { date: "2026-09-18", pending: true, generatedAt: null, overview: "",
        notablePicks: [], conflicts: [], positionNotes: [] },
      "/api/briefs": [{ date: "2026-09-18", pending: true }],
    });
    renderWith(<Brief />);
    expect(await screen.findByText("This brief has not been generated yet")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
  });
});

describe("Login", () => {
  it("stores the token it is given", async () => {
    renderWith(<Login />);
    await userEvent.type(screen.getByLabelText("API token"), "stk_secret");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(localStorage.getItem("stk.token")).toBe("stk_secret");
  });

  it("ignores an empty submit", async () => {
    renderWith(<Login />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(localStorage.getItem("stk.token")).toBeNull();
  });
});
