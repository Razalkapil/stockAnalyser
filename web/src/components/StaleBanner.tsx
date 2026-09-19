import type { Status } from "../lib/api/types";
import { color, font, tint } from "../lib/theme";

/** The red banner from the design. Shown whenever the data is behind where the calendar says. */
export function StaleBanner({ warning }: { warning: Status["staleWarning"] }) {
  if (!warning) return null;
  return (
    <div
      role="alert"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 18px",
        background: tint.negative(0.1),
        borderBottom: `1px solid ${tint.negative(0.3)}`,
        color: color.negative,
        font: `500 11.5px ${font.sans}`,
        flex: "none",
      }}
    >
      <span>⚠</span> {warning.message}
    </div>
  );
}
