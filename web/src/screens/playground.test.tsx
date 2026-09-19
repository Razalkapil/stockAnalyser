import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OrderDrawer } from "../components/OrderDrawer";
import { TicketProvider, useTicket } from "../components/TicketContext";
import { mockApi, portfolioDetail, portfolioSummary, stockDetail } from "../test/fixtures";
import { Playground } from "./Playground";

function OpenButton({ prefill }: { prefill: Record<string, unknown> }) {
  const { openTicket } = useTicket();
  return <button onClick={() => openTicket(prefill)}>open-ticket</button>;
}

function renderPlayground(extra?: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TicketProvider>
          <Playground />
          <OrderDrawer />
          {extra}
        </TicketProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const routes = (over: Record<string, unknown> = {}) => ({
  "/api/portfolios": [portfolioSummary()],
  "/api/portfolios/1": portfolioDetail(),
  "/api/stocks/RELIANCE": stockDetail(),
  ...over,
});

afterEach(() => vi.unstubAllGlobals());

describe("Playground", () => {
  it("shows the ten stat tiles with lakh formatting and coloured P&L", async () => {
    mockApi(routes());
    renderPlayground();
    expect(await screen.findByText("₹10,12,345.50")).toBeInTheDocument(); // current value
    for (const label of ["Current value", "Cash", "Invested", "Realised P&L", "Unrealised P&L",
      "Charges paid", "Return vs Nifty", "XIRR", "Max drawdown", "Win rate"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("+1.2% / +0.8%")).toBeInTheDocument();
    expect(screen.getByText("+14.0%")).toBeInTheDocument(); // XIRR
    expect(screen.getByText("-3.1%")).toBeInTheDocument(); // drawdown
  });

  it("shows a dash for XIRR / drawdown / win rate that cannot be computed, never 0", async () => {
    mockApi(routes({ "/api/portfolios/1": portfolioDetail({ xirr: null, maxDd: null, winRate: null, niftyReturnPct: null }) }));
    renderPlayground();
    await screen.findByText("XIRR");
    const tile = (label: string) => screen.getByText(label).parentElement as HTMLElement;
    expect(within(tile("XIRR")).getByText("—")).toBeInTheDocument();
    expect(within(tile("Max drawdown")).getByText("—")).toBeInTheDocument();
    expect(within(tile("Win rate")).getByText("—")).toBeInTheDocument();
  });

  it("lists positions with LTP and P&L", async () => {
    mockApi(routes());
    renderPlayground();
    expect(await screen.findByText("2,945.50")).toBeInTheDocument();
    expect(screen.getByText(/₹455\.00 \+1\.6%/)).toBeInTheDocument();
  });

  it("marks a parked order Pending with the designed message and explains it", async () => {
    mockApi(routes());
    renderPlayground();
    expect(await screen.findByText("Pending")).toBeInTheDocument();
    expect(screen.getAllByText("Delayed feed down — will fall back to EOD fill").length).toBeGreaterThan(0);
    expect(screen.getByRole("status")).toHaveTextContent(/Nothing fills on stale data/);
  });

  it("tags each trade with where its price came from", async () => {
    mockApi(routes());
    renderPlayground();
    await screen.findByText("delayed feed");
    expect(screen.getByText("EOD fill")).toBeInTheDocument();
    expect(screen.getByText("delayed feed").getAttribute("title")).toMatch(/14 min behind/);
  });

  it("cancels an open order", async () => {
    const fn = mockApi(routes({ "/api/orders/11": {} }));
    renderPlayground();
    const row = (await screen.findByText("TITAN")).closest("[role=row]") as HTMLElement;
    await userEvent.click(within(row).getByText("Cancel"));
    await waitFor(() =>
      expect(fn).toHaveBeenCalledWith("/api/orders/11", expect.objectContaining({ method: "DELETE" })),
    );
  });

  it("edits a journal note inline", async () => {
    const fn = mockApi(routes({ "/api/trades/1": {} }));
    renderPlayground();
    await userEvent.click(await screen.findByText("breakout entry"));
    const box = screen.getByLabelText("Journal note");
    await userEvent.clear(box);
    await userEvent.type(box, "sized too big{Enter}");
    await waitFor(() =>
      expect(fn).toHaveBeenCalledWith(
        "/api/trades/1",
        expect.objectContaining({ method: "PATCH", body: JSON.stringify({ note: "sized too big" }) }),
      ),
    );
  });

  it("says what to do with no portfolios, and can create one", async () => {
    const fn = mockApi({ "/api/portfolios": [] });
    renderPlayground();
    expect(await screen.findByText("No portfolios yet")).toBeInTheDocument();
    await userEvent.click(screen.getByText("+ New portfolio"));
    await userEvent.type(screen.getByLabelText("Portfolio name"), "Swing test");
    fn.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      const ok = (b: unknown) => new Response(JSON.stringify(b), { status: init?.method === "POST" ? 201 : 200 });
      if (path === "/api/portfolios" && init?.method === "POST") return ok(portfolioSummary({ id: 2, name: "Swing test" }));
      if (path === "/api/portfolios") return ok([portfolioSummary({ id: 2, name: "Swing test" })]);
      return ok(portfolioDetail({ id: 2, name: "Swing test" }));
    });
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(fn).toHaveBeenCalledWith(
        "/api/portfolios",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ name: "Swing test", startCapital: "1000000" }) }),
      ),
    );
  });

  it("explains an empty curve instead of drawing nothing", async () => {
    mockApi(routes({ "/api/portfolios/1": portfolioDetail({ curve: [], niftyCurve: [] }) }));
    renderPlayground();
    expect(await screen.findByText(/builds from nightly snapshots/)).toBeInTheDocument();
  });
});

