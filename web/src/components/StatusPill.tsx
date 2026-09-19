import { color, font, statusColors } from "../lib/theme";

export function StatusPill({ status }: { status: string }) {
  const c = statusColors[status] ?? { bg: "rgba(139,150,163,0.15)", fg: color.textMuted };
  // "rejected" is the promotion gate's word; the design's palette calls that state "retired".
  const label = status === "rejected" ? "rejected" : status;
  return (
    <span
      data-testid="status-pill"
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 4,
        background: c.bg,
        color: c.fg,
        font: `600 10.5px ${font.sans}`,
        textTransform: "capitalize",
      }}
    >
      {label}
    </span>
  );
}
