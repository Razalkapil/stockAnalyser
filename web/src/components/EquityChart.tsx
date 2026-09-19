import { color, font } from "../lib/theme";

const W = 380;
const H = 120;
const PAD = 6;

function points(values: number[], lo: number, hi: number): string {
  const span = hi - lo || 1;
  return values
    .map((v, i) => {
      const x = values.length === 1 ? W / 2 : (i / (values.length - 1)) * W;
      const y = H - PAD - ((v - lo) / span) * (H - PAD * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

/** The design's two-line SVG: strategy solid blue, benchmark dashed grey. Both share one y-scale. */
export function EquityChart({
  strategy,
  benchmark,
  benchmarkName,
}: {
  strategy: number[];
  benchmark: number[];
  benchmarkName: string;
}) {
  if (strategy.length < 2) {
    return (
      <div style={{ font: `400 12px ${font.sans}`, color: color.textFaint, padding: "18px 0" }}>
        No backtest curve yet.
      </div>
    );
  }
  const all = benchmark.length ? [...strategy, ...benchmark] : strategy;
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 110, marginBottom: 16 }}>
        {benchmark.length > 1 && (
          <polyline
            data-testid="benchmark-line"
            points={points(benchmark, lo, hi)}
            fill="none"
            stroke={color.textFaint}
            strokeWidth={1.5}
            strokeDasharray="4,3"
          />
        )}
        <polyline
          data-testid="strategy-line"
          points={points(strategy, lo, hi)}
          fill="none"
          stroke={color.accent}
          strokeWidth={2}
        />
      </svg>
      <div
        style={{
          display: "flex",
          gap: 14,
          font: `500 10.5px ${font.sans}`,
          color: color.textMuted,
          marginBottom: 16,
          marginTop: -10,
        }}
      >
        <Legend swatch={color.accent} label="Strategy" />
        {benchmark.length > 1 ? (
          <Legend swatch={color.textFaint} label={benchmarkName} />
        ) : (
          <span style={{ color: color.textFaint }}>no benchmark for this span</span>
        )}
      </div>
    </>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span>
      <span
        style={{
          display: "inline-block",
          width: 8,
          height: 8,
          background: swatch,
          borderRadius: 2,
          marginRight: 5,
        }}
      />
      {label}
    </span>
  );
}
