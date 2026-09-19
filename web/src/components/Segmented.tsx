import { color, font } from "../lib/theme";

export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { id: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 2,
        background: color.inset,
        border: `1px solid ${color.border}`,
        borderRadius: 6,
        padding: 2,
      }}
    >
      {options.map((o) => (
        <div
          key={o.id}
          role="button"
          aria-pressed={value === o.id}
          onClick={() => onChange(o.id)}
          style={{
            padding: "5px 12px",
            borderRadius: 5,
            font: `500 11.5px ${font.sans}`,
            cursor: "pointer",
            ...(value === o.id
              ? { background: color.active, color: color.text }
              : { color: color.textMuted }),
          }}
        >
          {o.label}
        </div>
      ))}
    </div>
  );
}
