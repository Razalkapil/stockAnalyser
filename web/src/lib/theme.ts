/**
 * Design tokens, taken from the handoff (docs/design/Stock Terminal Design.html) -- every value
 * below appears verbatim in that file. Components import from here; no component hard-codes a
 * hex value, so the palette can change in one place.
 */
export const color = {
  page: "#0a0e13",
  panel: "#11161d",
  inset: "#161c25",
  sunken: "#0e1319",
  active: "#1b2330",
  border: "#232b36",
  borderSubtle: "#2a3340",
  borderRow: "#1a2029",
  text: "#e6ebf0",
  textSecondary: "#c7d0d9",
  textMuted: "#8b96a3",
  textFaint: "#5b6573",
  accent: "#4c8dff",
  accentHover: "#7bacff",
  positive: "#26a969",
  negative: "#e5484d",
  warning: "#d99a1b",
  violet: "#9d7cf5",
} as const;

/** Semantic chip backgrounds: the semantic colour at low alpha, with solid text. */
export const tint = {
  accent: (a = 0.15) => `rgba(76,141,255,${a})`,
  positive: (a = 0.15) => `rgba(38,169,105,${a})`,
  negative: (a = 0.1) => `rgba(229,72,77,${a})`,
  warning: (a = 0.12) => `rgba(217,154,27,${a})`,
  violet: (a = 0.15) => `rgba(157,124,245,${a})`,
  muted: (a = 0.15) => `rgba(139,150,163,${a})`,
};

export const font = {
  sans: "'IBM Plex Sans', system-ui, sans-serif",
  mono: "'IBM Plex Mono', monospace",
} as const;

export const statusColors: Record<string, { bg: string; fg: string }> = {
  live: { bg: tint.positive(), fg: color.positive },
  candidate: { bg: tint.violet(), fg: color.violet },
  decaying: { bg: tint.warning(0.15), fg: color.warning },
  retired: { bg: tint.muted(), fg: color.textMuted },
  // The promotion gate's own verdict. The design has no separate "rejected"; it reads as retired.
  rejected: { bg: tint.muted(), fg: color.textMuted },
};

export const horizons = [
  { id: "short_term", label: "Short-term" },
  { id: "swing", label: "Swing" },
  { id: "momentum", label: "Momentum" },
  { id: "long_term", label: "Long-term" },
] as const;

export type HorizonId = (typeof horizons)[number]["id"];

export function horizonLabel(id: string): string {
  return horizons.find((h) => h.id === id)?.label ?? id;
}

/** P&L colour: green up, red down, muted for null/zero. */
export function pnlColor(v: number | null | undefined): string {
  if (v == null) return color.textFaint;
  if (v > 0) return color.positive;
  if (v < 0) return color.negative;
  return color.textMuted;
}
