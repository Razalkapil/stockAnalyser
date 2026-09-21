import type { PreviewPick } from "../lib/api/types";
import { fmtINR, fmtScore } from "../lib/format";
import { color, font, tint } from "../lib/theme";
import { Num } from "./Num";
import { useTicket } from "./TicketContext";

const label = {
  font: `500 9px ${font.sans}`,
  color: color.textFaint,
  textTransform: "uppercase" as const,
  marginBottom: 2,
};

function Cell({ name, children }: { name: string; children: string }) {
  return (
    <div>
      <div style={label}>{name}</div>
      <Num>{children}</Num>
    </div>
  );
}

/**
 * A preview is NOT a pick, and the card says so rather than relying on where it sits: a
 * dashed border, no live or backtest performance figures (the strategy has none worth
 * quoting), and the strategy's actual status on the badge. It keeps the paper-trade button,
 * because trying an unapproved idea in the sandbox is exactly what the sandbox is for.
 */
export function PreviewCard({
  pick: p,
  onOpen,
}: {
  pick: PreviewPick;
  onOpen?: (symbol: string) => void;
}) {
  const { openTicket } = useTicket();
  return (
    <div
      data-testid="preview-card"
      style={{
        background: color.sunken,
        border: `1px dashed ${color.borderSubtle}`,
        borderRadius: 8,
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              onClick={() => onOpen?.(p.symbol)}
              style={{
                font: `600 14px ${font.mono}`,
                color: color.textSecondary,
                cursor: onOpen ? "pointer" : "default",
              }}
            >
              {p.symbol}
            </span>
            <span
              style={{
                font: `500 9px ${font.mono}`,
                color: color.textFaint,
                border: `1px solid ${color.borderSubtle}`,
                borderRadius: 3,
                padding: "0 4px",
              }}
            >
              {p.exch}
            </span>
          </div>
          <div style={{ font: `400 11.5px ${font.sans}`, color: color.textMuted, marginTop: 2 }}>
            {p.company}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ font: `700 15px ${font.mono}`, color: color.textMuted }}>
            {fmtScore(p.score)}
          </div>
          <div style={{ font: `500 9.5px ${font.sans}`, color: color.textFaint }}>score</div>
        </div>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          font: `500 11px ${font.sans}`,
          color: color.textMuted,
        }}
      >
        {p.strategy}
        <span
          style={{
            font: `500 9px ${font.mono}`,
            color: color.warning,
            background: tint.warning(0.1),
            borderRadius: 3,
            padding: "1px 5px",
          }}
        >
          {p.strategyStatus}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        <Cell name="Ref">{fmtINR(p.ref)}</Cell>
        <Cell name="Stop">{fmtINR(p.stop)}</Cell>
        <Cell name="Target">{fmtINR(p.target)}</Cell>
      </div>

      <div
        style={{
          font: `400 12px ${font.sans}`,
          color: color.textMuted,
          lineHeight: 1.5,
          fontStyle: "italic",
        }}
      >
        {p.reason}
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 2,
        }}
      >
        <span style={{ font: `500 10.5px ${font.sans}`, color: color.textFaint }}>{p.window}</span>
        <button
          onClick={() =>
            openTicket({
              symbol: p.symbol,
              side: "buy",
              ref: p.ref,
              stop: p.stop,
              target: p.target,
              note: `PREVIEW (${p.strategyStatus}) ${p.strategy}: ${p.reason}`,
            })
          }
          style={{
            padding: "6px 12px",
            borderRadius: 5,
            background: color.inset,
            color: color.textSecondary,
            font: `600 11px ${font.sans}`,
            border: `1px solid ${color.border}`,
            cursor: "pointer",
          }}
        >
          Paper trade this
        </button>
      </div>
    </div>
  );
}
