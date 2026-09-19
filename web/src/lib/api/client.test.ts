import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiGet, apiPost, getToken, setToken } from "./client";

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

const reply = (status: number, body: unknown = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("api client", () => {
  it("sends the stored token as a bearer header", async () => {
    setToken("stk_abc");
    const fn = vi.fn(async () => reply(200, { ok: 1 }));
    vi.stubGlobal("fetch", fn);
    await apiGet("/api/status");
    expect((fn.mock.calls[0] as unknown[])[1]).toMatchObject({
      headers: expect.objectContaining({ Authorization: "Bearer stk_abc" }),
    });
  });

  it("clears a rejected token so the app returns to sign-in", async () => {
    setToken("stk_bad");
    vi.stubGlobal("fetch", vi.fn(async () => reply(401, { detail: "no" })));
    await expect(apiGet("/api/status")).rejects.toMatchObject({ status: 401 });
    expect(getToken()).toBeNull();
  });

  it("surfaces the server's own reason for a failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(409, { detail: "not through the gate" })));
    const err = await apiPost("/api/strategies/x/approve").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe("not through the gate");
  });

  it("posts JSON bodies", async () => {
    const fn = vi.fn(async () => reply(200));
    vi.stubGlobal("fetch", fn);
    await apiPost("/api/x", { confirm: true });
    const init = (fn.mock.calls[0] as unknown[])[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"confirm":true}');
  });

  it("survives storage being unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(getToken()).toBeNull();
    vi.restoreAllMocks();
  });
});
