import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TicketProvider } from "../components/TicketContext";
import { detail, mockApi, proposal, summary } from "../test/fixtures";
import { StrategyLab } from "./StrategyLab";

function renderLab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TicketProvider>
          <StrategyLab />
        </TicketProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const base = (proposals: unknown[]) => ({
  "/api/strategies": [summary({ id: "a", name: "Alpha" })],
  "/api/strategies/a": detail({ id: "a", name: "Alpha" }),
  "/api/proposals": proposals,
});

afterEach(() => vi.restoreAllMocks());

describe("AI proposals", () => {
  it("shows a new-strategy proposal with its rules and out-of-sample numbers", async () => {
    mockApi(base([proposal()]));
    renderLab();
    const card = await screen.findByTestId("proposal");
    expect(within(card).getByText("New strategy")).toBeInTheDocument();
    expect(within(card).getByText("Buy short-term dips")).toBeInTheDocument();
    expect(within(card).getByText("rsi2 < 25")).toBeInTheDocument();
    expect(within(card).getByText("+18%")).toBeInTheDocument();
    expect(within(card).getByText("54%")).toBeInTheDocument();
    expect(within(card).getByText("-14%")).toBeInTheDocument();
    expect(within(card).getByText(/out-of-sample, after costs/)).toBeInTheDocument();
    expect(within(card).getByText(/Awaiting your approval/)).toBeInTheDocument();
  });

  it("approving posts to the API without a confirm dialog for a new strategy", async () => {
    const fn = mockApi({ ...base([proposal()]), "/api/proposals/5/approve": [] });
    const confirm = vi.spyOn(window, "confirm");
    renderLab();
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(fn).toHaveBeenCalledWith("/api/proposals/5/approve", expect.objectContaining({ method: "POST", body: JSON.stringify({ confirm: false }) })),
    );
    expect(confirm).not.toHaveBeenCalled();
  });

  it("a demotion asks first and sends confirm=true; declining sends nothing", async () => {
    const fn = mockApi({
      ...base([proposal({ id: 8, type: "demote", title: "Retire Alpha", targetStrategy: "a", strategyId: null, rules: [], gateVerdict: null, btCagr: null })]),
      "/api/proposals/8/approve": [],
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderLab();
    const btn = await screen.findByRole("button", { name: "Approve" });
    await userEvent.click(btn);
    expect(fn.mock.calls.some(([u]) => String(u).endsWith("/approve"))).toBe(false);
    await userEvent.click(btn);
    await waitFor(() =>
      expect(fn).toHaveBeenCalledWith("/api/proposals/8/approve", expect.objectContaining({ body: JSON.stringify({ confirm: true }) })),
    );
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Demotion")).toBeInTheDocument();
  });

  it("Reject dismisses it", async () => {
    const fn = mockApi({ ...base([proposal()]), "/api/proposals/5/dismiss": [] });
    renderLab();
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
    await waitFor(() =>
      expect(fn).toHaveBeenCalledWith("/api/proposals/5/dismiss", expect.objectContaining({ method: "POST" })),
    );
  });

  it("only an awaiting proposal has buttons; a failed one explains why and shows the errors", async () => {
    mockApi(base([proposal({ id: 6, status: "invalid", statusNote: "rejected before any backtest: unknown indicator 'magic'", validationErrors: ["entry: unknown indicator 'magic'"], gateVerdict: null, rules: [] })]));
    renderLab();
    const card = await screen.findByTestId("proposal");
    expect(within(card).queryByRole("button", { name: /approve|reject/i })).not.toBeInTheDocument();
    expect(within(card).getByText(/Rejected: invalid strategy/)).toBeInTheDocument();
    expect(within(card).getByText("entry: unknown indicator 'magic'")).toBeInTheDocument();
  });

  it("gate failures and insufficient evidence are stated, not hidden", async () => {
    mockApi(base([
      proposal({ id: 1, status: "rejected_by_gate", gateVerdict: "fail" }),
      proposal({ id: 2, status: "insufficient_evidence", gateVerdict: "insufficient_evidence" }),
    ]));
    renderLab();
    expect(await screen.findByText(/Failed the promotion gate/)).toBeInTheDocument();
    expect(screen.getByText(/Not enough evidence to judge/)).toBeInTheDocument();
  });

  it("shows the server's reason if an approval is refused", async () => {
    mockApi({ ...base([proposal()]), "/api/proposals/5/approve": new Response(JSON.stringify({ detail: "only a proposal that passed the promotion gate can go live" }), { status: 409 }) });
    renderLab();
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("passed the promotion gate");
  });

  it("flags an approximate backtest on the proposal", async () => {
    mockApi(base([proposal({ approx: true, approxReasons: ["benchmark did not cover some windows"] })]));
    renderLab();
    expect(await screen.findByText(/Approximate: benchmark did not cover/)).toBeInTheDocument();
  });

  it("says so when the lab has not run", async () => {
    mockApi(base([]));
    renderLab();
    expect(await screen.findByText("No proposals")).toBeInTheDocument();
  });
});
