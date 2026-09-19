import { EmptyState } from "../components/EmptyState";
import { color, font } from "../lib/theme";

/** Built in the next phase. An honest placeholder, not a mock-up with invented numbers. */
export function Playground() {
  return (
    <div style={{ padding: "20px 24px 40px" }}>
      <div style={{ font: `600 15px ${font.sans}`, marginBottom: 14 }}>Playground</div>
      <EmptyState title="Paper trading is not built yet">
        <span style={{ color: color.textFaint }}>
          Portfolios, orders and the delayed-feed fill engine arrive in the next phase.
        </span>
      </EmptyState>
    </div>
  );
}
