import { useEffect, useState } from "react";
import { useCostPreview, usePlaceOrder, usePortfolios, useStock } from "../lib/api/hooks";
import { fmtINR } from "../lib/format";
import { color, font, tint } from "../lib/theme";
import { Num } from "./Num";
import { useTicket } from "./TicketContext";

type OrderType = "MARKET" | "LIMIT" | "SL" | "TARGET";

const label = { font: `500 10.5px ${font.sans}`, color: color.textMuted, marginBottom: 4 } as const;
const input = {
  width: "100%",
  background: color.inset,
  border: `1px solid ${color.border}`,
  borderRadius: 5,
  padding: 8,
  color: color.text,
  font: `500 12px ${font.mono}`,
  outline: "none",
} as const;

function Field({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={label}>{name}</div>
      {children}
    </div>
  );
}

const num = (s: string): number | null => {
  const v = Number(s.replace(/,/g, ""));
  return s.trim() !== "" && Number.isFinite(v) && v > 0 ? v : null;
};

export function OrderDrawer() {
  const { open, prefill, closeTicket } = useTicket();
  const { data: portfolios } = usePortfolios();
  const place = usePlaceOrder();

  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [symbol, setSymbol] = useState("");
  const [portfolioId, setPortfolioId] = useState<number | null>(null);
  const [qty, setQty] = useState("10");
  const [type, setType] = useState<OrderType>("MARKET");
  const [price, setPrice] = useState("");
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");

  // Re-seed the form every time the ticket is opened.
  useEffect(() => {
    if (!open) return;
    setSide(prefill.side ?? "buy");
    setSymbol(prefill.symbol ?? "");
    setQty("10");
    setType("MARKET");
    setPrice("");
    setStop(prefill.stop != null ? String(prefill.stop) : "");
    setTarget(prefill.target != null ? String(prefill.target) : "");
    setNote(prefill.note ?? "");
    place.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, prefill]);

  useEffect(() => {
    if (portfolioId == null && portfolios?.length) setPortfolioId(portfolios[0]?.id ?? null);
  }, [portfolios, portfolioId]);

  const sym = symbol.trim().toUpperCase();
  const { data: stock } = useStock(open && sym ? sym : null);
  const ref = prefill.symbol === sym && prefill.ref != null ? prefill.ref : (stock?.lastClose ?? null);
  const priced = type !== "MARKET";
  const px = priced ? num(price) : ref;
  const q = Math.floor(Number(qty));
  const { data: preview } = useCostPreview(
    sym && px != null && q >= 1 ? { symbol: sym, side, qty: q, price: px } : null,
  );

  if (!open) return null;

  const sellOnly = type === "SL" || type === "TARGET";
  const canPlace = portfolioId != null && sym !== "" && q >= 1 && (!priced || px != null) && !place.isPending;

  const submit = () => {
    if (portfolioId == null) return;
    place.mutate(
      {
        portfolioId,
        symbol: sym,
        side,
        type,
        qty: q,
        limitPrice: type === "LIMIT" ? String(px) : null,
        triggerPrice: sellOnly ? String(px) : null,
        bracketStop: side === "buy" && num(stop) ? String(num(stop)) : null,
        bracketTarget: side === "buy" && num(target) ? String(num(target)) : null,
        journalNote: note.trim() || null,
        pickId: prefill.pickId ?? null,
      },
      { onSuccess: closeTicket },
    );
  };

  return (
    <>
      <div onClick={closeTicket} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 40 }} />
      <div
        role="dialog"
        aria-label="Order ticket"
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          height: "100vh",
          width: 380,
          background: color.panel,
          borderLeft: `1px solid ${color.border}`,
          zIndex: 41,
          padding: 20,
          overflowY: "auto",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <div style={{ font: `600 14px ${font.sans}` }}>Order ticket</div>
          <div onClick={closeTicket} style={{ cursor: "pointer", color: color.textFaint, fontSize: 16 }} aria-label="Close">
            ✕
          </div>
        </div>

        <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
          {(["buy", "sell"] as const).map((s) => {
            const on = side === s;
            const c = s === "buy" ? color.positive : color.negative;
            return (
              <div
                key={s}
                role="button"
                aria-pressed={on}
                onClick={() => setSide(s)}
                style={{
                  flex: 1,
                  textAlign: "center",
                  padding: 9,
                  borderRadius: 6,
                  cursor: "pointer",
                  font: `600 12.5px ${font.sans}`,
                  ...(on
                    ? { background: s === "buy" ? tint.positive(0.18) : tint.negative(0.18), color: c, border: `1px solid ${c}` }
                    : { background: color.inset, color: color.textMuted, border: `1px solid ${color.border}` }),
                }}
              >
                {s === "buy" ? "Buy" : "Sell"}
              </div>
            );
          })}
        </div>

        {!portfolios?.length && (
          <div role="alert" style={{ color: color.warning, font: `400 12px ${font.sans}`, marginBottom: 12 }}>
            Create a portfolio on the Playground screen first.
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
          <Field name="Symbol">
            <input aria-label="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} style={input} placeholder="RELIANCE" />
          </Field>
          <Field name="Portfolio">
            <select
              aria-label="Portfolio"
              value={portfolioId ?? ""}
              onChange={(e) => setPortfolioId(Number(e.target.value))}
              style={{ ...input, font: `500 12px ${font.sans}` }}
            >
              {portfolios?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div style={{ font: `500 10.5px ${font.sans}`, color: color.textFaint, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 14 }}>
          {sym || "—"} · NSE · ref {ref != null ? fmtINR(ref) : "—"}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
          <Field name="Qty">
            <input aria-label="Quantity" value={qty} onChange={(e) => setQty(e.target.value)} inputMode="numeric" style={input} />
          </Field>
          <Field name="Order type">
            <select
              aria-label="Order type"
              value={type}
              onChange={(e) => {
                const t = e.target.value as OrderType;
                setType(t);
                if (t === "SL" || t === "TARGET") setSide("sell"); // protective exits are sells
              }}
              style={{ ...input, font: `500 12px ${font.sans}` }}
            >
              <option value="MARKET">Market</option>
              <option value="LIMIT">Limit</option>
              <option value="SL">Stop-loss (sell)</option>
              <option value="TARGET">Target (sell)</option>
            </select>
          </Field>
        </div>

        {priced && (
          <div style={{ marginBottom: 10 }}>
            <Field name={type === "LIMIT" ? "Limit price" : "Trigger price"}>
              <input aria-label="Price" value={price} onChange={(e) => setPrice(e.target.value)} style={input} />
            </Field>
          </div>
        )}

        {side === "buy" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
            <Field name="Stop (bracket)">
              <input aria-label="Stop" value={stop} onChange={(e) => setStop(e.target.value)} style={input} />
            </Field>
            <Field name="Target (bracket)">
              <input aria-label="Target" value={target} onChange={(e) => setTarget(e.target.value)} style={input} />
            </Field>
          </div>
        )}

        <div style={{ marginBottom: 14 }}>
          <Field name="Journal note">
            <textarea
              aria-label="Journal note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Why this trade…"
              style={{ ...input, height: 56, font: `400 12px ${font.sans}`, resize: "vertical" }}
            />
          </Field>
        </div>

        <div
          style={{
            background: color.inset,
            border: `1px solid ${color.border}`,
            borderRadius: 6,
            padding: "10px 12px",
            marginBottom: 16,
            font: `400 11.5px ${font.sans}`,
            color: color.textMuted,
          }}
        >
          <Row name="Est. value" value={preview ? fmtINR(preview.value) : "—"} />
          <Row name="Brokerage + STT + taxes" value={preview ? fmtINR(preview.charges) : "—"} />
          <Row name={side === "buy" ? "Total" : "Net proceeds"} value={preview ? fmtINR(preview.total) : "—"} strong />
          {preview && (
            <div style={{ marginTop: 6, font: `400 10.5px ${font.sans}`, color: color.textFaint, lineHeight: 1.4 }}>
              At ~{fmtINR(preview.estPrice)} incl. {preview.slippageBps} bps slippage.
              {preview.dpCharge > 0 && ` Includes the ${fmtINR(preview.dpCharge)} DP charge.`}
            </div>
          )}
        </div>

        {place.error && (
          <div role="alert" style={{ color: color.negative, font: `400 12px ${font.sans}`, marginBottom: 10 }}>
            {place.error.message}
          </div>
        )}
        <button
          disabled={!canPlace}
          onClick={submit}
          style={{
            width: "100%",
            padding: 11,
            borderRadius: 6,
            border: "none",
            background: color.accent,
            color: "#fff",
            font: `600 13px ${font.sans}`,
            cursor: canPlace ? "pointer" : "not-allowed",
            opacity: canPlace ? 1 : 0.5,
          }}
        >
          Place paper order
        </button>
        <div style={{ font: `400 10.5px ${font.sans}`, color: color.textFaint, marginTop: 10, lineHeight: 1.5 }}>
          Paper orders rest until a delayed candle touches the price. Fills from the ~15-min delayed
          feed are tagged; if the feed is down, the order waits for the end-of-day bar.
        </div>
      </div>
    </>
  );
}

function Row({ name, value, strong = false }: { name: string; value: string; strong?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
      <span>{name}</span>
      <Num size={12} weight={strong ? 600 : 500} color={strong ? color.text : color.textSecondary}>
        {value}
      </Num>
    </div>
  );
}
