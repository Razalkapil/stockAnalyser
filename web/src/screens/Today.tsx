import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { PickCard } from "../components/PickCard";
import { PreviewCard } from "../components/PreviewCard";
import { Segmented } from "../components/Segmented";
import { usePicks, usePreviews } from "../lib/api/hooks";
import type { Pick, PreviewPick } from "../lib/api/types";
import { fmtDate } from "../lib/format";
import { color, font, horizons, type HorizonId } from "../lib/theme";

type Layout = "tabs" | "columns";
type Sort = "score" | "strategy";
const LAYOUT_KEY = "stk.todayLayout";

// A remembered layout is a per-viewer convenience; storage may be unavailable, so it is optional.
function readLayout(): Layout {
  try {
    return localStorage.getItem(LAYOUT_KEY) === "columns" ? "columns" : "tabs";
  } catch {
    return "tabs";
  }
}

function sortPicks(picks: Pick[], by: Sort): Pick[] {
  return [...picks].sort((a, b) =>
    by === "score" ? b.score - a.score : a.strategy.localeCompare(b.strategy) || b.score - a.score,
  );
}

const noPicks = (
  <EmptyState title="No qualifying picks today">
    No setups passed strategy filters for this horizon in tonight's run.
  </EmptyState>
);

function sortPreviews(rows: PreviewPick[]): PreviewPick[] {
  return [...rows].sort((a, b) => b.score - a.score);
}

export function Today() {
  const { data, isLoading, error } = usePicks();
  const { data: previewData } = usePreviews();
  const nav = useNavigate();
  const [layout, setLayout] = useState<Layout>(readLayout);
  const [active, setActive] = useState<HorizonId>("short_term");
  const [sort, setSort] = useState<Sort>("score");
  const [showPreviews, setShowPreviews] = useState(false);

  const changeLayout = (l: Layout) => {
    setLayout(l);
    try {
      localStorage.setItem(LAYOUT_KEY, l);
    } catch {
      /* not remembered */
    }
  };

  const picks = data ?? [];
  const previews = previewData ?? [];
  const byHorizon = (h: HorizonId) => sortPicks(picks.filter((p) => p.horizon === h), sort);
  const signalDate = picks[0]?.signalDate ?? previews[0]?.signalDate;

  return (
    <div style={{ padding: "20px 24px 40px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div>
          <div style={{ font: `600 15px ${font.sans}` }}>Today's picks</div>
          <div style={{ font: `400 12px ${font.sans}`, color: color.textMuted, marginTop: 2 }}>
            {signalDate ? `Signals from the ${fmtDate(signalDate)} close` : "No signals yet"}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Segmented
            options={[
              { id: "tabs", label: "Tabs" },
              { id: "columns", label: "Columns" },
            ]}
            value={layout}
            onChange={changeLayout}
          />
          <select
            aria-label="Sort picks"
            value={sort}
            onChange={(e) => setSort(e.target.value as Sort)}
            style={{
              background: color.inset,
              border: `1px solid ${color.border}`,
              color: color.textSecondary,
              font: `500 11.5px ${font.sans}`,
              borderRadius: 5,
              padding: "6px 8px",
            }}
          >
            <option value="score">Sort: Score</option>
            <option value="strategy">Sort: Strategy</option>
          </select>
        </div>
      </div>

      {isLoading && <div style={{ color: color.textFaint }}>Loading…</div>}
      {error && (
        <div role="alert" style={{ color: color.negative }}>
          Could not load picks: {error.message}
        </div>
      )}

      {!isLoading && !error && picks.length === 0 && (
        <EmptyState title="No picks yet">
          {previews.length > 0
            ? "No strategy has passed the promotion gate, so nothing here is a recommendation. The preview below shows what the strategies that did not pass would have bought."
            : "Nothing has been scanned. Promote a strategy, then run `stk scan` — or run `stk strategies preview` to see what the unapproved ones would pick."}
        </EmptyState>
      )}

      {picks.length > 0 && layout === "tabs" && (
        <>
          <div
            style={{
              display: "flex",
              gap: 4,
              marginBottom: 16,
              borderBottom: `1px solid ${color.border}`,
            }}
          >
            {horizons.map((h) => (
              <div
                key={h.id}
                role="tab"
                aria-selected={active === h.id}
                onClick={() => setActive(h.id)}
                style={{
                  padding: "9px 4px",
                  marginRight: 20,
                  font: `500 12.5px ${font.sans}`,
                  cursor: "pointer",
                  borderBottom: `2px solid ${active === h.id ? color.accent : "transparent"}`,
                  color: active === h.id ? color.text : color.textMuted,
                }}
              >
                {h.label}{" "}
                <span style={{ opacity: 0.6, font: `500 10.5px ${font.mono}` }}>
                  {byHorizon(h.id).length}
                </span>
              </div>
            ))}
          </div>
          {byHorizon(active).length ? (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill,minmax(340px,1fr))",
                gap: 14,
              }}
            >
              {byHorizon(active).map((p) => (
                <PickCard key={p.id} pick={p} onOpen={(s) => nav(`/stocks/${s}`)} />
              ))}
            </div>
          ) : (
            noPicks
          )}
        </>
      )}

      {picks.length > 0 && layout === "columns" && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4,1fr)",
            gap: 14,
            alignItems: "start",
          }}
        >
          {horizons.map((h) => (
            <div key={h.id} style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
              <div
                style={{
                  font: `600 12px ${font.sans}`,
                  color: color.textSecondary,
                  paddingBottom: 8,
                  borderBottom: `1px solid ${color.border}`,
                }}
              >
                {h.label}{" "}
                <span style={{ color: color.textFaint, font: `500 10.5px ${font.mono}` }}>
                  {byHorizon(h.id).length}
                </span>
              </div>
              {byHorizon(h.id).length ? (
                byHorizon(h.id).map((p) => (
                  <PickCard key={p.id} pick={p} onOpen={(s) => nav(`/stocks/${s}`)} />
                ))
              ) : (
                <div
                  style={{
                    padding: 24,
                    textAlign: "center",
                    color: color.textFaint,
                    font: `400 12px ${font.sans}`,
                    border: `1px dashed ${color.border}`,
                    borderRadius: 8,
                  }}
                >
                  No picks today
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {previews.length > 0 && (
        <div style={{ marginTop: picks.length > 0 ? 28 : 20 }}>
          <div
            role="button"
            onClick={() => setShowPreviews((v) => !v)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              cursor: "pointer",
              paddingBottom: 10,
              borderBottom: `1px solid ${color.border}`,
            }}
          >
            <span style={{ font: `600 12.5px ${font.sans}`, color: color.textSecondary }}>
              {showPreviews ? "▾" : "▸"} Preview — not promoted
            </span>
            <span style={{ font: `500 10.5px ${font.mono}`, color: color.textFaint }}>
              {previews.length}
            </span>
          </div>
          <div
            style={{
              font: `400 11.5px ${font.sans}`,
              color: color.textFaint,
              margin: "8px 0 14px",
              lineHeight: 1.5,
            }}
          >
            What strategies that have <em>not</em> passed the promotion gate would buy today.
            These are not recommendations and are not tracked — they exist so a rejected rule can
            still be watched. Generated by <code>stk strategies preview</code>.
          </div>
          {showPreviews && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill,minmax(340px,1fr))",
                gap: 14,
              }}
            >
              {sortPreviews(previews).map((p) => (
                <PreviewCard
                  key={`${p.strategyId}-${p.symbol}`}
                  pick={p}
                  onOpen={(sym) => nav(`/stocks/${sym}`)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
