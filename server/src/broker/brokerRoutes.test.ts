import { describe, expect, it, vi } from "vitest";
import { buildApp, type QueryFn } from "../app.js";
import type { KiteFetch } from "../holdings/kiteHoldings.js";
import type { PortfolioQuery, PortfolioTx } from "../portfolioTx.js";
import type { UiClient, UiResponse } from "../uiClient.js";
import { browserSession } from "../sessionTestHelper.js";

const ACCESS = "tok-SENTINEL-ACCESS-9001";
const API_KEY = "key-SENTINEL-APIKEY-9002";
const REQUEST_TOKEN = "rt-SENTINEL-REQ-9003";
const STATE = "state-SENTINEL-9004";
const RETURN_URL = "http://127.0.0.1:5173/";
const NOW = new Date("2026-11-14T09:00:00.000Z");

const kiteBody = {
  status: "success",
  data: [
    { tradingsymbol: "ACE", exchange: "NSE", isin: "INE00000001", quantity: 100, average_price: 834.1, last_price: 1166, pnl: 1, day_change: 4.9, day_change_percentage: 0.41 },
    { tradingsymbol: "BEE", exchange: "BSE", isin: "INE00000002", quantity: 5, average_price: 10, last_price: 12, pnl: 10, day_change: 0, day_change_percentage: 0 },
  ],
};

function kiteJson(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function fakeSecrets(values: Record<string, string | undefined>) {
  const get = vi.fn(async (name: string): Promise<string | undefined> => values[name]);
  const invalidate = vi.fn((_name: string): void => undefined);
  return { secrets: { get, invalidate }, get, invalidate };
}

function fakeUi(handler: (method: string, path: string, body?: unknown) => UiResponse) {
  const request = vi.fn<UiClient["request"]>(async (method, path, body) => handler(method, path, body));
  const uiClient: UiClient = { request };
  return { uiClient, request };
}

function fakeQuery(opts: { syncRows?: unknown[]; holdingRows?: unknown[]; fail?: boolean } = {}) {
  const calls: Array<{ text: string; values: unknown[] }> = [];
  const query = (async (text: string, values: unknown[]) => {
    calls.push({ text, values });
    if (opts.fail) throw new Error("connection refused");
    if (text.includes("FROM portfolio_sync")) return { rows: opts.syncRows ?? [] };
    return { rows: opts.holdingRows ?? [] };
  }) as unknown as QueryFn;
  return { query, calls };
}

function fakeTx(opts: { failText?: string } = {}) {
  const statements: Array<{ text: string; values: unknown[] }> = [];
  const portfolioTx = vi.fn(async (work: (query: PortfolioQuery) => Promise<unknown>) =>
    work((async (text: string, values: unknown[]) => {
      statements.push({ text, values });
      if (opts.failText && text.includes(opts.failText)) throw new Error("db down");
      return { rowCount: 1 };
    }) as PortfolioQuery),
  );
  return { portfolioTx, statements };
}

interface SetupOpts {
  secrets?: Record<string, string | undefined>;
  ui?: (method: string, path: string, body?: unknown) => UiResponse;
  kiteFetch?: KiteFetch;
  query?: ReturnType<typeof fakeQuery>;
  tx?: ReturnType<typeof fakeTx>;
  returnUrl?: string;
}

async function setup(opts: SetupOpts = {}) {
  const secrets = fakeSecrets(opts.secrets ?? { broker_default_kite_access_token: ACCESS, broker_default_kite_api_key: API_KEY });
  const ui = fakeUi(opts.ui ?? (() => ({ status: 0, body: null })));
  const kiteFetch = vi.fn<KiteFetch>(opts.kiteFetch ?? (async () => kiteJson(200, kiteBody)));
  const query = opts.query ?? fakeQuery();
  const tx = opts.tx ?? fakeTx();
  const app = buildApp({
    query: query.query,
    portfolioTx: tx.portfolioTx as unknown as PortfolioTx,
    broker: {
      secrets: secrets.secrets,
      uiClient: ui.uiClient,
      returnUrl: opts.returnUrl ?? RETURN_URL,
      fetch: kiteFetch,
    },
    // Clock is fixed through the route deps only when needed; the default Date is used otherwise.
  });
  const session = await browserSession(app);
  return { app, session, secrets, ui, kiteFetch, query, tx };
}

function sessionHeaders(session: { cookie: string; csrf: string }) {
  return { cookie: session.cookie, "x-csrf-token": session.csrf };
}

describe("GET /api/broker/:broker/status", () => {
  it("returns 404 for a broker other than kite", async () => {
    const { app, session, ui } = await setup();
    const res = await app.inject({ method: "GET", url: "/api/broker/upstox/status", headers: sessionHeaders(session) });
    expect(res.statusCode).toBe(404);
    expect(ui.request).not.toHaveBeenCalled();
    await app.close();
  });

  it("rejects an invalid profile before calling the ui", async () => {
    const { app, session, ui } = await setup();
    const res = await app.inject({ method: "GET", url: "/api/broker/kite/status?profile=Bad%20Name", headers: sessionHeaders(session) });
    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: "invalid profile" });
    expect(ui.request).not.toHaveBeenCalled();
    await app.close();
  });

  it("returns connected state from the ui for the default profile", async () => {
    const { app, session, ui } = await setup({
      ui: () => ({ status: 200, body: { connected: true, expires_at: "2026-11-14T23:59:00+05:30" } }),
    });
    const res = await app.inject({ method: "GET", url: "/api/broker/kite/status", headers: sessionHeaders(session) });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ connected: true, expiresAt: "2026-11-14T23:59:00+05:30" });
    expect(ui.request).toHaveBeenCalledWith("GET", "/internal/broker/kite/status?profile_id=default");
    await app.close();
  });

  it("returns 502 when the ui is unreachable or answers badly", async () => {
    const down = await setup({ ui: () => ({ status: 0, body: null }) });
    const res1 = await down.app.inject({ method: "GET", url: "/api/broker/kite/status", headers: sessionHeaders(down.session) });
    expect(res1.statusCode).toBe(502);
    await down.app.close();

    const bad = await setup({ ui: () => ({ status: 200, body: { nope: true } }) });
    const res2 = await bad.app.inject({ method: "GET", url: "/api/broker/kite/status", headers: sessionHeaders(bad.session) });
    expect(res2.statusCode).toBe(502);
    expect(res2.json()).toEqual({ error: "broker service unavailable" });
    await bad.app.close();
  });
});

