import { describe, expect, it, vi } from "vitest";
import type { KiteFetch } from "./kiteHoldings.js";
import { fetchUpstoxHoldings, parseUpstoxHoldings, UPSTOX_HOLDINGS_URL } from "./upstoxHoldings.js";

function jsonResponse(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

const TOKEN = "tok-SENTINEL-UPSTOX-9010";

const sampleBody = {
  status: "success",
  data: [
    {
      trading_symbol: "ACE",
      exchange: "NSE",
      isin: "INE00000001",
      quantity: 100,
      average_price: 834.1,
      last_price: 1166,
      close_price: 1160,
      pnl: 33189.55,
      day_change: 4.9,
      day_change_percentage: 0.41,
      product: "CNC",
    },
    { trading_symbol: "", quantity: 5 },
    { trading_symbol: "NOQTY", exchange: "NSE" },
    { trading_symbol: "BAD", quantity: "x" },
    { tradingsymbol: "OLD", quantity: 3 },
    "not an object",
  ],
};

describe("parseUpstoxHoldings", () => {
  it("maps trading_symbol and the other documented fields onto the shared Holding shape", () => {
    expect(parseUpstoxHoldings(sampleBody)).toEqual([
      {
        symbol: "ACE",
        exchange: "NSE",
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

  it("skips rows without a trading_symbol or a numeric quantity", () => {
    const holdings = parseUpstoxHoldings({
      data: [{ quantity: 5 }, { trading_symbol: "X", quantity: null }, { trading_symbol: "Y", quantity: Number.NaN }],
    });
    expect(holdings).toEqual([]);
  });

  it("defaults missing numbers as the Kite parser does and maps empty optional values", () => {
    const [row] = parseUpstoxHoldings({
      data: [{ trading_symbol: "ZED", quantity: 2, isin: "", exchange: 7 }],
    }) ?? [];
    expect(row).toEqual({
      symbol: "ZED",
      exchange: "",
      isin: null,
      quantity: 2,
      averagePrice: 0,
      lastPrice: 0,
      pnl: 0,
      dayChange: null,
      dayChangePct: null,
    });
  });

  it("returns null when the body has no data array", () => {
    expect(parseUpstoxHoldings({ status: "success" })).toBeNull();
    expect(parseUpstoxHoldings(null)).toBeNull();
    expect(parseUpstoxHoldings("text")).toBeNull();
  });
});

describe("fetchUpstoxHoldings", () => {
  it("calls the long-term holdings endpoint with a bearer token and JSON accept header", async () => {
    const fetch = vi.fn<KiteFetch>(async () => jsonResponse(200, sampleBody));
    const result = await fetchUpstoxHoldings({ accessToken: TOKEN, fetch });

    expect(UPSTOX_HOLDINGS_URL).toBe("https://api.upstox.com/v2/portfolio/long-term-holdings");
    expect(fetch).toHaveBeenCalledWith(UPSTOX_HOLDINGS_URL, {
      headers: { Accept: "application/json", Authorization: `Bearer ${TOKEN}` },
    });
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.holdings).toHaveLength(1);
  });

  it("returns login required without calling the network when no token is given", async () => {
    const fetch = vi.fn<KiteFetch>(async () => jsonResponse(200, sampleBody));
    const result = await fetchUpstoxHoldings({ accessToken: undefined, fetch });
    expect(result).toEqual({ ok: false, status: 401, error: "Upstox login required. Log in again." });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("maps 401 to login expired", async () => {
    const result = await fetchUpstoxHoldings({ accessToken: TOKEN, fetch: async () => jsonResponse(401, {}) });
    expect(result).toEqual({ ok: false, status: 401, error: "Upstox login expired. Log in again." });
  });

  it("maps 403 to the static IP message", async () => {
    const result = await fetchUpstoxHoldings({ accessToken: TOKEN, fetch: async () => jsonResponse(403, {}) });
    expect(result).toEqual({
      ok: false,
      status: 403,
      error: "Upstox refused the request. Check the static IP setting for the app.",
    });
  });

  it("maps other non-2xx statuses to 502 without the body", async () => {
    const result = await fetchUpstoxHoldings({ accessToken: TOKEN, fetch: async () => jsonResponse(500, { leak: TOKEN }) });
    expect(result).toEqual({ ok: false, status: 502, error: "Upstox returned status 500." });
    expect(JSON.stringify(result)).not.toContain(TOKEN);
  });

  it("maps a network failure to 502 without the token", async () => {
    const result = await fetchUpstoxHoldings({
      accessToken: TOKEN,
      fetch: async () => {
        throw new Error(`socket reset for ${TOKEN}`);
      },
    });
    expect(result).toEqual({ ok: false, status: 502, error: "Could not reach Upstox." });
  });

  it("maps a body that is not JSON to 502", async () => {
    const result = await fetchUpstoxHoldings({
      accessToken: TOKEN,
      fetch: async () => ({ ok: true, status: 200, json: async () => Promise.reject(new SyntaxError("bad")) }),
    });
    expect(result).toEqual({ ok: false, status: 502, error: "Upstox returned a response that was not valid JSON." });
  });

  it("maps a body without a data array to 502 unexpected shape", async () => {
    const result = await fetchUpstoxHoldings({ accessToken: TOKEN, fetch: async () => jsonResponse(200, { nope: 1 }) });
    expect(result).toEqual({ ok: false, status: 502, error: "Upstox returned an unexpected holdings shape." });
  });
});
