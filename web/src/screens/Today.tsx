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
const PREVIEWS_KEY = "stk.todayPreviews";

// A remembered layout is a per-viewer convenience; storage may be unavailable, so it is optional.
function readLayout(): Layout {
  try {
    return localStorage.getItem(LAYOUT_KEY) === "columns" ? "columns" : "tabs";
  } catch {
    return "tabs";
  }
}

// Whether previews are expanded is a per-viewer convenience; null means "never chosen".
function readPreviewsOpen(): boolean | null {
  try {
    const v = localStorage.getItem(PREVIEWS_KEY);
    return v === "open" ? true : v === "closed" ? false : null;
  } catch {
    return null;
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

// Setups DID pass here; the strategy that found them has not passed the promotion gate.
const noPicksButPreviews = (
  <EmptyState title="No promoted picks for this horizon">
    No strategy for this horizon has passed the promotion gate, so there is nothing to recommend.
    What the unapproved ones would have picked is listed below.
  </EmptyState>
);

function sortPreviews(rows: PreviewPick[]): PreviewPick[] {
  return [...rows].sort((a, b) => b.score - a.score);
}

const cardGrid = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill,minmax(340px,1fr))",
  gap: 14,
} as const;

/**
 * The previews for ONE horizon, kept as their own labelled block after the picks -- never
 * interleaved with them. The separation is what stops a preview reading as a recommendation.
 */
function PreviewBlock({
  rows,
  open,
  onToggle,
  onOpen,
  stacked,
}: {
  rows: PreviewPick[];
  open: boolean;
  onToggle: () => void;
  onOpen: (symbol: string) => void;
  stacked?: boolean;
}) {
  if (rows.length === 0) return null;
  return (
    <div data-testid="preview-block" style={{ marginTop: stacked ? 4 : 24 }}>
      <div
        role="button"
        onClick={onToggle}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          cursor: "pointer",
          paddingBottom: 8,
          borderBottom: `1px solid ${color.border}`,
        }}
      >
        <span style={{ font: `600 12px ${font.sans}`, color: color.textSecondary }}>
          {open ? "▾" : "▸"} Preview — not promoted
        </span>
        <span style={{ font: `500 10.5px ${font.mono}`, color: color.textFaint }}>{rows.length}</span>
      </div>
      {open && (
        <>
          <div
            style={{
              font: `400 11.5px ${font.sans}`,
              color: color.textFaint,
              margin: "8px 0 12px",
              lineHeight: 1.5,
            }}
          >
            What strategies that have <em>not</em> passed the promotion gate would buy. Not
            recommendations, and not tracked.
          </div>
          <div style={stacked ? { display: "flex", flexDirection: "column", gap: 10 } : cardGrid}>
            {sortPreviews(rows).map((p) => (
              <PreviewCard key={`${p.strategyId}-${p.symbol}`} pick={p} onOpen={onOpen} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function Today() {
  const { data, isLoading, error } = usePicks();
  const { data: previewData } = usePreviews();
  const nav = useNavigate();
  const [layout, setLayout] = useState<Layout>(readLayout);
  const [chosenTab, setChosenTab] = useState<HorizonId | null>(null);
  const [sort, setSort] = useState<Sort>("score");
  const [chosenOpen, setChosenOpen] = useState<boolean | null>(readPreviewsOpen);

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
  const previewsBy = (h: HorizonId) => previews.filter((p) => p.horizon === h);
  const signalDate = picks[0]?.signalDate ?? previews[0]?.signalDate;

  // With nothing promoted the previews ARE the page, so they start open; once real picks
  // exist they are secondary and start closed. An explicit choice always wins.
  const previewsOpen = chosenOpen ?? picks.length === 0;
  const togglePreviews = () => {
    const next = !previewsOpen;
    setChosenOpen(next);
    try {
      localStorage.setItem(PREVIEWS_KEY, next ? "open" : "closed");
    } catch {
      /* not remembered */
    }
  };

  // Land on a tab that has something in it rather than an empty default.
  const firstWith = (n: (h: HorizonId) => number) => horizons.find((h) => n(h.id) > 0)?.id;
  const active: HorizonId =
    chosenTab ??
    firstWith((h) => picks.filter((p) => p.horizon === h).length) ??
    firstWith((h) => previewsBy(h).length) ??
    "short_term";

  const hasRows = picks.length > 0 || previews.length > 0;

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
            ? "No strategy has beaten the Nifty 500 in enough out-of-sample windows to pass the promotion gate, so nothing here is a recommendation. What the strategies that did not pass would have bought is listed under each horizon."
            : "Nothing has been scanned. Promote a strategy, then run `stk scan` — or run `stk strategies preview` to see what the unapproved ones would pick."}
        </EmptyState>
      )}

      {hasRows && layout === "tabs" && (
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
                onClick={() => setChosenTab(h.id)}
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
                {previewsBy(h.id).length > 0 && (
                  <span style={{ opacity: 0.45, font: `500 10.5px ${font.mono}` }}>
                    {" "}
                    +{previewsBy(h.id).length} preview
                  </span>
                )}
              </div>
            ))}
          </div>
          {byHorizon(active).length ? (
            <div style={cardGrid}>
              {byHorizon(active).map((p) => (
                <PickCard key={p.id} pick={p} onOpen={(s) => nav(`/stocks/${s}`)} />
              ))}
            </div>
          ) : previewsBy(active).length ? (
            noPicksButPreviews
          ) : (
            noPicks
          )}
          <PreviewBlock
            rows={previewsBy(active)}
            open={previewsOpen}
            onToggle={togglePreviews}
            onOpen={(s) => nav(`/stocks/${s}`)}
          />
        </>
      )}

      {hasRows && layout === "columns" && (
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
              <PreviewBlock
                stacked
                rows={previewsBy(h.id)}
                open={previewsOpen}
                onToggle={togglePreviews}
                onOpen={(s) => nav(`/stocks/${s}`)}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
