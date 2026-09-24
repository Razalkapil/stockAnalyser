import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { EquityChart } from "../components/EquityChart";
import { StatusPill } from "../components/StatusPill";
import {
  usePreviews,
  useProposalAction,
  useLabRun,
  useProposals,
  useRunLab,
  useStrategies,
  useStrategy,
  useStrategyAction,
} from "../lib/api/hooks";
import type { ProposalOut, StrategyDetail, StrategySummary } from "../lib/api/types";
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
  const { data: previews } = usePreviews(d.id);
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

      {d.gateChecks.length > 0 && (
        <>
          <div style={section}>Promotion gate</div>
          <div
            data-testid="gate-checks"
            style={{ display: "grid", gap: 4, marginBottom: 16, font: `400 12px ${font.sans}` }}
          >
            {d.statusReason && (
              <div style={{ color: color.textMuted, marginBottom: 2 }}>{d.statusReason}</div>
            )}
            {d.gateChecks.map((c) => (
              <div key={c.name} style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                <span
                  aria-label={c.passed ? "passed" : "failed"}
                  style={{
                    font: `700 11px ${font.mono}`,
                    color: c.passed ? color.positive : color.negative,
                    minWidth: 30,
                  }}
                >
                  {c.passed ? "PASS" : "FAIL"}
                </span>
                <span style={{ color: c.passed ? color.textSecondary : color.text }}>{c.detail}</span>
              </div>
            ))}
          </div>
        </>
      )}

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

      {previews && previews.length > 0 && (
        <>
          <div style={section}>
            What it would pick today{" "}
            <span style={{ textTransform: "none", letterSpacing: 0 }}>(preview, not a pick)</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 16 }}>
            {previews.map((p) => (
              <div
                key={p.symbol}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  font: `500 11.5px ${font.mono}`,
                }}
              >
                <span>{p.symbol}</span>
                <span style={{ color: color.textMuted }}>{fmtNum(p.ref, 2)}</span>
                <span style={{ color: color.textMuted }}>{fmtNum(p.score, 0)}</span>
              </div>
            ))}
          </div>
        </>
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

const STATUS_LABEL: Record<string, string> = {
  awaiting_approval: "Awaiting your approval",
  invalid: "Rejected: invalid strategy",
  backtest_error: "Backtest could not run",
  rejected_by_gate: "Failed the promotion gate",
  insufficient_evidence: "Not enough evidence to judge",
  approved: "Approved",
  dismissed: "Dismissed",
};