describe("POST /api/broker/:broker/login-url", () => {
  it("returns the login URL from the ui for the default profile", async () => {
    const { app, session, ui } = await setup({
      ui: () => ({ status: 200, body: { url: "https://kite.zerodha.com/connect/login?api_key=abc" } }),
    });
    const res = await app.inject({
      method: "POST",
      url: "/api/broker/kite/login-url",
      headers: sessionHeaders(session),
      payload: {},
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ url: "https://kite.zerodha.com/connect/login?api_key=abc" });
    expect(ui.request).toHaveBeenCalledWith("POST", "/internal/broker/kite/login-url", { profile_id: "default" });
    await app.close();
  });

  it("maps a ui 409 to 409 api key not configured", async () => {
    const { app, session } = await setup({ ui: () => ({ status: 409, body: { error: "x" } }) });
    const res = await app.inject({ method: "POST", url: "/api/broker/kite/login-url", headers: sessionHeaders(session), payload: { profile: "main" } });
    expect(res.statusCode).toBe(409);
    expect(res.json()).toEqual({ error: "api key not configured" });
    await app.close();
  });

  it("rejects an invalid profile in the body with 400", async () => {
    const { app, session, ui } = await setup();
    const res = await app.inject({ method: "POST", url: "/api/broker/kite/login-url", headers: sessionHeaders(session), payload: { profile: "Bad!" } });
    expect(res.statusCode).toBe(400);
    expect(ui.request).not.toHaveBeenCalled();
    await app.close();
  });

  it("returns 502 when the ui answers 200 without a URL", async () => {
    const { app, session } = await setup({ ui: () => ({ status: 200, body: { url: 42 } }) });
    const res = await app.inject({ method: "POST", url: "/api/broker/kite/login-url", headers: sessionHeaders(session), payload: {} });
    expect(res.statusCode).toBe(502);
    await app.close();
  });
});

