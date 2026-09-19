import type { Pick } from "../lib/api/types";
import { fmtINR, fmtPct, fmtPlainPct, fmtScore } from "../lib/format";
import { color, font, tint } from "../lib/theme";
import { Num } from "./Num";

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

export function PickCard({ pick: p, onOpen }: { pick: Pick; onOpen?: (symbol: string) => void }) {
  return (
    <div
      data-testid="pick-card"
      style={{
        background: color.panel,
        border: `1px solid ${color.border}`,
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
              data-testid="pick-symbol"
              onClick={() => onOpen?.(p.symbol)}
              style={{
                font: `600 14px ${font.mono}`,
                color: color.text,
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
            {p.sector ? ` · ${p.sector}` : ""}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ font: `700 15px ${font.mono}`, color: color.accent }}>{fmtScore(p.score)}</div>
          <div style={{ font: `500 9.5px ${font.sans}`, color: color.textFaint }}>score</div>
        </div>
      </div>

      <div style={{ font: `500 11px ${font.sans}`, color: color.textSecondary }}>{p.strategy}</div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        <Cell name="Ref">{fmtINR(p.ref)}</Cell>
        <Cell name="Stop">{fmtINR(p.stop)}</Cell>
        <Cell name="Target">{fmtINR(p.target)}</Cell>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          font: `500 10.5px ${font.mono}`,
          color: color.textMuted,
          background: color.sunken,
          borderRadius: 5,
          padding: "6px 8px",
        }}
      >
        <span>
          BT {p.btCagr == null ? "—" : fmtPct(p.btCagr, 0)} / Live {fmtPct(p.liveReturn)}
          {p.approx && (
            <span style={{ color: color.warning, marginLeft: 6 }} title="Approximate backtest">
              approx
            </span>
          )}
        </span>
        <span>{p.hitRate == null ? "— hit" : `${fmtPlainPct(p.hitRate)} hit`}</span>
      </div>

      <div
        style={{
          font: `400 12px ${font.sans}`,
          color: color.textSecondary,
          lineHeight: 1.5,
          fontStyle: "italic",
        }}
      >
        {p.reason}
      </div>

      {p.conflict && (
        <div
          style={{
            display: "flex",
            gap: 6,
            alignItems: "flex-start",
            font: `400 11px ${font.sans}`,
            color: color.warning,
            background: tint.warning(0.08),
            borderRadius: 5,
            padding: "6px 8px",
          }}
        >
          <span>⚑</span>
          <span>{p.conflict}</span>
        </div>
      )}

      <div
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 2 }}
      >
        <span style={{ font: `500 10.5px ${font.sans}`, color: color.textFaint }}>{p.window}</span>
        <button
          disabled
          title="Paper trading arrives with the playground"
          style={{
            padding: "6px 12px",
            borderRadius: 5,
            background: color.active,
            color: color.accent,
            font: `600 11px ${font.sans}`,
            border: "none",
            opacity: 0.5,
            cursor: "not-allowed",
          }}
        >
          Paper trade this
        </button>
      </div>
    </div>
  );
}
