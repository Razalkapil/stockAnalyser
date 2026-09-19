import { useEffect, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { useBrief, useBriefs } from "../lib/api/hooks";
import { fmtDate } from "../lib/format";
import { color, font, tint } from "../lib/theme";

const card = {
  background: color.panel,
  border: `1px solid ${color.border}`,
  borderRadius: 8,
  padding: "14px 16px",
} as const;
const cardTitle = { font: `600 12.5px ${font.sans}`, marginBottom: 8 } as const;

export function Brief() {
  const { data: list } = useBriefs();
  const [day, setDay] = useState<string | null>(null);
  useEffect(() => {
    if (!day && list?.length) setDay(list[0]?.date ?? null);
  }, [list, day]);
  const { data: brief } = useBrief(day);

  return (
    <div style={{ padding: "20px 24px 40px", display: "grid", gridTemplateColumns: "220px 1fr", gap: 18 }}>
      <div>
        <div style={{ font: `600 15px ${font.sans}`, marginBottom: 12 }}>Market brief</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {list?.map((b) => (
            <div
              key={b.date}
              role="button"
              onClick={() => setDay(b.date)}
              style={{
                padding: "8px 10px",
                borderRadius: 5,
                cursor: "pointer",
                font: `500 12px ${font.sans}`,
                ...(day === b.date
                  ? { background: color.inset, color: color.text }
                  : { color: color.textMuted }),
              }}
            >
              {fmtDate(b.date)}
              {b.pending && (
                <span style={{ marginLeft: 8, color: color.warning, font: `500 10px ${font.mono}` }}>
                  pending
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      <div>
        {brief?.pending && (
          <EmptyState title="This brief has not been generated yet">
            It is written by the evening AI review after market close (after 15:30 IST).
          </EmptyState>
        )}
        {brief && !brief.pending && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div>
              <div style={{ font: `600 15px ${font.sans}` }}>{fmtDate(brief.date)}</div>
              {brief.generatedAt && (
                <div style={{ font: `400 12px ${font.sans}`, color: color.textMuted, marginTop: 2 }}>
                  Generated {brief.generatedAt}
                </div>
              )}
            </div>
            <div style={card}>
              <div style={cardTitle}>Overview</div>
              <div style={{ font: `400 12.5px ${font.sans}`, color: color.textSecondary, lineHeight: 1.6 }}>
                {brief.overview}
              </div>
            </div>
            <div style={card}>
              <div style={cardTitle}>Notable picks</div>
              {brief.notablePicks.map((p, i) => (
                <div key={i} style={{ font: `400 12px ${font.sans}`, marginBottom: 6 }}>
                  <span style={{ font: `600 12px ${font.mono}` }}>{p.symbol}</span>{" "}
                  <span style={{ color: color.textSecondary }}>{p.note}</span>
                </div>
              ))}
            </div>
            <div style={card}>
              <div style={cardTitle}>Conflicts flagged</div>
              {brief.conflicts.map((c, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    gap: 6,
                    font: `400 12px ${font.sans}`,
                    color: color.warning,
                    background: tint.warning(0.08),
                    borderRadius: 5,
                    padding: "6px 8px",
                    marginBottom: 6,
                  }}
                >
                  <span>⚑</span>
                  <span>{c}</span>
                </div>
              ))}
            </div>
            <div style={card}>
              <div style={cardTitle}>Your open positions</div>
              {brief.positionNotes.map((p, i) => (
                <div key={i} style={{ font: `400 12px ${font.sans}`, marginBottom: 6 }}>
                  <span style={{ font: `600 12px ${font.mono}` }}>{p.symbol}</span>{" "}
                  <span style={{ color: color.textSecondary }}>{p.note}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
