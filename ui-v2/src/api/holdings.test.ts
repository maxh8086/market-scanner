import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchHoldings, HoldingsError } from "./holdings";
import { resetCsrfTokenForTests, SESSION_URL } from "./session";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === SESSION_URL) {
      return jsonResponse({ csrfToken: "csrf-1" });
    }
    return jsonResponse(body, status);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const HOLDING = {
  symbol: "ACE",
  isin: null,
  quantity: 100,
  averagePrice: 834.1,
  lastPrice: 1166,
  pnl: 33190,
  dayChange: 4.9,
  dayChangePct: 0.41,
};

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchHoldings", () => {
  it("returns the stored snapshot with its sync time and broker", async () => {
    stubFetch({ holdings: [HOLDING], syncedAt: "2026-11-13T10:15:00.000Z", broker: "kite" });

    await expect(fetchHoldings()).resolves.toEqual({
      holdings: [HOLDING],
      syncedAt: "2026-11-13T10:15:00.000Z",
      broker: "kite",
    });
  });

  it("treats a missing sync time and broker as null", async () => {
    stubFetch({ holdings: [] });

    await expect(fetchHoldings()).resolves.toEqual({ holdings: [], syncedAt: null, broker: null });
  });

  it("throws a HoldingsError when the body has no holdings array", async () => {
    stubFetch({ syncedAt: null });

    const error = await fetchHoldings().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(HoldingsError);
    expect((error as HoldingsError).status).toBe(200);
  });
});
