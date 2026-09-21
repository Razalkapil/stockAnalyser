import { useEffect, useId, useState } from "react";
import { useStockSearch } from "../lib/api/hooks";
import { color, font } from "../lib/theme";

const DEBOUNCE_MS = 200;

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

interface Props {
  /** What the user has typed (or the picked symbol, once one is chosen). */
  text: string;
  /** The chosen symbol, or null while the text is only a search. Only a picked symbol can be ordered. */
  picked: string | null;
  onText: (text: string) => void;
  onPick: (symbol: string) => void;
}

/**
 * Symbol search box with a dropdown of matches (by ticker or company name).
 * Typing clears the selection, so a half-typed ticker is never mistaken for a real one and
 * nothing is looked up until the user chooses.
 */
export function SymbolPicker({ text, picked, onText, onPick }: Props) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const query = text.trim();
  const debounced = useDebounced(query, DEBOUNCE_MS);
  const searching = picked == null && query !== "";
  const { data: hits } = useStockSearch(searching ? debounced : "");
  const results = searching && debounced === query ? (hits ?? null) : null; // null = still loading
  const showList = open && searching;

  useEffect(() => setActive(0), [debounced]);

  const choose = (symbol: string) => {
    onPick(symbol);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!results?.length) return;
      e.preventDefault();
      setOpen(true);
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (i + step + results.length) % results.length);
    } else if (e.key === "Enter" && showList && results?.length) {
      e.preventDefault();
      const hit = results[active] ?? results[0];
      if (hit) choose(hit.symbol);
    } else if (e.key === "Escape" && showList) {
      e.stopPropagation();
      setOpen(false);
    }
  };

  // Leaving the box with the exact ticker typed is as good as picking it.
  const onBlur = () => {
    setOpen(false);
    const exact = results?.find((h) => h.symbol === query.toUpperCase());
    if (picked == null && exact) onPick(exact.symbol);
  };

  const row = { padding: "8px 10px", display: "flex", gap: 8, alignItems: "baseline", cursor: "pointer" } as const;
  const note = { padding: "10px", font: `400 12px ${font.sans}`, color: color.textFaint } as const;

  return (
    <div style={{ position: "relative" }}>
      <input
        role="combobox"
        aria-label="Symbol"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        spellCheck={false}
        value={text}
        placeholder="Search symbol or company…"
        onChange={(e) => {
          onText(e.target.value);
          setOpen(true);
        }}
        onFocus={(e) => {
          e.target.select();
          setOpen(true);
        }}
        onBlur={onBlur}
        onKeyDown={onKeyDown}
        style={{
          width: "100%",
          background: color.inset,
          border: `1px solid ${color.border}`,
          borderRadius: 5,
          padding: 8,
          color: color.text,
          font: `500 12px ${font.mono}`,
          outline: "none",
        }}
      />
      {showList && (
        <div
          id={listId}
          role="listbox"
          aria-label="Matching stocks"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            zIndex: 2,
            maxHeight: 280,
            overflowY: "auto",
            background: color.panel,
            border: `1px solid ${color.border}`,
            borderRadius: 6,
            boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
          }}
        >
          {results == null && <div style={note}>Searching…</div>}
          {results?.length === 0 && <div style={note}>No match</div>}
          {results?.map((h, i) => (
            <div
              key={`${h.exch}:${h.symbol}`}
              role="option"
              aria-selected={i === active}
              // mousedown fires before the input's blur, which would close the list before the click lands
              onMouseDown={(e) => {
                e.preventDefault();
                choose(h.symbol);
              }}
              onMouseEnter={() => setActive(i)}
              style={{ ...row, background: i === active ? color.inset : "transparent" }}
            >
              <span style={{ font: `600 12px ${font.mono}`, minWidth: 84 }}>{h.symbol}</span>
              <span
                style={{
                  flex: 1,
                  font: `400 12px ${font.sans}`,
                  color: color.textMuted,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {h.company}
              </span>
              <span style={{ font: `500 10px ${font.sans}`, color: color.textFaint }}>{h.exch}</span>
            </div>
          ))}
        </div>
      )}
      {!showList && searching && (
        <div style={{ font: `400 11px ${font.sans}`, color: color.warning, marginTop: 4 }}>
          Pick a stock from the list.
        </div>
      )}
    </div>
  );
}
