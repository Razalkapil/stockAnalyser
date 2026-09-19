import { useEffect, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { EquityChart } from "../components/EquityChart";
import { StatusPill } from "../components/StatusPill";
import { useStrategies, useStrategy, useStrategyAction } from "../lib/api/hooks";
import type { StrategyDetail, StrategySummary } from "../lib/api/types";
import { fmtDate, fmtNum, fmtPct, fmtPlainPct } from "../lib/format";
import { color, font, horizonLabel, pnlColor, tint } from "../lib/theme";

const COLS = "170px 90px 90px 70px 70px 70px 65px 70px 65px 75px";
const head = { textAlign: "right" as const };
const section = {
  font: `500 10.5px ${font.sans}`,
  color: color.textFaint,
  textTransform: "uppercase" as const,
  letterSpacing: 0.4,
  marginBottom: 6,
};
const mono = (extra = "") => ({ textAlign: "right" as const, font: `500 12px ${font.mono}`, ...(extra ? { color: extra } : {}) });

function Row({ s, selected, onClick }: { s: StrategySummary; selected: boolean; onClick: () => void }) {
  return (
    <div
      role="row"
      onClick={onClick}
      style={{
        display: "grid",
        gridTemplateColumns: COLS,
        columnGap: 10,
        minWidth: 820,
        padding: "10px 14px",
        borderBottom: `1px solid ${color.borderRow}`,
        cursor: "pointer",
        alignItems: "center",
        background: selected ? color.inset : undefined,
      }}
    >
      <div
        style={{
          font: `500 12px ${font.sans}`,
          color: color.text,
          display: "flex",
          alignItems: "center",
          gap: 6,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {s.name}
        {s.approx && (
          <span
            style={{
              font: `500 9px ${font.mono}`,
              color: color.warning,
              border: `1px solid ${tint.warning(0.4)}`,
              borderRadius: 3,
              padding: "0 4px",
            }}
          >
            approx
          </span>
        )}
      </div>
      <div style={{ font: `400 11.5px ${font.sans}`, color: color.textMuted }}>
        {horizonLabel(s.horizon)}
      </div>
      <div>
        <StatusPill status={s.status} />
      </div>
      <div style={mono()}>{fmtPct(s.btCagr, 0)}</div>
      <div style={mono(color.textMuted)}>{fmtPlainPct(s.winRate)}</div>
      <div style={mono(color.textMuted)}>{fmtPlainPct(s.maxDd)}</div>
      <div style={mono(color.textMuted)}>{fmtNum(s.sharpe, 1)}</div>
      <div style={mono(pnlColor(s.liveReturn))}>{fmtPct(s.liveReturn)}</div>
      <div style={mono(color.textMuted)}>{fmtPlainPct(s.hitRate)}</div>
      <div style={{ ...mono(color.textMuted), font: `400 11.5px ${font.mono}` }}>
        {s.avgHold == null ? "—" : `${s.avgHold.toFixed(0)}d`}
      </div>
    </div>
  );
}

function Detail({ d }: { d: StrategyDetail }) {
  const { approve, retire } = useStrategyAction(d.id);
  const error = approve.error ?? retire.error;
  return (
    <div
      style={{
        background: color.panel,
        border: `1px solid ${color.border}`,
        borderRadius: 8,
        padding: 16,
        position: "sticky",
        top: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
        <div style={{ font: `600 14px ${font.sans}` }}>{d.name}</div>
        <StatusPill status={d.status} />
      </div>
      <div style={{ font: `400 11.5px ${font.sans}`, color: color.textMuted, marginBottom: 14 }}>
        {horizonLabel(d.horizon)} · {d.trades} backtest trades · {d.liveClosed} live picks closed
      </div>

      <div style={section}>Rules</div>
      <ul
        style={{
          margin: "0 0 16px",
          paddingLeft: 18,
          font: `400 12px ${font.sans}`,
          color: color.textSecondary,
          lineHeight: 1.65,
        }}
      >
        {d.rules.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>

      <div style={section}>Equity curve vs Nifty 500 (out-of-sample)</div>
      <EquityChart strategy={d.equityCurve} benchmark={d.niftyCurve} benchmarkName="Nifty 500" />

      <div style={section}>Walk-forward windows</div>
      {d.walkForward.length ? (
        <div
          style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", gap: 5, marginBottom: 16 }}
        >
          {d.walkForward.map((w) => {
            const c =
              w.result === "pass"
                ? { bg: tint.positive(0.16), fg: color.positive }
                : w.result === "fail"
                  ? { bg: tint.negative(0.16), fg: color.negative }
                  : { bg: tint.muted(0.16), fg: color.textMuted };
            return (
              <div
                key={w.label}
                title={`${w.label}: ${fmtDate(w.testStart)} – ${fmtDate(w.testEnd)} · strategy ${fmtPct(
                  w.stratReturn,
                )} vs benchmark ${fmtPct(w.benchReturn)} (${w.result.replace("_", " ")})`}
                style={{
                  textAlign: "center",
                  padding: "7px 0",
                  borderRadius: 4,
                  font: `600 10px ${font.mono}`,
                  background: c.bg,
                  color: c.fg,
                }}
              >
                {w.label}
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{ font: `400 12px ${font.sans}`, color: color.textFaint, marginBottom: 16 }}>
          No walk-forward run yet.
        </div>
      )}

      <div style={section}>
        Recent trades{" "}
        <span style={{ textTransform: "none", letterSpacing: 0 }}>
          ({d.tradeListSource === "live" ? "live picks" : d.tradeListSource === "backtest" ? "backtest" : "none"})
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 16 }}>
        {d.tradeList.length === 0 && (
          <div style={{ font: `400 12px ${font.sans}`, color: color.textFaint }}>No trades yet.</div>
        )}
        {d.tradeList.map((t, i) => (
          <div
            key={i}
            style={{ display: "flex", justifyContent: "space-between", font: `500 11.5px ${font.mono}` }}
          >
            <span>{t.symbol}</span>
            <span style={{ color: color.textMuted }}>{fmtDate(t.date)}</span>
            <span style={{ color: pnlColor(t.ret) }}>{fmtPct(t.ret)}</span>
          </div>
        ))}
      </div>

      {d.approxReasons.length > 0 && (
        <div
          style={{
            background: tint.warning(0.08),
            border: `1px solid ${tint.warning(0.3)}`,
            borderRadius: 5,
            padding: "8px 10px",
            marginBottom: 12,
            font: `400 11px ${font.sans}`,
            color: color.warning,
            lineHeight: 1.5,
          }}
        >
          <strong>Read with care:</strong>
          <ul style={{ margin: "4px 0 0", paddingLeft: 16 }}>
            {d.approxReasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {d.notes && (
        <div style={{ font: `400 11px ${font.sans}`, color: color.textMuted, lineHeight: 1.5, marginBottom: 12 }}>
          {d.notes}
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        {d.status === "candidate" && (
          <button
            disabled={d.gateVerdict !== "pass" || approve.isPending}
            title={d.gateVerdict === "pass" ? "" : "Only a strategy that passed the promotion gate can go live"}
            onClick={() => approve.mutate()}
            style={{
              padding: "5px 12px",
              borderRadius: 5,
              border: "none",
              background: tint.positive(0.14),
              color: color.positive,
              font: `600 11px ${font.sans}`,
              cursor: d.gateVerdict === "pass" ? "pointer" : "not-allowed",
              opacity: d.gateVerdict === "pass" ? 1 : 0.5,
            }}
          >
            Approve
          </button>
        )}
        {(d.status === "live" || d.status === "decaying" || d.status === "candidate") && (
          <button
            disabled={retire.isPending}
            onClick={() => {
              if (window.confirm(`Retire "${d.name}"? It will stop producing picks.`)) {
                retire.mutate("retired in the UI");
              }
            }}
            style={{
              padding: "5px 12px",
              borderRadius: 5,
              background: color.inset,
              border: `1px solid ${color.border}`,
              color: color.textMuted,
              font: `600 11px ${font.sans}`,
              cursor: "pointer",
            }}
          >
            Retire
          </button>
        )}
      </div>
      {error && (
        <div role="alert" style={{ color: color.negative, font: `400 11.5px ${font.sans}`, marginTop: 8 }}>
          {error.message}
        </div>
      )}
    </div>
  );
}

export function StrategyLab() {
  const { data: rows, isLoading, error } = useStrategies();
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    if (!selected && rows?.length) setSelected(rows[0]?.id ?? null);
  }, [rows, selected]);
  const { data: detail } = useStrategy(selected);

  return (
    <div
      style={{
        padding: "20px 24px 40px",
        display: "grid",
        gridTemplateColumns: "minmax(0,1fr) minmax(0,420px)",
        gap: 18,
        alignItems: "start",
      }}
    >
      <div>
        <div style={{ font: `600 15px ${font.sans}`, marginBottom: 2 }}>Strategy lab</div>
        <div style={{ font: `400 12px ${font.sans}`, color: color.textMuted, marginBottom: 14 }}>
          {rows ? `${rows.length} strateg${rows.length === 1 ? "y" : "ies"}` : "…"} · CAGR, win rate,
          drawdown and Sharpe are out-of-sample walk-forward, after costs
        </div>
        {isLoading && <div style={{ color: color.textFaint }}>Loading…</div>}
        {error && (
          <div role="alert" style={{ color: color.negative }}>
            Could not load strategies: {error.message}
          </div>
        )}
        {rows && rows.length === 0 && (
          <EmptyState title="No strategies registered">
            Run <code>stk strategies seed</code>.
          </EmptyState>
        )}
        {rows && rows.length > 0 && (
          <div
            style={{
              background: color.panel,
              border: `1px solid ${color.border}`,
              borderRadius: 8,
              overflowX: "auto",
              marginBottom: 22,
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: COLS,
                columnGap: 10,
                padding: "8px 14px",
                font: `500 10.5px ${font.sans}`,
                color: color.textFaint,
                borderBottom: `1px solid ${color.border}`,
                textTransform: "uppercase",
                letterSpacing: 0.4,
                minWidth: 820,
              }}
            >
              <div>Strategy</div>
              <div>Horizon</div>
              <div>Status</div>
              <div style={head}>CAGR</div>
              <div style={head}>Win%</div>
              <div style={head}>MaxDD</div>
              <div style={head}>Sharpe</div>
              <div style={head}>Live%</div>
              <div style={head}>Hit%</div>
              <div style={head}>Avg hold</div>
            </div>
            {rows.map((s) => (
              <Row key={s.id} s={s} selected={selected === s.id} onClick={() => setSelected(s.id)} />
            ))}
          </div>
        )}

        <div style={{ font: `600 13px ${font.sans}`, marginBottom: 10 }}>AI proposals — weekly lab</div>
        <EmptyState title="No proposals">The weekly strategy lab has not run yet.</EmptyState>
      </div>
      {detail && <Detail d={detail} />}
    </div>
  );
}
