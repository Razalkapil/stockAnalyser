import type { CSSProperties, ReactNode } from "react";
import { font } from "../lib/theme";

/**
 * Every number, symbol, price and date goes through this component, which is what enforces the
 * design's rule that they are set in IBM Plex Mono. Using it (rather than remembering a font
 * string at each call site) is the point.
 */
export function Num({
  children,
  size = 12,
  weight = 500,
  color,
  style,
}: {
  children: ReactNode;
  size?: number;
  weight?: number;
  color?: string;
  style?: CSSProperties;
}) {
  return (
    <span style={{ fontFamily: font.mono, fontSize: size, fontWeight: weight, color, ...style }}>
      {children}
    </span>
  );
}
