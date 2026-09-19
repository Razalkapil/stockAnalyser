import { describe, expect, it } from "vitest";
import { DASH, fmtClock, fmtDate, fmtINR, fmtNum, fmtPct, fmtPlainPct, fmtScore } from "./format";

describe("fmtINR (lakh/crore grouping)", () => {
  it.each([
    [1234567.5, "₹12,34,567.50"],
    [950, "₹950.00"],
    [100000, "₹1,00,000.00"],
    [12345678.9, "₹1,23,45,678.90"],
    [-2500000, "-₹25,00,000.00"],
    [0, "₹0.00"],
  ])("%s -> %s", (v, out) => expect(fmtINR(v)).toBe(out));

  it("can drop the symbol", () => expect(fmtINR(1500, { symbol: false })).toBe("1,500.00"));
  it("shows a dash for missing data, never zero", () => {
    expect(fmtINR(null)).toBe(DASH);
    expect(fmtINR(undefined)).toBe(DASH);
    expect(fmtINR(Number.NaN)).toBe(DASH);
  });
});

describe("percent formatting", () => {
  it("signs a fraction", () => {
    expect(fmtPct(0.052)).toBe("+5.2%");
    expect(fmtPct(-0.031)).toBe("-3.1%");
    expect(fmtPct(0)).toBe("0.0%");
    expect(fmtPct(0.31, 0)).toBe("+31%");
  });
  it("plain percent has no sign", () => {
    expect(fmtPlainPct(0.55)).toBe("55%");
    expect(fmtPlainPct(-0.123, 1)).toBe("-12.3%");
  });
  it("missing is a dash, not 0%", () => {
    expect(fmtPct(null)).toBe(DASH);
    expect(fmtPlainPct(undefined)).toBe(DASH);
    expect(fmtNum(null)).toBe(DASH);
  });
});

describe("dates", () => {
  it("formats a calendar date without any timezone shift", () => {
    expect(fmtDate("2026-01-01")).toBe("1 Jan 2026");
    expect(fmtDate("2026-12-31")).toBe("31 Dec 2026");
  });
  it("takes the date part of a timestamp", () => expect(fmtDate("2026-09-18T20:30:00+05:30")).toBe("18 Sep 2026"));
  it("passes an unparseable value through rather than inventing one", () => expect(fmtDate("soon")).toBe("soon"));
  it("reads the IST wall clock the server already supplied", () => {
    expect(fmtClock("2026-09-18T13:02:44+05:30")).toBe("13:02");
    expect(fmtClock(null)).toBe(DASH);
  });
});

describe("fmtScore", () => it("rounds onto /100", () => expect(fmtScore(78.4)).toBe("78/100")));
