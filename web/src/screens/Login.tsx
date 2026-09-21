import { useState } from "react";
import { setToken } from "../lib/api/client";
import { color, font } from "../lib/theme";

export function Login() {
  const [value, setValue] = useState("");
  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: color.page,
        color: color.text,
      }}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (value.trim()) setToken(value.trim());
        }}
        style={{
          width: 340,
          background: color.panel,
          border: `1px solid ${color.border}`,
          borderRadius: 8,
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div style={{ font: `700 13px/1 ${font.mono}`, letterSpacing: 0.5 }}>
          RZ<span style={{ color: color.accent }}>•</span>TERMINAL
        </div>
        <div style={{ font: `400 12px ${font.sans}`, color: color.textMuted, lineHeight: 1.5 }}>
          Paste your API token: the <code>STK_AUTH__TOKEN</code> from <code>.env</code>, or one
          created with <code>stk api token create NAME</code>.
        </div>
        <input
          type="password"
          aria-label="API token"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="stk_…"
          autoFocus
          style={{
            background: color.inset,
            border: `1px solid ${color.border}`,
            borderRadius: 5,
            padding: "8px 10px",
            color: color.text,
            font: `400 12px ${font.mono}`,
            outline: "none",
          }}
        />
        <button
          type="submit"
          style={{
            padding: "8px 12px",
            borderRadius: 5,
            border: "none",
            background: color.accent,
            color: "#fff",
            font: `600 12px ${font.sans}`,
            cursor: "pointer",
          }}
        >
          Sign in
        </button>
      </form>
    </div>
  );
}
