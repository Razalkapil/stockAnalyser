import { useEffect, useRef } from "react";
import { color, font } from "../lib/theme";

/**
 * TradingView's free embeddable chart. Opt-in and clearly labelled: it is THEIR data (not the
 * adjusted series our strategies use), and whether the free widget renders every NSE/BSE symbol
 * is unconfirmed -- so it is a toggle, never the default.
 */
export function TradingViewWidget({ symbol }: { symbol: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.innerHTML = "";
    const inner = document.createElement("div");
    inner.className = "tradingview-widget-container__widget";
    inner.style.height = "340px";
    el.appendChild(inner);
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.async = true;
    script.text = JSON.stringify({
      symbol,
      interval: "D",
      theme: "dark",
      style: "1",
      locale: "en",
      backgroundColor: color.panel,
      autosize: true,
      allow_symbol_change: false,
      hide_side_toolbar: true,
      timezone: "Asia/Kolkata",
    });
    el.appendChild(script);
    return () => {
      el.innerHTML = "";
    };
  }, [symbol]);
  return (
    <div>
      <div ref={ref} data-testid="tv-widget" style={{ height: 340 }} />
      <div style={{ font: `400 10.5px ${font.sans}`, color: color.textFaint, marginTop: 6 }}>
        Third-party chart and data (TradingView). Not the adjusted series the strategies use.
      </div>
    </div>
  );
}
