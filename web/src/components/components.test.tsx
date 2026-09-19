import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { pick } from "../test/fixtures";
import { EquityChart } from "./EquityChart";
import { PickCard } from "./PickCard";
import { StaleBanner } from "./StaleBanner";
import { StatusPill } from "./StatusPill";

describe("PickCard", () => {
  it("shows the design's fields with lakh formatting", () => {
    render(<PickCard pick={pick({ ref: 123456.5 })} />);
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("NSE")).toBeInTheDocument();
    expect(screen.getByText("78/100")).toBeInTheDocument();
    expect(screen.getByText("₹1,23,456.50")).toBeInTheDocument();
    expect(screen.getByText(/BT \+31% \/ Live \+9\.0%/)).toBeInTheDocument();
    expect(screen.getByText("42% hit")).toBeInTheDocument();
    expect(screen.getByText("up to 5 trading days")).toBeInTheDocument();
  });

  it("shows a dash, not a zero, when there is no backtest or live record", () => {
    render(<PickCard pick={pick({ btCagr: null, liveReturn: null, hitRate: null, target: null })} />);
    expect(screen.getByText(/BT — \/ Live —/)).toBeInTheDocument();
    expect(screen.getByText("— hit")).toBeInTheDocument();
    expect(screen.queryByText("₹0.00")).not.toBeInTheDocument();
  });

  it("flags an approximate backtest", () => {
    render(<PickCard pick={pick({ approx: true })} />);
    expect(screen.getByText("approx")).toBeInTheDocument();
  });

  it("renders a conflict note only when there is one", () => {
    const { rerender } = render(<PickCard pick={pick()} />);
    expect(screen.queryByText("⚑")).not.toBeInTheDocument();
    rerender(<PickCard pick={pick({ conflict: "Fundamentals deteriorating" })} />);
    expect(screen.getByText("Fundamentals deteriorating")).toBeInTheDocument();
  });

  it("does not offer paper trading before the playground exists", () => {
    render(<PickCard pick={pick()} />);
    expect(screen.getByRole("button", { name: /paper trade/i })).toBeDisabled();
  });

  it("opens the stock when the symbol is clicked", () => {
    let opened = "";
    render(<PickCard pick={pick()} onOpen={(s) => (opened = s)} />);
    screen.getByText("RELIANCE").click();
    expect(opened).toBe("RELIANCE");
  });
});

describe("StatusPill", () => {
  it.each(["live", "candidate", "decaying", "retired", "rejected"])("renders %s", (s) => {
    render(<StatusPill status={s} />);
    expect(screen.getByTestId("status-pill")).toHaveTextContent(s);
  });
});

describe("StaleBanner", () => {
  it("is absent when data is fresh", () => {
    const { container } = render(<StaleBanner warning={null} />);
    expect(container).toBeEmptyDOMElement();
  });
  it("is an alert carrying the server's message", () => {
    render(<StaleBanner warning={{ job: "ingest_nse_prices", since: null, message: "Data is stale." }} />);
    expect(within(screen.getByRole("alert")).getByText(/Data is stale/)).toBeInTheDocument();
  });
});

describe("EquityChart", () => {
  it("draws both lines on a shared scale", () => {
    render(<EquityChart strategy={[100, 110, 125]} benchmark={[100, 104, 108]} benchmarkName="Nifty 500" />);
    expect(screen.getByTestId("strategy-line")).toBeInTheDocument();
    expect(screen.getByTestId("benchmark-line")).toBeInTheDocument();
    expect(screen.getByText("Nifty 500")).toBeInTheDocument();
  });

  it("omits the benchmark, and says so, rather than drawing a flat line", () => {
    render(<EquityChart strategy={[100, 110, 125]} benchmark={[]} benchmarkName="Nifty 500" />);
    expect(screen.queryByTestId("benchmark-line")).not.toBeInTheDocument();
    expect(screen.getByText(/no benchmark for this span/)).toBeInTheDocument();
  });

  it("says so when there is no curve at all", () => {
    render(<EquityChart strategy={[]} benchmark={[]} benchmarkName="Nifty 500" />);
    expect(screen.getByText("No backtest curve yet.")).toBeInTheDocument();
  });

  it("keeps every point inside the viewBox", () => {
    render(<EquityChart strategy={[50, 400, 5]} benchmark={[]} benchmarkName="x" />);
    const pts = screen.getByTestId("strategy-line").getAttribute("points")!.split(" ");
    for (const p of pts) {
      const [x, y] = p.split(",").map(Number) as [number, number];
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(380);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(120);
    }
  });
});