describe("Order ticket", () => {
  const preview = { price: 2945, estPrice: 2946.5, slippageBps: 5, value: 29465, charges: 42.6,
    dpCharge: 0, total: 29507.6, chargeBreakdown: {}, note: "" };

  async function openTicket(prefill: Record<string, unknown>, extra: Record<string, unknown> = {}) {
    const fn = mockApi(routes({ "/api/orders/preview": preview, ...extra }));
    renderPlayground(<OpenButton prefill={prefill} />);
    await screen.findByText("Current value");
    await userEvent.click(screen.getByText("open-ticket"));
    await screen.findByRole("dialog", { name: "Order ticket" });
    return fn;
  }

  it("is pre-filled from a pick, and shows the live cost estimate", async () => {
    await openTicket({ symbol: "RELIANCE", ref: 2945, stop: 2870.5, target: 3120, pickId: 7 });
    expect(screen.getByLabelText("Symbol")).toHaveValue("RELIANCE");
    expect(screen.getByLabelText("Stop")).toHaveValue("2870.5");
    expect(screen.getByLabelText("Target")).toHaveValue("3120");
    const dialog = screen.getByRole("dialog", { name: "Order ticket" });
    expect(await within(dialog).findByText("₹29,465.00")).toBeInTheDocument(); // est. value
    expect(within(dialog).getByText("₹42.60")).toBeInTheDocument(); // (also a trade charge on the page)
    expect(within(dialog).getByText("₹29,507.60")).toBeInTheDocument(); // total
    expect(within(dialog).getByText(/5 bps slippage/)).toBeInTheDocument();
  });

  it("posts the order with exact decimal strings, the bracket and the pick id", async () => {
    const fn = await openTicket({ symbol: "RELIANCE", ref: 2945, stop: 2870.5, target: 3120, pickId: 7 },
      { "/api/orders": { id: 99 } });
    await userEvent.click(screen.getByRole("button", { name: "Place paper order" }));
    await waitFor(() => {
      const call = fn.mock.calls.find(([u]) => String(u) === "/api/orders");
      expect(call).toBeTruthy();
      const body = JSON.parse((call![1] as RequestInit).body as string);
      expect(body).toMatchObject({ portfolioId: 1, symbol: "RELIANCE", side: "buy", type: "MARKET",
        qty: 10, bracketStop: "2870.5", bracketTarget: "3120", pickId: 7, limitPrice: null });
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument()); // closes on success
  });

  it("a limit order needs a price before it can be placed", async () => {
    await openTicket({ symbol: "RELIANCE", ref: 2945 });
    await userEvent.selectOptions(screen.getByLabelText("Order type"), "LIMIT");
    expect(screen.getByRole("button", { name: "Place paper order" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Price"), "2900");
    expect(screen.getByRole("button", { name: "Place paper order" })).toBeEnabled();
  });

  it("stop-loss and target are sell-only, so choosing one flips to sell and drops the bracket", async () => {
    await openTicket({ symbol: "RELIANCE", ref: 2945, stop: 2870, target: 3120 });
    await userEvent.selectOptions(screen.getByLabelText("Order type"), "SL");
    expect(screen.getByRole("button", { name: "Sell" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByLabelText("Stop")).not.toBeInTheDocument();
  });

  it("shows the server's reason when an order is refused", async () => {
    const fn = await openTicket({ symbol: "RELIANCE", ref: 2945 },
      { "/api/orders": new Response(JSON.stringify({ detail: "cannot sell 10 RELIANCE: only 0 held (no shorting)" }), { status: 422 }) });
    await userEvent.click(screen.getByRole("button", { name: "Sell" }));
    await userEvent.click(screen.getByRole("button", { name: "Place paper order" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("only 0 held (no shorting)");
    expect(fn).toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument(); // stays open so it can be corrected
  });

  it("closes from the ✕", async () => {
    await openTicket({ symbol: "RELIANCE", ref: 2945 });
    await userEvent.click(screen.getByLabelText("Close"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
