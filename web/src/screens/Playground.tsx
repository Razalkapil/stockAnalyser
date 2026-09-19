import { useEffect, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { EquityChart } from "../components/EquityChart";
import { Num } from "../components/Num";
import { useTicket } from "../components/TicketContext";
import {
  useCancelOrder,
  useCreatePortfolio,
  useJournal,
  usePortfolio,
  usePortfolios,
} from "../lib/api/hooks";
import type { OrderOut, PortfolioDetail, TradeOut } from "../lib/api/types";
import { fmtClock, fmtDate, fmtINR, fmtPct, fmtPlainPct } from "../lib/format";
import { color, font, pnlColor, tint } from "../lib/theme";

const panel = {
  background: color.panel,
  border: `1px solid ${color.border}`,
  borderRadius: 8,
  padding: 16,
} as const;
const section = {
  font: `500 10.5px ${font.sans}`,
  color: color.textFaint,
  textTransform: "uppercase" as const,
  letterSpacing: 0.4,
  marginBottom: 10,
};
const th = { font: `500 10px ${font.sans}`, color: color.textFaint, textTransform: "uppercase" as const };
const right = { textAlign: "right" as const };

function Tile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ ...panel, padding: "10px 12px" }}>
      <div style={{ font: `500 10px ${font.sans}`, color: color.textFaint, textTransform: "uppercase", marginBottom: 4 }}>
        {label}
      </div>
      <Num size={14} weight={600} color={tone ?? color.text}>
        {value}
      </Num>
    </div>
  );
}

function NewPortfolio({ onDone }: { onDone: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [capital, setCapital] = useState("1000000");
  const create = useCreatePortfolio();
  if (!open) {
    return (
      <div
        role="button"
        onClick={() => setOpen(true)}
        style={{
          padding: "7px 14px",
          borderRadius: 6,
          border: `1px dashed ${color.borderSubtle}`,
          color: color.textMuted,
          font: `500 12.5px ${font.sans}`,
          cursor: "pointer",
        }}
      >
        + New portfolio
      </div>
    );
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate(
          { name, startCapital: capital },
          {
            onSuccess: (p) => {
              setOpen(false);
              setName("");
              onDone(p.id);
            },
          },
        );
      }}
      style={{ display: "flex", gap: 6, alignItems: "center" }}
    >
      <input
        aria-label="Portfolio name"
        placeholder="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        autoFocus
        style={{ background: color.inset, border: `1px solid ${color.border}`, borderRadius: 5, padding: "6px 8px", color: color.text, font: `400 12px ${font.sans}`, width: 130 }}
      />
      <input
        aria-label="Starting capital"
        value={capital}
        onChange={(e) => setCapital(e.target.value)}
        style={{ background: color.inset, border: `1px solid ${color.border}`, borderRadius: 5, padding: "6px 8px", color: color.text, font: `500 12px ${font.mono}`, width: 110 }}
      />
      <button type="submit" disabled={!name.trim() || create.isPending} style={{ padding: "6px 10px", borderRadius: 5, border: "none", background: color.accent, color: "#fff", font: `600 11px ${font.sans}`, cursor: "pointer" }}>
        Create
      </button>
      <span onClick={() => setOpen(false)} style={{ cursor: "pointer", color: color.textFaint }}>
        ✕
      </span>
      {create.error && (
        <span role="alert" style={{ color: color.negative, font: `400 11.5px ${font.sans}` }}>
          {create.error.message}
        </span>
      )}
    </form>
  );
}

