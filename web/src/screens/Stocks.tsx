import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { Num } from "../components/Num";
import { PriceChart } from "../components/PriceChart";
import { Segmented } from "../components/Segmented";
import { StatusPill } from "../components/StatusPill";
import { TradingViewWidget } from "../components/TradingViewWidget";
import { ApiError } from "../lib/api/client";
import { useBars, useStock, useStockSearch } from "../lib/api/hooks";
import { fmtDate, fmtINR, fmtNum, fmtPct, fmtPlainPct } from "../lib/format";
import { color, font, horizonLabel, pnlColor } from "../lib/theme";

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
  marginBottom: 8,
};

function SearchPage() {
  const [q, setQ] = useState("");
  const nav = useNavigate();
  const { data } = useStockSearch(q);
  return (
    <div style={{ padding: "20px 24px 40px", maxWidth: 720 }}>
      <div style={{ font: `600 15px ${font.sans}`, marginBottom: 12 }}>Stocks</div>
      <input
        aria-label="Find a stock"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Symbol or company name…"
        autoFocus
        style={{
          width: "100%",
          background: color.inset,
          border: `1px solid ${color.border}`,
          borderRadius: 6,
          padding: "10px 12px",
          color: color.text,
          font: `400 13px ${font.sans}`,
          outline: "none",
          marginBottom: 12,
        }}
      />
      {q.trim() === "" && (
        <EmptyState title="Search for a stock">
          Chart, fundamentals and the strategies that flagged it.
        </EmptyState>
      )}
      {data?.map((h) => (
        <div
          key={h.symbol}
          onClick={() => nav(`/stocks/${h.symbol}`)}
          style={{
            display: "flex",
            gap: 10,
            alignItems: "baseline",
            padding: "10px 12px",
            borderBottom: `1px solid ${color.borderRow}`,
            cursor: "pointer",
          }}
        >
          <span style={{ font: `600 13px ${font.mono}`, width: 110 }}>{h.symbol}</span>
          <span style={{ font: `400 12px ${font.sans}`, color: color.textMuted }}>{h.company}</span>
        </div>
      ))}
      {q.trim() !== "" && data?.length === 0 && <EmptyState title="No match" />}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ font: `500 9px ${font.sans}`, color: color.textFaint, textTransform: "uppercase", marginBottom: 2 }}>
        {label}
      </div>
      <Num>{value}</Num>
    </div>
  );
}

function StockPage({ symbol }: { symbol: string }) {
  const { data: stock, error, isLoading } = useStock(symbol);
  const { data: bars } = useBars(stock ? symbol : null);
  const [source, setSource] = useState<"own" | "tv">("own");
  const markers = useMemo(
    () => (stock?.flaggedBy ?? []).map((f) => ({ date: f.signalDate, label: f.strategy })),
    [stock],
  );

  if (isLoading) return <div style={{ padding: 24, color: color.textFaint }}>Loading…</div>;
  if (error) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <div style={{ padding: 24 }}>
        <EmptyState title={notFound ? `No security called ${symbol}` : "Could not load this stock"}>
          <Link to="/stocks">Search again</Link>
        </EmptyState>
      </div>
    );
  }
  if (!stock) return null;
  const f = stock.fundamentals;

  return (
    <div style={{ padding: "20px 24px 40px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <span style={{ font: `700 20px ${font.mono}` }}>{stock.symbol}</span>
        <span
          style={{
            font: `500 9px ${font.mono}`,
            color: color.textFaint,
            border: `1px solid ${color.borderSubtle}`,
            borderRadius: 3,
            padding: "0 4px",
          }}
        >
          {stock.exch}
        </span>
        <span style={{ font: `400 13px ${font.sans}`, color: color.textMuted }}>{stock.company}</span>
        <div style={{ flex: 1 }} />
        <Num size={18} weight={600}>{fmtINR(stock.lastClose)}</Num>
        {stock.changePct != null && (
          <Num size={13} color={pnlColor(stock.changePct)}>
            {fmtPct(stock.changePct / 100, 2)}
          </Num>
        )}
        <span style={{ font: `400 11px ${font.sans}`, color: color.textFaint }}>
          {stock.lastDate ? `close ${fmtDate(stock.lastDate)}` : ""}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 320px", gap: 18, alignItems: "start" }}>
        <div style={panel}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
            <div style={section}>Price</div>
            <Segmented
              options={[
                { id: "own", label: "Adjusted (ours)" },
                { id: "tv", label: "TradingView" },
              ]}
              value={source}
              onChange={setSource}
            />
          </div>
          {source === "own" ? (
            <PriceChart bars={bars ?? []} markers={markers} />
          ) : (
            <TradingViewWidget symbol={stock.tvSymbol} />
          )}
          {source === "own" && markers.length > 0 && (
            <div style={{ font: `400 10.5px ${font.sans}`, color: color.textFaint, marginTop: 6 }}>
              ▲ marks a day a strategy flagged this stock.
            </div>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={panel}>
            <div style={section}>Fundamentals</div>
            {f ? (
              <>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <Fact label="ROCE" value={fmtPlainPct(f.roce, 1)} />
                  <Fact label="Debt / equity" value={fmtNum(f.deRatio)} />
                  <Fact label="Sales CAGR 3y" value={fmtPlainPct(f.salesCagr3, 1)} />
                  <Fact label="Profit CAGR 3y" value={fmtPlainPct(f.profitCagr3, 1)} />
                  <Fact label="EPS (TTM)" value={fmtNum(f.epsTtm)} />
                </div>
                <div style={{ font: `400 10.5px ${font.sans}`, color: color.warning, marginTop: 10, lineHeight: 1.5 }}>
                  As of {fmtDate(f.asOf)} filing. {f.note}
                </div>
              </>
            ) : (
              <div style={{ font: `400 12px ${font.sans}`, color: color.textFaint, lineHeight: 1.5 }}>
                No parsed filings for this stock. Run <code>stk ingest xbrl</code>. Banks and some
                older filings use a different format and are not supported.
              </div>
            )}
          </div>

          <div style={panel}>
            <div style={section}>Flagged by</div>
            {stock.flaggedBy.length === 0 && (
              <div style={{ font: `400 12px ${font.sans}`, color: color.textFaint }}>
                No strategy has flagged this stock.
              </div>
            )}
            {stock.flaggedBy.map((x, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <div>
                  <div style={{ font: `500 12px ${font.sans}` }}>{x.strategy}</div>
                  <div style={{ font: `400 10.5px ${font.sans}`, color: color.textFaint }}>
                    {horizonLabel(x.horizon)} · {fmtDate(x.signalDate)}
                  </div>
                </div>
                <StatusPill status={x.status === "pending_entry" ? "candidate" : x.status === "open" ? "live" : "retired"} />
              </div>
            ))}
          </div>

          <div style={panel}>
            <div style={section}>Paper positions</div>
            <div style={{ font: `400 12px ${font.sans}`, color: color.textFaint }}>
              Paper trading arrives with the playground.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Stocks() {
  const { symbol } = useParams();
  return symbol ? <StockPage symbol={symbol} /> : <SearchPage />;
}
