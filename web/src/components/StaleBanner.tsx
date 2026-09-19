import type { Status } from "../lib/api/types";
import { color, font, tint } from "../lib/theme";

const bar = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 18px",
  background: tint.negative(0.1),
  borderBottom: `1px solid ${tint.negative(0.3)}`,
  color: color.negative,
  font: `500 11.5px ${font.sans}`,
  flex: "none",
} as const;

/**
 * The red banner from the design. Shown whenever the data is behind where the calendar says,
 * and whenever a scheduled step's latest run failed -- a failure at 21:00 must be visible the
 * next morning without reading a log.
 */
export function StaleBanner({
  warning,
  alerts = [],
}: {
  warning: Status["staleWarning"];
  alerts?: Status["jobAlerts"];
}) {
  if (!warning && alerts.length === 0) return null;
  return (
    <div role="alert" style={{ flex: "none" }}>
      {warning && (
        <div style={bar}>
          <span>⚠</span> {warning.message}
        </div>
      )}
      {alerts.map((a) => (
        <div key={`${a.job}-${a.businessDate}`} style={bar}>
          <span>⚠</span>
          <span>
            {a.job.replace(/^(nightly|weekly)\./, "$1 · ")} {a.status}
            {a.businessDate ? ` (${a.businessDate})` : ""}: {a.message}
          </span>
        </div>
      ))}
    </div>
  );
}
