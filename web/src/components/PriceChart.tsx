import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Bar } from "../lib/api/types";
import { color, font } from "../lib/theme";

export interface PickMarker {
  date: string;
  label: string;
}

/**
 * Candlesticks from OUR OWN back-adjusted bars (Lightweight Charts 5). Own data is the default
 * because it is what the strategies actually saw, works offline, and lets us mark the days a
 * strategy flagged the stock -- none of which an embedded third-party chart can do.
 * NB v5 removed series.setMarkers(); markers go through createSeriesMarkers().
 */
export function PriceChart({ bars, markers }: { bars: Bar[]; markers: PickMarker[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || bars.length === 0) return;
    const chart = createChart(el, {
      height: 340,
      layout: {
        background: { type: ColorType.Solid, color: color.panel },
        textColor: color.textMuted,
        fontFamily: font.mono,
      },
      grid: { vertLines: { color: color.borderRow }, horzLines: { color: color.borderRow } },
      rightPriceScale: { borderColor: color.border },
      timeScale: { borderColor: color.border },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: color.positive,
      downColor: color.negative,
      borderUpColor: color.positive,
      borderDownColor: color.negative,
      wickUpColor: color.positive,
      wickDownColor: color.negative,
    });
    series.setData(
      bars.map((b) => ({
        time: b.time as Time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );
    const times = new Set(bars.map((b) => b.time));
    createSeriesMarkers(
      series,
      markers
        .filter((m) => times.has(m.date)) // a marker on a day with no bar would throw
        .map((m) => ({
          time: m.date as Time,
          position: "belowBar" as const,
          color: color.accent,
          shape: "arrowUp" as const,
          text: m.label,
        })),
    );
    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: el.clientWidth });
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [bars, markers]);

  if (bars.length === 0) {
    return <div style={{ padding: 40, color: color.textFaint }}>No price history for this stock.</div>;
  }
  return <div ref={ref} data-testid="price-chart" style={{ width: "100%" }} />;
}