function Journal({ t }: { t: TradeOut }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(t.journalNote ?? "");
  const save = useJournal();
  if (editing) {
    return (
      <input
        aria-label="Journal note"
        value={text}
        autoFocus
        onChange={(e) => setText(e.target.value)}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            save.mutate({ id: t.id, note: text });
            setEditing(false);
          }
          if (e.key === "Escape") setEditing(false);
        }}
        style={{ width: "100%", background: color.inset, border: `1px solid ${color.border}`, borderRadius: 4, color: color.text, font: `400 11px ${font.sans}`, padding: "2px 6px" }}
      />
    );
  }
  return (
    <div
      onClick={() => setEditing(true)}
      title="Click to edit"
      style={{ color: color.textMuted, font: `400 11px ${font.sans}`, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", cursor: "text" }}
    >
      {t.journalNote || <span style={{ color: color.textFaint }}>add a note…</span>}
    </div>
  );
}

function OrderRow({ o }: { o: OrderOut }) {
  const cancel = useCancelOrder();
  const active = o.status === "open" || o.status === "pending_eod";
  const pending = o.status === "pending_eod";
  return (
    <div
      role="row"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 0.9fr 0.9fr 0.9fr 1.4fr 0.9fr 0.7fr",
        alignItems: "center",
        padding: "7px 0",
        borderBottom: `1px solid ${color.borderRow}`,
      }}
    >
      <div style={{ font: `600 12px ${font.mono}` }}>
        {o.symbol} <span style={{ color: o.side === "buy" ? color.positive : color.negative, font: `600 9px ${font.sans}` }}>{o.side.toUpperCase()}</span>
      </div>
      <div style={{ color: color.textMuted, font: `400 11px ${font.sans}` }}>
        {o.type} · {o.qty}
      </div>
      <div style={right}>
        <Num size={11.5}>{o.price != null ? fmtINR(o.price) : "mkt"}</Num>
      </div>
      <div>
        <span
          style={{
            display: "inline-block",
            padding: "2px 8px",
            borderRadius: 4,
            font: `600 10px ${font.sans}`,
            ...(pending
              ? { background: tint.warning(0.15), color: color.warning }
              : o.status === "open"
                ? { background: tint.accent(), color: color.accent }
                : o.status === "filled"
                  ? { background: tint.positive(), color: color.positive }
                  : { background: tint.muted(), color: color.textMuted }),
          }}
        >
          {pending ? "Pending" : o.status === "open" ? "Open" : o.status}
        </span>
      </div>
      <div style={{ color: color.warning, font: `400 10.5px ${font.sans}` }}>{o.statusNote}</div>
      <Num size={10.5} weight={400} color={color.textMuted}>
        {fmtClock(o.created)}
      </Num>
      <div>
        {active && (
          <span
            role="button"
            onClick={() => cancel.mutate(o.id)}
            style={{ color: color.accent, font: `500 11px ${font.sans}`, cursor: "pointer" }}
          >
            Cancel
          </span>
        )}
      </div>
    </div>
  );
}

