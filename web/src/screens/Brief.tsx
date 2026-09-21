import { useEffect, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { useBrief, useBriefs, useGenerateBrief } from "../lib/api/hooks";
import type { BriefState } from "../lib/api/types";
import { fmtDate } from "../lib/format";
import { color, font, tint } from "../lib/theme";

const card = {
  background: color.panel,
  border: `1px solid ${color.border}`,
  borderRadius: 8,
  padding: "14px 16px",
} as const;
const cardTitle = { font: `600 12.5px ${font.sans}`, marginBottom: 8 } as const;

/**
 * What each state means on screen. "pending" used to be the only answer for every one of
 * these, which told you nothing and offered you nothing to do about it.
 */
const stateText: Record<BriefState, { badge: string; title: string; body: string }> = {
  ready: { badge: "", title: "", body: "" },
  pending: {
    badge: "pending",
    title: "This brief has not been generated yet",
    body: "It is written by the evening AI review after market close (after 15:30 IST).",
  },
  queued: {
    badge: "queued",
    title: "Queued",
    body: "Waiting for the worker. Run `stk ai worker --once` to pick it up now.",
  },
  running: { badge: "running", title: "Generating…", body: "The review is running." },
  skipped: {
    badge: "skipped",
    title: "Nothing to review",
    body: "The review ran and had no work to do.",
  },
  failed: { badge: "failed", title: "The review did not complete", body: "" },
  invalid_output: {
    badge: "invalid",
    title: "The model's reply was rejected",
    body: "It did not survive validation, so nothing was stored. Generating again is safe.",
  },
};

/** An unknown or absent state reads as "pending": a newer API must never blank the screen. */
const describe = (st: string | undefined) => stateText[st as BriefState] ?? stateText.pending;
const badgeOf = (st: string | undefined) => badgeColor[st as BriefState] ?? color.warning;

const badgeColor: Record<BriefState, string> = {
  ready: color.positive,
  pending: color.warning,
  queued: color.accent,
  running: color.accent,
  skipped: color.textMuted,
  failed: color.negative,
  invalid_output: color.negative,
};

function EmptyList({ title, children }: { title: string; children: string }) {
  return (
    <div style={{ font: `400 12px ${font.sans}`, color: color.textFaint }}>
      {title}
      {children}
    </div>
  );
}

export function Brief() {
  const { data: list } = useBriefs();
  const [day, setDay] = useState<string | null>(null);
  useEffect(() => {
    if (!day && list?.length) setDay(list[0]?.date ?? null);
  }, [list, day]);
  const { data: brief } = useBrief(day);
  const generate = useGenerateBrief(day);

  const state = brief?.state;
  const inFlight = state === "queued" || state === "running" || generate.isPending;
  const text = describe(state);

  return (
    <div style={{ padding: "20px 24px 40px", display: "grid", gridTemplateColumns: "220px 1fr", gap: 18 }}>
      <div>
        <div style={{ font: `600 15px ${font.sans}`, marginBottom: 12 }}>Market brief</div>
        {list?.length === 0 && (
          <div style={{ font: `400 12px ${font.sans}`, color: color.textFaint }}>
            No recent trading days to show.
          </div>
        )}
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
                <span
                  style={{
                    marginLeft: 8,
                    color: badgeOf(b.state),
                    font: `500 10px ${font.mono}`,
                  }}
                >
                  {describe(b.state).badge}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      <div>
        {brief && brief.pending && (
          <>
            <EmptyState title={text.title}>
              {brief.stateReason ? `${text.body} ${brief.stateReason}.` : text.body}
            </EmptyState>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 14 }}>
              <button
                type="button"
                disabled={inFlight}
                onClick={() => generate.mutate()}
                style={{
                  background: inFlight ? color.inset : tint.accent(0.18),
                  border: `1px solid ${inFlight ? color.border : color.accent}`,
                  color: inFlight ? color.textMuted : color.accentHover,
                  font: `500 12px ${font.sans}`,
                  borderRadius: 5,
                  padding: "7px 12px",
                  cursor: inFlight ? "default" : "pointer",
                }}
              >
                {inFlight ? "Queued…" : "Generate now"}
              </button>
              <span style={{ font: `400 11.5px ${font.sans}`, color: color.textFaint }}>
                Queues the review; <code>stk ai worker</code> runs it.
              </span>
            </div>
            {generate.error && (
              <div role="alert" style={{ color: color.negative, marginTop: 8, font: `400 12px ${font.sans}` }}>
                {generate.error.message}
              </div>
            )}
          </>
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
              {brief.notablePicks.length === 0 && (
                <EmptyList title="None called out ">for this day.</EmptyList>
              )}
              {brief.notablePicks.map((p, i) => (
                <div key={i} style={{ font: `400 12px ${font.sans}`, marginBottom: 6 }}>
                  <span style={{ font: `600 12px ${font.mono}` }}>{p.symbol}</span>{" "}
                  <span style={{ color: color.textSecondary }}>{p.note}</span>
                </div>
              ))}
            </div>
            <div style={card}>
              <div style={cardTitle}>Conflicts flagged</div>
              {brief.conflicts.length === 0 && (
                <EmptyList title="No conflicts flagged ">between today's picks.</EmptyList>
              )}
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
              {brief.positionNotes.length === 0 && (
                <EmptyList title="No open playground positions ">to comment on.</EmptyList>
              )}
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
