import { browserSession } from "../sessionTestHelper.js";
import { describe, expect, it, vi } from "vitest";
import { buildApp } from "../app.js";
import { fetchKiteHoldings, parseKiteHoldings, type KiteFetch } from "./kiteHoldings.js";

function jsonResponse(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

const sampleBody = {
  status: "success",
  data: [
    {
      tradingsymbol: "ACE",
      isin: "INE00000001",
      quantity: 100,
      average_price: 834.1,
      last_price: 1166,
      pnl: 33189.55,
      day_change: 4.9,
      day_change_percentage: 0.41,
    },
    { tradingsymbol: "", quantity: 5 },
    { tradingsymbol: "BAD", quantity: "x" },
  ],
};

describe("parseKiteHoldings", () => {
  it("keeps valid rows and drops rows without a symbol or quantity", () => {
    const holdings = parseKiteHoldings(sampleBody);
    expect(holdings).toEqual([
      {
        symbol: "ACE",
        isin: "INE00000001",
        quantity: 100,
        averagePrice: 834.1,
        lastPrice: 1166,
        pnl: 33189.55,
        dayChange: 4.9,
        dayChangePct: 0.41,
      },
    ]);
  });

  it("returns null when data is missing", () => {
    expect(parseKiteHoldings({ status: "error" })).toBeNull();
    expect(parseKiteHoldings(null)).toBeNull();
  });
});

describe("fetchKiteHoldings", () => {
  it("reports unconfigured without calling Kite when the key or token is missing", async () => {
    const fetch = vi.fn<KiteFetch>();
    const result = await fetchKiteHoldings({ apiKey: "k", accessToken: undefined, fetch });
    expect(result).toMatchObject({ ok: false, status: 503 });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("sends the Kite auth header and returns the parsed holdings", async () => {
    const fetch = vi.fn<KiteFetch>(async () => jsonResponse(200, sampleBody));
    const result = await fetchKiteHoldings({ apiKey: "key1", accessToken: "tok1", fetch });

    expect(fetch).toHaveBeenCalledWith(
      "https://api.kite.trade/portfolio/holdings",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "token key1:tok1", "X-Kite-Version": "3" }),
      }),
    );
    expect(result.ok && result.holdings).toHaveLength(1);
  });

  it("maps a Kite 403 to 401 with a session-expired message", async () => {
    const fetch = vi.fn<KiteFetch>(async () => jsonResponse(403, { status: "error" }));
    const result = await fetchKiteHoldings({ apiKey: "k", accessToken: "t", fetch });
    expect(result).toEqual({ ok: false, status: 401, error: "Kite session expired. Update KITE_ACCESS_TOKEN." });
  });

  it("maps a network failure to 502", async () => {
    const fetch = vi.fn<KiteFetch>(async () => {
      throw new Error("socket hang up");
    });
    const result = await fetchKiteHoldings({ apiKey: "k", accessToken: "t", fetch });
    expect(result).toMatchObject({ ok: false, status: 502 });
  });
});

describe("GET /api/holdings with async credentials", () => {
  const query = async () => ({ rows: [] });

  it("awaits async credentials and uses them for the Kite call", async () => {
    const fetch = vi.fn<KiteFetch>(async () => jsonResponse(200, sampleBody));
    const app = buildApp({
      query,
      kite: { credentials: async () => ({ apiKey: "key1", accessToken: "secret-token" }), fetch },
    });
    const response = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: "/api/holdings" });

    expect(response.statusCode).toBe(200);
    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "token key1:secret-token" }) }),
    );
    expect(response.body).not.toContain("secret-token");
    await app.close();
  });

  it("reports 503 without calling Kite when async credentials lack an access token", async () => {
    const fetch = vi.fn<KiteFetch>(async () => jsonResponse(200, sampleBody));
    const app = buildApp({ query, kite: { credentials: async () => ({ apiKey: "key1" }), fetch } });
    const response = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: "/api/holdings" });

    expect(response.statusCode).toBe(503);
    expect(fetch).not.toHaveBeenCalled();
    await app.close();
  });
});

describe("GET /api/holdings", () => {
  const query = async () => ({ rows: [] });

  it("returns holdings and never includes the access token in the response", async () => {
    const app = buildApp({
      query,
      kite: { apiKey: "key1", accessToken: "secret-token", fetch: async () => jsonResponse(200, sampleBody) },
    });
    const response = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: "/api/holdings" });

    expect(response.statusCode).toBe(200);
    expect(response.json().holdings[0].symbol).toBe("ACE");
    expect(response.body).not.toContain("secret-token");
    expect(response.body).not.toContain("key1");
    await app.close();
  });

  it("returns 503 when Kite is not configured", async () => {
    const app = buildApp({ query });
    const response = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: "/api/holdings" });
    expect(response.statusCode).toBe(503);
    await app.close();
  });
});
