import { describe, expect, it, vi } from "vitest";
import { fetchKiteHoldings, parseKiteHoldings, type KiteFetch } from "./kiteHoldings.js";

function jsonResponse(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

const sampleBody = {
  status: "success",
  data: [
    {
      tradingsymbol: "ACE",
      exchange: "NSE",
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

  it("uses an empty exchange when Kite omits it", () => {
    const holdings = parseKiteHoldings({ status: "success", data: [{ tradingsymbol: "XYZ", quantity: 1 }] });
    expect(holdings?.[0].exchange).toBe("");
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
    expect(result).toEqual({ ok: false, status: 401, error: "Kite session expired. Log in again." });
  });

  it("maps a network failure to 502", async () => {
    const fetch = vi.fn<KiteFetch>(async () => {
      throw new Error("socket hang up");
    });
    const result = await fetchKiteHoldings({ apiKey: "k", accessToken: "t", fetch });
    expect(result).toMatchObject({ ok: false, status: 502 });
  });
});
