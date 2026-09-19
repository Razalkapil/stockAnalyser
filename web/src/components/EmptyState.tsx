import type { ReactNode } from "react";
import { color, font } from "../lib/theme";

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div
      style={{
        padding: 48,
        textAlign: "center",
        color: color.textFaint,
        border: `1px dashed ${color.border}`,
        borderRadius: 8,
      }}
    >
      <div style={{ fontSize: 22, marginBottom: 6 }}>—</div>
      <div style={{ font: `500 13px ${font.sans}`, color: color.textMuted }}>{title}</div>
      {children && <div style={{ font: `400 12px ${font.sans}`, marginTop: 4 }}>{children}</div>}
    </div>
  );
}