describe("GET /api/broker/kite/callback", () => {
  const exchangeOk = (profileId = "default") => ({ status: 200, body: { profile_id: profileId } });

  it("redirects with login=failed and calls nothing when the status is not success", async () => {
    const { app, ui } = await setup();
    const res = await app.inject({ method: "GET", url: `/api/broker/kite/callback?status=cancelled&request_token=${REQUEST_TOKEN}&state=${STATE}` });
    expect(res.statusCode).toBe(302);
    expect(res.headers.location).toBe("http://127.0.0.1:5173/?broker=kite&login=failed");
    expect(ui.request).not.toHaveBeenCalled();
    await app.close();
  });

  it("redirects with login=failed when request_token or state is missing", async () => {
    const { app, ui } = await setup();
    const res = await app.inject({ method: "GET", url: `/api/broker/kite/callback?status=success&state=${STATE}` });
    expect(res.headers.location).toContain("login=failed");
    const res2 = await app.inject({ method: "GET", url: `/api/broker/kite/callback?status=success&request_token=${REQUEST_TOKEN}` });
    expect(res2.headers.location).toContain("login=failed");
    expect(ui.request).not.toHaveBeenCalled();
    await app.close();
  });

  it("exchanges the token through the ui, clears the cached access token and redirects with login=ok", async () => {
    const { app, ui, secrets } = await setup({ ui: () => exchangeOk() });
    const res = await app.inject({ method: "GET", url: `/api/broker/kite/callback?status=success&request_token=${REQUEST_TOKEN}&state=${STATE}` });

    expect(ui.request).toHaveBeenCalledWith("POST", "/internal/broker/kite/exchange", { request_token: REQUEST_TOKEN, state: STATE });
    expect(secrets.invalidate).toHaveBeenCalledWith("broker_default_kite_access_token");
    expect(res.statusCode).toBe(302);
    expect(res.headers.location).toBe("http://127.0.0.1:5173/?broker=kite&login=ok");
    expect(res.headers["cache-control"]).toBe("no-store");
    await app.close();
  });

  it("never puts the request token or state in the redirect or the response body", async () => {
    const { app } = await setup({ ui: () => exchangeOk() });
    const res = await app.inject({ method: "GET", url: `/api/broker/kite/callback?status=success&request_token=${REQUEST_TOKEN}&state=${STATE}` });
    expect(res.headers.location).not.toContain(REQUEST_TOKEN);
    expect(res.headers.location).not.toContain(STATE);
    expect(res.body).not.toContain(REQUEST_TOKEN);
    await app.close();
  });

  it("redirects with login=failed and clears nothing when the ui rejects the exchange", async () => {
    const { app, secrets } = await setup({ ui: () => ({ status: 400, body: { error: "state" } }) });
    const res = await app.inject({ method: "GET", url: `/api/broker/kite/callback?status=success&request_token=${REQUEST_TOKEN}&state=${STATE}` });
    expect(res.headers.location).toContain("login=failed");
    expect(secrets.invalidate).not.toHaveBeenCalled();
    await app.close();
  });

  it("treats a malformed profile_id from the ui as failed", async () => {
    const { app, secrets } = await setup({ ui: () => exchangeOk("Not Valid") });
    const res = await app.inject({ method: "GET", url: `/api/broker/kite/callback?status=success&request_token=${REQUEST_TOKEN}&state=${STATE}` });
    expect(res.headers.location).toContain("login=failed");
    expect(secrets.invalidate).not.toHaveBeenCalled();
    await app.close();
  });

  it("keeps existing query parameters of the return URL", async () => {
    const { app } = await setup({ ui: () => exchangeOk(), returnUrl: "http://127.0.0.1:5173/app?view=holdings" });
    const res = await app.inject({ method: "GET", url: `/api/broker/kite/callback?status=success&request_token=${REQUEST_TOKEN}&state=${STATE}` });
    const location = new URL(res.headers.location as string);
    expect(location.searchParams.get("view")).toBe("holdings");
    expect(location.searchParams.get("broker")).toBe("kite");
    expect(location.searchParams.get("login")).toBe("ok");
    await app.close();
  });
});