function ProposalCard({ p, onView, viewing }: { p: ProposalOut; onView: (slug: string) => void; viewing: boolean }) {
  const slug = p.strategyId ?? p.targetStrategy;
  const { approve, dismiss } = useProposalAction();
  const open = p.status === "awaiting_approval";
  const isNew = p.type === "new";
  const error = approve.error ?? dismiss.error;
  return (
    <div data-testid="proposal" style={{ background: color.panel, border: `1px solid ${color.border}`, borderRadius: 8, padding: "14px 16px", opacity: open ? 1 : 0.75 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8, gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span
            style={{
              padding: "2px 8px",
              borderRadius: 4,
              font: `600 10px ${font.sans}`,
              background: isNew ? tint.accent() : tint.warning(0.15),
              color: isNew ? color.accent : color.warning,
              whiteSpace: "nowrap",
            }}
          >
            {isNew ? "New strategy" : "Demotion"}
          </span>
          <span style={{ font: `600 12.5px ${font.sans}` }}>{p.title}</span>
        </div>
        {open && (
          <div style={{ display: "flex", gap: 6 }}>
            <button
              disabled={approve.isPending}
              onClick={() => {
                if (!isNew && !window.confirm(`Retire "${p.targetStrategy}"? It will stop producing picks.`)) return;
                approve.mutate({ id: p.id, confirm: !isNew });
              }}
              style={{ padding: "5px 12px", borderRadius: 5, border: "none", background: tint.positive(0.14), color: color.positive, font: `600 11px ${font.sans}`, cursor: "pointer" }}
            >
              Approve
            </button>
            <button
              disabled={dismiss.isPending}
              onClick={() => dismiss.mutate(p.id)}
              style={{ padding: "5px 12px", borderRadius: 5, background: color.inset, border: `1px solid ${color.border}`, color: color.textMuted, font: `600 11px ${font.sans}`, cursor: "pointer" }}
            >
              Reject
            </button>
          </div>
        )}
      </div>
      <div style={{ font: `500 10.5px ${font.sans}`, color: open ? color.warning : color.textFaint, marginBottom: 6 }}>
        {STATUS_LABEL[p.status] ?? p.status}
        {p.statusNote ? ` — ${p.statusNote}` : ""}
      </div>
      <div style={{ font: `400 12px ${font.sans}`, color: color.textMuted, lineHeight: 1.5, marginBottom: 8 }}>{p.rationale}</div>
      {p.rules.length > 0 && (
        <ul style={{ margin: "0 0 8px", paddingLeft: 18, font: `400 11.5px ${font.sans}`, color: color.textSecondary, lineHeight: 1.6 }}>
          {p.rules.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {p.validationErrors.length > 0 && (
        <ul style={{ margin: "0 0 8px", paddingLeft: 18, font: `400 11.5px ${font.sans}`, color: color.negative, lineHeight: 1.6 }}>
          {p.validationErrors.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {isNew && p.gateVerdict && (
        <div style={{ display: "flex", gap: 14, font: `500 11px ${font.mono}`, color: color.textFaint }}>
          <span>CAGR <span style={{ color: color.textSecondary }}>{fmtPct(p.btCagr, 0)}</span></span>
          <span>Win <span style={{ color: color.textSecondary }}>{fmtPlainPct(p.btWinRate)}</span></span>
          <span>MaxDD <span style={{ color: color.textSecondary }}>{fmtPlainPct(p.btMaxDd)}</span></span>
          <span style={{ color: color.textFaint }}>out-of-sample, after costs</span>
        </div>
      )}
      {p.approx && p.approxReasons.length > 0 && (
        <div style={{ marginTop: 6, font: `400 10.5px ${font.sans}`, color: color.warning }}>Approximate: {p.approxReasons[0]}</div>
      )}
      {slug && (
        <button
          onClick={() => onView(slug)}
          style={{ marginTop: 8, padding: "4px 10px", borderRadius: 5, background: viewing ? color.inset : "transparent", border: `1px solid ${color.border}`, color: color.accent, font: `600 11px ${font.sans}`, cursor: "pointer" }}
        >
          {viewing ? "Showing details →" : "View details →"}
        </button>
      )}
      {error && (
        <div role="alert" style={{ color: color.negative, font: `400 11.5px ${font.sans}`, marginTop: 6 }}>
          {error.message}
        </div>
      )}
    </div>
  );
}

/** Why the lab is not offering to run, or what it is doing. `pending` = never run today. */
function labStatusLine(state: string | undefined, reason: string | null | undefined): string {
  switch (state) {
    case "queued":
      return "Queued — waiting for stk ai worker to pick it up.";
    case "running":
      return "Running — one model call, then local backtests. This can take hours.";
    case "ready":
      return "The lab has already run today.";
    case "failed":
    case "invalid_output":
      return `The last attempt did not complete${reason ? `: ${reason}` : ""}.`;
    case "skipped":
      return reason ?? "The last attempt was skipped.";
    default:
      return "Not run today.";
  }
}

function RunLab() {
  const qc = useQueryClient();
  const { data: run } = useLabRun();
  const start = useRunLab();
  const state = run?.state;
  const inFlight = state === "queued" || state === "running" || start.isPending;
  const already = state === "ready";

  // A run finishing is the moment new proposals appear; the list does not poll on its own.
  const wasInFlight = useRef(false);
  useEffect(() => {
    if (wasInFlight.current && !inFlight) void qc.invalidateQueries({ queryKey: ["proposals"] });
    wasInFlight.current = inFlight;
  }, [inFlight, qc]);

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <button
          type="button"
          disabled={inFlight}
          onClick={() => start.mutate(already)}
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
          {inFlight ? "Queued…" : already ? "Run again" : "Run lab now"}
        </button>
        <span style={{ font: `400 11.5px ${font.sans}`, color: color.textFaint }}>
          {labStatusLine(state, run?.stateReason)}
        </span>
      </div>
      <div style={{ font: `400 11px ${font.sans}`, color: color.textFaint, marginTop: 5 }}>
        Costs one model call and runs walk-forward backtests locally. Nothing it proposes changes
        anything until it passes the gate and you approve it.
      </div>
      {start.error && (
        <div role="alert" style={{ color: color.negative, marginTop: 6, font: `400 12px ${font.sans}` }}>
          {start.error.message}
        </div>
      )}
    </div>
  );
}

function Proposals({ selected, onView }: { selected: string | null; onView: (slug: string) => void }) {
  const { data, isLoading, error } = useProposals();
  return (
    <>
      <div style={{ font: `600 13px ${font.sans}`, marginBottom: 10 }}>AI proposals — weekly lab</div>
      <RunLab />
      {isLoading && <div style={{ color: color.textFaint }}>Loading…</div>}
      {error && (
        <div role="alert" style={{ color: color.negative }}>
          Could not load proposals: {error.message}
        </div>
      )}
      {data && data.length === 0 && <EmptyState title="No proposals">The weekly strategy lab has not run yet.</EmptyState>}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {data?.map((p) => (
          <ProposalCard key={p.id} p={p} onView={onView} viewing={selected === (p.strategyId ?? p.targetStrategy)} />
        ))}
      </div>
    </>
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

        <Proposals selected={selected} onView={setSelected} />
      </div>
      {detail && <Detail d={detail} />}
    </div>
  );
}
