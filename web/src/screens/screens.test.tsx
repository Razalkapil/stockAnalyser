import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { TicketProvider } from "../components/TicketContext";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { detail, mockApi, pick, preview, summary } from "../test/fixtures";
import { Brief } from "./Brief";
import { Login } from "./Login";
import { StrategyLab } from "./StrategyLab";
import { Today } from "./Today";

function renderWith(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TicketProvider>{ui}</TicketProvider>
      </MemoryRouter>
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

  it("offers previews when the gate has approved nothing, and calls them not-picks", async () => {
    mockApi({ "/api/picks": [], "/api/previews": [preview()] });
    renderWith(<Today />);
    expect(await screen.findByText("No picks yet")).toBeInTheDocument();
    expect(screen.getByText(/not a recommendation|nothing here is a recommendation/)).toBeInTheDocument();
    expect(screen.getByText(/Preview — not promoted/)).toBeInTheDocument();
  });

  it("shows previews without a click when nothing is promoted, and marks the strategy's status", async () => {
    mockApi({ "/api/picks": [], "/api/previews": [preview()] });
    renderWith(<Today />);
    expect(await screen.findByTestId("preview-card")).toBeInTheDocument();
    expect(screen.getByText("TATASTEEL")).toBeInTheDocument();
    expect(screen.getByText("rejected")).toBeInTheDocument();
  });

  it("keeps previews collapsed when real picks exist, until asked", async () => {
    mockApi({ "/api/picks": picks, "/api/previews": [preview({ horizon: "short_term" })] });
    renderWith(<Today />);
    await screen.findByText("AAA");
    expect(screen.queryByTestId("preview-card")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText(/Preview — not promoted/));
    expect(screen.getByTestId("preview-card")).toBeInTheDocument();
  });

  it("files each preview under its own horizon tab", async () => {
    mockApi({
      "/api/picks": [],
      "/api/previews": [
        preview({ symbol: "SWINGY", horizon: "swing", strategyId: "s1" }),
        preview({ symbol: "MOMO", horizon: "momentum", strategyId: "s2" }),
      ],
    });
    renderWith(<Today />);
    // lands on the first horizon that has content (swing), not an empty short-term tab
    expect(await screen.findByText("SWINGY")).toBeInTheDocument();
    expect(screen.queryByText("MOMO")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Momentum/ }));
    expect(screen.getByText("MOMO")).toBeInTheDocument();
    expect(screen.queryByText("SWINGY")).not.toBeInTheDocument();
  });

  it("counts previews on the tab, so a tab with only previews does not read as empty", async () => {
    mockApi({ "/api/picks": [], "/api/previews": [preview({ horizon: "swing" })] });
    renderWith(<Today />);
    await screen.findByTestId("preview-card");
    expect(screen.getByRole("tab", { name: /Swing\s*0\s*\+1 preview/ })).toBeInTheDocument();
  });

  it("says why a horizon has previews but no promoted picks", async () => {
    mockApi({ "/api/picks": [], "/api/previews": [preview({ horizon: "swing" })] });
    renderWith(<Today />);
    await screen.findByTestId("preview-card");
    expect(screen.getByText("No promoted picks for this horizon")).toBeInTheDocument();
    expect(screen.queryByText("No qualifying picks today")).not.toBeInTheDocument();
  });

  it("never renders a preview as a pick card, and never inside the picks grid", async () => {
    mockApi({
      "/api/picks": [pick({ id: 1, symbol: "AAA", horizon: "swing" })],
      "/api/previews": [preview({ horizon: "swing" })],
    });
    renderWith(<Today />);
    await screen.findByText("AAA");
    await userEvent.click(screen.getByText(/Preview — not promoted/));
    const card = screen.getByTestId("preview-card");
    expect(screen.getAllByTestId("pick-card")).toHaveLength(1);
    expect(screen.getByTestId("pick-card").contains(card)).toBe(false);
    // the preview sits inside its own labelled block
    expect(screen.getByTestId("preview-block").contains(card)).toBe(true);
  });

  it("shows previews in the columns layout too", async () => {
    localStorage.setItem("stk.todayLayout", "columns");
    mockApi({
      "/api/picks": [],
      "/api/previews": [
        preview({ symbol: "SWINGY", horizon: "swing", strategyId: "s1" }),
        preview({ symbol: "MOMO", horizon: "momentum", strategyId: "s2" }),
      ],
    });
    renderWith(<Today />);
    expect(await screen.findByText("SWINGY")).toBeInTheDocument();
    expect(screen.getByText("MOMO")).toBeInTheDocument();
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
      "/api/proposals": [],
    });
    renderWith(<StrategyLab />);
    expect(await screen.findByText("2 strategies", { exact: false })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(screen.getByText("approx")).toBeInTheDocument();
    expect(await screen.findByText("gap_pct >= 2")).toBeInTheDocument();
    expect(screen.getByText(/120 backtest trades/)).toBeInTheDocument();
  });

  it("renders walk-forward windows including the third, no-benchmark state", async () => {
    mockApi({ "/api/strategies/a": detail({ id: "a" }), "/api/strategies": rows, "/api/proposals": [] });
    renderWith(<StrategyLab />);
    await screen.findByText("W1");
    expect(screen.getByText("W2").getAttribute("title")).toMatch(/fail/);
    expect(screen.getByText("W3").getAttribute("title")).toMatch(/no benchmark/);
  });

  it("shows how far a rejected strategy is from the gate, per check", async () => {
    mockApi({ "/api/strategies/a": detail({ id: "a" }), "/api/strategies": rows, "/api/proposals": [] });
    renderWith(<StrategyLab />);
    const block = await screen.findByTestId("gate-checks");
    expect(block).toHaveTextContent("beat the benchmark in 3/7 windows (43%), need >= 60%");
    expect(block).toHaveTextContent("120 trades, need >= 30");
    expect(screen.getByLabelText("failed")).toBeInTheDocument();
    expect(screen.getByLabelText("passed")).toBeInTheDocument();
  });

  it("omits the gate block for a strategy that was never backtested", async () => {
    mockApi({
      "/api/strategies/a": detail({ id: "a", gateChecks: [] }),
      "/api/strategies": rows,
      "/api/proposals": [],
    });
    renderWith(<StrategyLab />);
    await screen.findByText("W1");
    expect(screen.queryByTestId("gate-checks")).not.toBeInTheDocument();
  });

  it("will not approve a candidate that has not passed the gate", async () => {
    mockApi({
      "/api/strategies/a": detail({ id: "a", name: "Alpha" }),
      "/api/strategies/b": detail({ id: "b", name: "Beta", status: "candidate",
        gateVerdict: "insufficient_evidence", approxReasons: ["benchmark did not cover some windows"] }),
      "/api/strategies": rows,
      "/api/proposals": [],
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
      "/api/proposals": [],
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
    const fn = mockApi({ "/api/strategies/a": detail({ id: "a" }), "/api/strategies": rows, "/api/proposals": [] });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWith(<StrategyLab />);
    await userEvent.click(await screen.findByRole("button", { name: "Retire" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(fn.mock.calls.some(([u]) => String(u).endsWith("/retire"))).toBe(false);
  });

  it("tells you when nothing is registered", async () => {
    mockApi({ "/api/strategies": [], "/api/proposals": [] });
    renderWith(<StrategyLab />);
    expect(await screen.findByText("No strategies registered")).toBeInTheDocument();
  });
});

const unreadyBrief = (state: string, stateReason: string | null = null) => ({
  date: "2026-09-18", pending: true, state, stateReason, coverage: null, generatedAt: null,
  overview: "",
  notablePicks: [], conflicts: [], positionNotes: [],
});

describe("Brief", () => {
  it("is honestly pending until the AI review writes one", async () => {
    mockApi({
      "/api/briefs/2026-09-18": unreadyBrief("pending"),
      "/api/briefs": [{ date: "2026-09-18", pending: true, state: "pending" }],
    });
    renderWith(<Brief />);
    expect(await screen.findByText("This brief has not been generated yet")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("says WHY there is no brief instead of a bare 'pending'", async () => {
    mockApi({
      "/api/briefs/2026-09-18": unreadyBrief(
        "skipped",
        "nothing to review: no picks, no strategy previews, no open positions and no index moves",
      ),
      "/api/briefs": [{ date: "2026-09-18", pending: true, state: "skipped" }],
    });
    renderWith(<Brief />);
    expect(await screen.findByText("Nothing to review")).toBeInTheDocument();
    expect(screen.getByText(/nothing to review: no picks/)).toBeInTheDocument();
  });

  it("queues a review rather than calling a model from the browser", async () => {
    const fn = mockApi({
      "/api/briefs/2026-09-18": unreadyBrief("pending"),
      "/api/briefs": [{ date: "2026-09-18", pending: true, state: "pending" }],
      "/api/briefs/2026-09-18/generate": unreadyBrief("queued"),
    });
    renderWith(<Brief />);
    await userEvent.click(await screen.findByRole("button", { name: "Generate now" }));
    const call = fn.mock.calls.find(([u]) => String(u).endsWith("/generate"));
    expect(call).toBeDefined();
    expect((call?.[1] as RequestInit | undefined)?.method).toBe("POST");
  });

  it("cannot be pressed twice while a request is already in flight", async () => {
    mockApi({
      "/api/briefs/2026-09-18": unreadyBrief("queued"),
      "/api/briefs": [{ date: "2026-09-18", pending: true, state: "queued" }],
    });
    renderWith(<Brief />);
    expect(await screen.findByRole("button", { name: "Queued…" })).toBeDisabled();
  });

  it("does not blank the screen on a state it does not know", async () => {
    mockApi({
      "/api/briefs/2026-09-18": unreadyBrief("something_new"),
      "/api/briefs": [{ date: "2026-09-18", pending: true, state: "something_new" }],
    });
    renderWith(<Brief />);
    expect(await screen.findByText("This brief has not been generated yet")).toBeInTheDocument();
  });
});

describe("Brief (written)", () => {
  it("renders the four cards from a stored review", async () => {
    mockApi({
      "/api/briefs/2026-09-18": {
        date: "2026-09-18", pending: false, generatedAt: "2026-09-18T18:47:00+00:00",
        overview: "Indices were flat; breadth mixed.",
        notablePicks: [{ symbol: "RELIANCE", note: "gap held on volume" }],
        conflicts: ["Momentum names look stretched vs. their live record"],
        positionNotes: [{ symbol: "TITAN", note: "up 3% in 4 days, stop untouched" }],
      },
      "/api/briefs": [{ date: "2026-09-18", pending: false }],
    });
    renderWith(<Brief />);
    expect(await screen.findByText("Indices were flat; breadth mixed.")).toBeInTheDocument();
    for (const title of ["Overview", "Notable picks", "Conflicts flagged", "Your open positions"]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    expect(screen.getByText("gap held on volume")).toBeInTheDocument();
    expect(screen.getByText(/Momentum names look stretched/)).toBeInTheDocument();
    expect(screen.getByText(/stop untouched/)).toBeInTheDocument();
    expect(screen.queryByText("pending")).not.toBeInTheDocument();
  });
});

describe("Brief (coverage)", () => {
  const written = (coverage?: "picks" | "preview") => ({
    date: "2026-09-18", pending: false, state: "ready", stateReason: null,
    ...(coverage ? { coverage } : {}),
    generatedAt: "2026-09-18T18:47:00+00:00", overview: "Indices were flat.",
    notablePicks: [{ symbol: "RELIANCE", note: "flagged by an unapproved rule" }],
    conflicts: [], positionNotes: [],
  });
  const list = (coverage?: "picks" | "preview") => [
    { date: "2026-09-18", pending: false, state: "ready", ...(coverage ? { coverage } : {}) },
  ];

  it("labels a brief written without picks so it cannot read as a recommendation", async () => {
    mockApi({ "/api/briefs/2026-09-18": written("preview"), "/api/briefs": list("preview") });
    renderWith(<Brief />);
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent(/unapproved/);
    expect(note).toHaveTextContent(/Nothing here is a recommendation/);
    expect(screen.getByText("Notable names")).toBeInTheDocument();
    expect(screen.getByText("preview")).toBeInTheDocument();
  });

  it("does not label a brief that ranked real picks", async () => {
    mockApi({ "/api/briefs/2026-09-18": written("picks"), "/api/briefs": list("picks") });
    renderWith(<Brief />);
    expect(await screen.findByText("Notable picks")).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("treats a missing coverage as a normal brief", async () => {
    mockApi({ "/api/briefs/2026-09-18": written(), "/api/briefs": list() });
    renderWith(<Brief />);
    expect(await screen.findByText("Notable picks")).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
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