describe("POST /api/holdings/sync", () => {
  it("rejects a broker other than kite", async () => {
    const { app, session, kiteFetch } = await setup();
    const res = await app.inject({ method: "POST", url: "/api/holdings/sync", headers: sessionHeaders(session), payload: { broker: "upstox" } });
    expect(res.statusCode).toBe(400);
    expect(kiteFetch).not.toHaveBeenCalled();
    await app.close();
  });

  it("rejects an invalid profile with 400", async () => {
    const { app, session, kiteFetch } = await setup();
    const res = await app.inject({ method: "POST", url: "/api/holdings/sync", headers: sessionHeaders(session), payload: { profile: "x y" } });
    expect(res.statusCode).toBe(400);
    expect(kiteFetch).not.toHaveBeenCalled();
    await app.close();
  });

  it("returns 401 login required when no access token is stored", async () => {
    const { app, session, kiteFetch, tx } = await setup({ secrets: { broker_default_kite_api_key: API_KEY } });
    const res = await app.inject({ method: "POST", url: "/api/holdings/sync", headers: sessionHeaders(session), payload: {} });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "login required" });
    expect(kiteFetch).not.toHaveBeenCalled();
    expect(tx.portfolioTx).not.toHaveBeenCalled();
    await app.close();
  });

  it("returns 409 when no api key is configured, without calling Kite", async () => {
    const { app, session, kiteFetch } = await setup({ secrets: { broker_default_kite_access_token: ACCESS } });
    const res = await app.inject({ method: "POST", url: "/api/holdings/sync", headers: sessionHeaders(session), payload: {} });
    expect(res.statusCode).toBe(409);
    expect(res.json()).toEqual({ error: "api key not configured" });
    expect(kiteFetch).not.toHaveBeenCalled();
    await app.close();
  });

  it("uses the global kite_api_key for the default profile", async () => {
    const { app, session, kiteFetch } = await setup({
      secrets: { broker_default_kite_access_token: ACCESS, kite_api_key: API_KEY },
    });
    const res = await app.inject({ method: "POST", url: "/api/holdings/sync", headers: sessionHeaders(session), payload: {} });
    expect(res.statusCode).toBe(200);
    expect(kiteFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: `token ${API_KEY}:${ACCESS}` }) }),
    );
    await app.close();
  });

  it("saves a new ok snapshot and returns the sync summary without any secret", async () => {
    const { app, session, tx } = await setup();
    const res = await app.inject({ method: "POST", url: "/api/holdings/sync", headers: sessionHeaders(session), payload: {} });

    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body).toEqual({ syncedAt: expect.any(String), broker: "kite", rowCount: 2 });
    expect(tx.portfolioTx).toHaveBeenCalledTimes(1);
    expect(tx.statements[0].text).toContain("INSERT INTO portfolio_sync");
    expect(tx.statements[0].values).toContain("ok");
    expect(res.body).not.toContain(ACCESS);
    expect(res.body).not.toContain(API_KEY);
    await app.close();
  });

  it("maps a Kite 403 to the same status with an error and saves nothing", async () => {
    const { app, session, tx } = await setup({ kiteFetch: async () => kiteJson(403, { status: "error" }) });
    const res = await app.inject({ method: "POST", url: "/api/holdings/sync", headers: sessionHeaders(session), payload: {} });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "Kite session expired. Log in again." });
    expect(tx.portfolioTx).not.toHaveBeenCalled();
    await app.close();
  });

  it("returns 500 and no secret when the save fails", async () => {
    const { app, session } = await setup({ tx: fakeTx({ failText: "portfolio_holding" }) });
    const res = await app.inject({ method: "POST", url: "/api/holdings/sync", headers: sessionHeaders(session), payload: {} });
    expect(res.statusCode).toBe(500);
    expect(res.json()).toEqual({ error: "portfolio save failed" });
    expect(res.body).not.toContain(ACCESS);
    await app.close();
  });
});

describe("GET /api/holdings", () => {
  it("rejects an invalid profile with 400", async () => {
    const { app, session } = await setup();
    const res = await app.inject({ method: "GET", url: "/api/holdings?profile=Bad%21", headers: sessionHeaders(session) });
    expect(res.statusCode).toBe(400);
    await app.close();
  });

  it("returns an empty stored view and never calls Kite", async () => {
    const { app, session, kiteFetch } = await setup();
    const res = await app.inject({ method: "GET", url: "/api/holdings", headers: sessionHeaders(session) });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ holdings: [], syncedAt: null, broker: null });
    expect(kiteFetch).not.toHaveBeenCalled();
    await app.close();
  });

  it("returns the stored snapshot without the exchange or any secret", async () => {
    const query = fakeQuery({
      syncRows: [{ sync_id: "s1", synced_at: new Date("2026-11-13T10:00:00.000Z") }],
      holdingRows: [
        { symbol: "ACE", isin: "INE00000001", quantity: "100", average_price: 834.1, last_price: 1166, pnl: 1, day_change: 4.9, day_change_pct: 0.41 },
      ],
    });
    const { app, session, kiteFetch } = await setup({ query });
    const res = await app.inject({ method: "GET", url: "/api/holdings", headers: sessionHeaders(session) });

    expect(res.statusCode).toBe(200);
    expect(res.json().holdings[0]).toMatchObject({ symbol: "ACE", quantity: 100 });
    expect(res.json().broker).toBe("kite");
    expect(res.body).not.toContain("exchange");
    expect(res.body).not.toContain(ACCESS);
    expect(kiteFetch).not.toHaveBeenCalled();
    await app.close();
  });

  it("returns 500 when the database read fails", async () => {
    const { app, session } = await setup({ query: fakeQuery({ fail: true }) });
    const res = await app.inject({ method: "GET", url: "/api/holdings", headers: sessionHeaders(session) });
    expect(res.statusCode).toBe(500);
    expect(res.json()).toEqual({ error: "holdings unavailable" });
    await app.close();
  });
});

describe("broker routes are not registered without broker deps", () => {
  it("serves the holdings path only through the broker routes, so a bare app has no holdings route", async () => {
    const app = buildApp({ query: fakeQuery().query });
    const session = await browserSession(app);
    const res = await app.inject({ method: "GET", url: "/api/holdings", headers: sessionHeaders(session) });
    expect(res.statusCode).toBe(404);
    await app.close();
  });
});
