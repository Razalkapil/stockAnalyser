import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useStatus, useStockSearch } from "../lib/api/hooks";
import { setToken } from "../lib/api/client";
import { fmtDate } from "../lib/format";
import { color, font, tint } from "../lib/theme";

const NAV = [
  { to: "/", label: "Today", end: true },
  { to: "/stocks", label: "Stocks", end: false },
  { to: "/strategy", label: "Strategy lab", end: false },
  { to: "/brief", label: "Market brief", end: false },
  { to: "/playground", label: "Playground", end: false },
];

const chip = {
  padding: "3px 8px",
  borderRadius: 4,
  background: color.inset,
  border: `1px solid ${color.border}`,
} as const;

function SearchBox() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const { data } = useStockSearch(q);
  const go = (symbol: string) => {
    setQ("");
    setOpen(false);
    nav(`/stocks/${symbol}`);
  };
  return (
    <div style={{ position: "relative" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          background: color.inset,
          border: `1px solid ${color.border}`,
          borderRadius: 5,
          padding: "4px 10px",
          width: 220,
        }}
      >
        <span style={{ color: color.textFaint, fontSize: 12 }}>⌕</span>
        <input
          aria-label="Search symbol or company"
          value={q}
          placeholder="Search symbol or company…"
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && data?.[0]) go(data[0].symbol);
          }}
          style={{
            background: "transparent",
            border: "none",
            outline: "none",
            color: color.text,
            font: `400 12px ${font.sans}`,
            width: "100%",
          }}
        />
        <span
          style={{
            font: `500 9px ${font.mono}`,
            color: color.textFaint,
            border: `1px solid ${color.borderSubtle}`,
            borderRadius: 3,
            padding: "1px 4px",
          }}
        >
          NSE
        </span>
      </div>
      {open && q.trim() && (
        <div
          role="listbox"
          style={{
            position: "absolute",
            top: 34,
            right: 0,
            width: 300,
            background: color.panel,
            border: `1px solid ${color.border}`,
            borderRadius: 6,
            zIndex: 10,
            maxHeight: 320,
            overflowY: "auto",
          }}
        >
          {data?.length ? (
            data.map((h) => (
              <div
                key={h.symbol}
                role="option"
                onMouseDown={() => go(h.symbol)}
                style={{ padding: "8px 12px", cursor: "pointer", borderBottom: `1px solid ${color.borderRow}` }}
              >
                <span style={{ font: `600 12px ${font.mono}`, color: color.text }}>{h.symbol}</span>
                <span style={{ font: `400 11.5px ${font.sans}`, color: color.textMuted, marginLeft: 8 }}>
                  {h.company}
                </span>
              </div>
            ))
          ) : (
            <div style={{ padding: 12, font: `400 12px ${font.sans}`, color: color.textFaint }}>
              No match
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function TopBar() {
  const { data: status } = useStatus();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        padding: "0 18px",
        height: 50,
        background: color.panel,
        borderBottom: `1px solid ${color.border}`,
        flex: "none",
      }}
    >
      <div style={{ font: `700 13px/1 ${font.mono}`, letterSpacing: 0.5, whiteSpace: "nowrap" }}>
        RZ<span style={{ color: color.accent }}>•</span>TERMINAL
      </div>
      <nav style={{ display: "flex", gap: 2 }}>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            style={({ isActive }) => ({
              padding: "8px 14px",
              borderRadius: 5,
              font: `500 12.5px ${font.sans}`,
              textDecoration: "none",
              ...(isActive
                ? { background: color.active, color: color.text }
                : { color: color.textMuted }),
            })}
          >
            {n.label}
          </NavLink>
        ))}
      </nav>
      <div style={{ flex: 1 }} />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          font: `500 11px ${font.mono}`,
          color: color.textMuted,
        }}
      >
        <div style={{ ...chip, display: "flex", alignItems: "center", gap: 5 }}>
          <div
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: status?.marketOpen ? color.positive : color.textFaint,
            }}
          />
          {status?.marketLabel ?? "…"}
        </div>
        <div style={chip} title="Latest trading day in the price lake">
          {status?.dataAsOf ? `Data ${fmtDate(status.dataAsOf)}` : "No data"}
        </div>
        {status?.delayedFeed && (
          <div
            style={{
              ...chip,
              background: tint.warning(),
              color: color.warning,
              border: `1px solid ${tint.warning(0.3)}`,
            }}
          >
            ~{status.delayedFeed.lagMinutes} min delayed
          </div>
        )}
      </div>
      <SearchBox />
      <button
        onClick={() => setToken(null)}
        title="Sign out"
        style={{
          background: "transparent",
          border: "none",
          color: color.textFaint,
          font: `500 11px ${font.sans}`,
          cursor: "pointer",
        }}
      >
        Sign out
      </button>
    </div>
  );
}
