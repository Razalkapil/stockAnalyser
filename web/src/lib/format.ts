/**
 * Formatting. Rupees use Indian digit grouping (lakh / crore) -- the project's rule, and what
 * `stk.core.money.format_inr` does on the backend. Missing data is an em dash, never a zero:
 * "not available" and "zero" are different facts and the UI must not blur them.
 */
export const DASH = "—";

/** 1234567.5 -> "₹12,34,567.50". */
export function fmtINR(v: number | null | undefined, opts: { symbol?: boolean } = {}): string {
  if (v == null || Number.isNaN(v)) return DASH;
  const { symbol = true } = opts;
  const abs = Math.abs(v).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${v < 0 ? "-" : ""}${symbol ? "₹" : ""}${abs}`;
}

/** A fraction as a signed percent: 0.052 -> "+5.2%". */
export function fmtPct(fraction: number | null | undefined, digits = 1): string {
  if (fraction == null || Number.isNaN(fraction)) return DASH;
  const p = fraction * 100;
  return `${p > 0 ? "+" : ""}${p.toFixed(digits)}%`;
}

/** A fraction as an UNSIGNED percent: 0.55 -> "55%" (win rates, hit rates, drawdowns). */
export function fmtPlainPct(fraction: number | null | undefined, digits = 0): string {
  if (fraction == null || Number.isNaN(fraction)) return DASH;
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return v.toFixed(digits);
}

/** "2026-09-18T13:02:00+05:30" -> "13:02". Reads the wall-clock time the server already gave in IST. */
export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const m = /T(\d{2}:\d{2})/.exec(iso);
  return m?.[1] ?? DASH;
}

/** "2026-09-18" -> "18 Sep 2026" (parsed as a calendar date, never through a timezone). */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(m[3])} ${months[Number(m[2]) - 1] ?? "?"} ${m[1]}`;
}

/** Score on the 0-100 scale, shown "78/100". */
export function fmtScore(score: number): string {
  return `${Math.round(score)}/100`;
}