function Detail({ p }: { p: PortfolioDetail }) {
  const openOrders = p.orders.filter((o) => o.status === "open" || o.status === "pending_eod");
  const stalePending = openOrders.some((o) => o.status === "pending_eod");
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 10, marginBottom: 16 }}>
        <Tile label="Current value" value={fmtINR(p.currentValue)} />
        <Tile label="Cash" value={fmtINR(p.cash)} />
        <Tile label="Invested" value={fmtINR(p.invested)} />
        <Tile label="Realised P&L" value={fmtINR(p.realisedPnl)} tone={pnlColor(p.realisedPnl)} />
        <Tile label="Unrealised P&L" value={fmtINR(p.unrealisedPnl)} tone={pnlColor(p.unrealisedPnl)} />
        <Tile label="Charges paid" value={fmtINR(p.charges)} tone={color.textMuted} />
        <Tile
          label="Return vs Nifty"
          value={`${fmtPct(p.returnPct)} / ${fmtPct(p.niftyReturnPct)}`}
          tone={pnlColor(p.returnPct)}
        />
        <Tile label="XIRR" value={p.xirr == null ? "—" : fmtPct(p.xirr)} tone={pnlColor(p.xirr)} />
        <Tile label="Max drawdown" value={p.maxDd == null ? "—" : fmtPlainPct(p.maxDd, 1)} tone={color.negative} />
        <Tile label="Win rate" value={fmtPlainPct(p.winRate)} tone={color.textMuted} />
      </div>

      {stalePending && (
        <div role="status" style={{ color: color.warning, background: tint.warning(0.08), border: `1px solid ${tint.warning(0.3)}`, borderRadius: 6, padding: "8px 12px", marginBottom: 16, font: `400 12px ${font.sans}` }}>
          The delayed feed is down for some symbols. Nothing fills on stale data — those orders will
          be decided by tonight's end-of-day bar.
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 16, marginBottom: 16 }}>
        <div style={panel}>
          <div style={section}>Portfolio value vs Nifty 500</div>
          {p.curve.length >= 2 ? (
            <EquityChart strategy={p.curve} benchmark={p.niftyCurve} benchmarkName="Nifty 500" />
          ) : (
            <div style={{ font: `400 12px ${font.sans}`, color: color.textFaint, padding: "18px 0" }}>
              The curve builds from nightly snapshots — check back after tonight's run.
            </div>
          )}
        </div>

        <div style={panel}>
          <div style={section}>Positions</div>
          {p.positions.length === 0 ? (
            <div style={{ padding: "24px 0", textAlign: "center", color: color.textFaint, font: `400 12px ${font.sans}` }}>
              No positions yet — place a paper trade to get started.
            </div>
          ) : (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 0.5fr 0.8fr 0.8fr 1fr 0.6fr", paddingBottom: 6, borderBottom: `1px solid ${color.border}` }}>
                <div style={th}>Sym</div>
                <div style={{ ...th, ...right }}>Qty</div>
                <div style={{ ...th, ...right }}>Avg</div>
                <div style={{ ...th, ...right }}>LTP</div>
                <div style={{ ...th, ...right }}>P&amp;L</div>
                <div style={{ ...th, ...right }}>Days</div>
              </div>
              {p.positions.map((x) => (
                <div key={x.symbol} style={{ display: "grid", gridTemplateColumns: "1fr 0.5fr 0.8fr 0.8fr 1fr 0.6fr", padding: "6px 0", borderBottom: `1px solid ${color.borderRow}` }}>
                  <div style={{ font: `600 12px ${font.mono}` }}>{x.symbol}</div>
                  <div style={{ ...right, color: color.textMuted }}><Num size={11.5}>{x.qty}</Num></div>
                  <div style={{ ...right, color: color.textMuted }}><Num size={11.5}>{fmtINR(x.avg, { symbol: false })}</Num></div>
                  <div style={right}><Num size={11.5}>{x.ltp == null ? "—" : fmtINR(x.ltp, { symbol: false })}</Num></div>
                  <div style={right}>
                    <Num size={11.5} color={pnlColor(x.pnl)}>
                      {x.pnl == null ? "—" : `${fmtINR(x.pnl)} ${fmtPct(x.pnlPct)}`}
                    </Num>
                  </div>
                  <div style={{ ...right, color: color.textMuted }}><Num size={11.5}>{x.days}</Num></div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      <div style={{ ...panel, marginBottom: 16 }}>
        <div style={section}>Open orders</div>
        {openOrders.length === 0 ? (
          <div style={{ padding: "16px 0", textAlign: "center", color: color.textFaint, font: `400 12px ${font.sans}` }}>
            No open orders.
          </div>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 0.9fr 0.9fr 0.9fr 1.4fr 0.9fr 0.7fr", paddingBottom: 6, borderBottom: `1px solid ${color.border}` }}>
              <div style={th}>Sym</div>
              <div style={th}>Type</div>
              <div style={{ ...th, ...right }}>Price</div>
              <div style={th}>Status</div>
              <div style={th}>&nbsp;</div>
              <div style={th}>Created</div>
              <div />
            </div>
            {openOrders.map((o) => (
              <OrderRow key={o.id} o={o} />
            ))}
          </>
        )}
      </div>

      <div style={panel}>
        <div style={section}>Trade history</div>
        {p.trades.length === 0 ? (
          <div style={{ padding: "16px 0", textAlign: "center", color: color.textFaint, font: `400 12px ${font.sans}` }}>
            No trades yet in this portfolio.
          </div>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "0.8fr 0.6fr 0.9fr 0.9fr 0.8fr 0.9fr 2fr", paddingBottom: 6, borderBottom: `1px solid ${color.border}` }}>
              <div style={th}>Sym</div>
              <div style={th}>Side</div>
              <div style={{ ...th, ...right }}>Fill</div>
              <div style={th}>Time</div>
              <div style={{ ...th, ...right }}>Charges</div>
              <div />
              <div style={th}>Note</div>
            </div>
            {p.trades.map((t) => (
              <div
                key={t.id}
                role="row"
                style={{ display: "grid", gridTemplateColumns: "0.8fr 0.6fr 0.9fr 0.9fr 0.8fr 0.9fr 2fr", alignItems: "center", padding: "7px 0", borderBottom: `1px solid ${color.borderRow}` }}
              >
                <div style={{ font: `600 12px ${font.mono}` }}>{t.symbol}</div>
                <div style={{ font: `600 11px ${font.sans}`, color: t.side === "buy" ? color.positive : color.negative }}>
                  {t.side.toUpperCase()}
                </div>
                <div style={right}><Num size={11.5}>{fmtINR(t.fill)}</Num></div>
                <Num size={10.5} weight={400} color={color.textMuted}>
                  {fmtDate(t.time)} {fmtClock(t.time)}
                </Num>
                <div style={{ ...right, color: color.textMuted }}><Num size={11.5}>{fmtINR(t.charges)}</Num></div>
                <div
                  title={`${t.fillReason}${t.feedLagS != null ? ` · feed ${Math.round(t.feedLagS / 60)} min behind` : ""}`}
                  style={{ font: `500 9px ${font.sans}`, color: t.delayed ? color.warning : color.textFaint }}
                >
                  {t.delayed ? "delayed feed" : "EOD fill"}
                </div>
                <Journal t={t} />
              </div>
            ))}
          </>
        )}
      </div>
    </>
  );
}

export function Playground() {
  const { data: portfolios, isLoading, error } = usePortfolios();
  const [selected, setSelected] = useState<number | null>(null);
  const { openTicket } = useTicket();
  useEffect(() => {
    if (selected == null && portfolios?.length) setSelected(portfolios[0]?.id ?? null);
  }, [portfolios, selected]);
  const { data: detail } = usePortfolio(selected);

  return (
    <div style={{ padding: "20px 24px 40px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {portfolios?.map((p) => (
          <div
            key={p.id}
            role="tab"
            aria-selected={selected === p.id}
            onClick={() => setSelected(p.id)}
            style={{
              padding: "7px 14px",
              borderRadius: 6,
              font: `500 12.5px ${font.sans}`,
              cursor: "pointer",
              ...(selected === p.id
                ? { background: color.active, color: color.text }
                : { background: color.inset, color: color.textMuted, border: `1px solid ${color.border}` }),
            }}
          >
            {p.name}
          </div>
        ))}
        <NewPortfolio onDone={setSelected} />
        <div style={{ flex: 1 }} />
        <button
          onClick={() => openTicket({})}
          style={{ padding: "7px 14px", borderRadius: 6, border: "none", background: color.accent, color: "#fff", font: `600 12.5px ${font.sans}`, cursor: "pointer" }}
        >
          New order
        </button>
      </div>

      {isLoading && <div style={{ color: color.textFaint }}>Loading…</div>}
      {error && (
        <div role="alert" style={{ color: color.negative }}>
          Could not load portfolios: {error.message}
        </div>
      )}
      {portfolios && portfolios.length === 0 && (
        <EmptyState title="No portfolios yet">
          Create one to start paper trading with virtual capital.
        </EmptyState>
      )}
      {detail && <Detail p={detail} />}
    </div>
  );
}
