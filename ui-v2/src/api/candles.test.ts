import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CandlesError, fetchCandles, type CandlesResponse } from "./candles";
import { resetCsrfTokenForTests, SESSION_URL } from "./session";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** Answers GET /api/session with a test token and every other URL with the given read. */
function withSession(read: (url: string, init?: RequestInit) => Promise<Response>) {
  return vi.fn(async (url: string, init?: RequestInit) =>
    url === SESSION_URL ? jsonResponse({ csrfToken: "test-csrf" }) : read(url, init),
  );
}

const BODY: CandlesResponse = {
  symbol: "RELIANCE",
  candles: [
    { date: "2026-11-06", open: 100, high: 105, low: 99, close: 102, volume: 1000 },
    { date: "2026-11-09", open: 102, high: 106, low: 101, close: 104, volume: null },
  ],
};

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchCandles", () => {
  it("requests the encoded symbol path with the query params that are set", async () => {
    const fetchMock = withSession(async () => jsonResponse(BODY));
    vi.stubGlobal("fetch", fetchMock);

    await fetchCandles("M&M", { from: "2026-01-01", limit: 500 });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/stocks/M%26M/candles?from=2026-01-01&limit=500",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("omits the query string when no params are given", async () => {
    const fetchMock = withSession(async () => jsonResponse(BODY));
    vi.stubGlobal("fetch", fetchMock);

    await fetchCandles("RELIANCE");

    // Call 0 is the session fetch that apiGet makes first; call 1 is the candles read.
    expect(fetchMock.mock.calls[1][0]).toBe("/api/stocks/RELIANCE/candles");
  });

  it("returns the parsed body on success", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse(BODY)),
    );

    await expect(fetchCandles("RELIANCE", { limit: 500 })).resolves.toEqual(BODY);
  });

  it("throws a CandlesError when the body has an unexpected shape", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ symbol: "RELIANCE", candles: [{ date: 20261109, open: 1 }] })),
    );

    const error = await fetchCandles("RELIANCE").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(CandlesError);
    expect((error as CandlesError).message).toBe("The candles response had an unexpected shape.");
  });

  it("throws a CandlesError with the status and the server error message on a non-OK response", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ error: "Unknown symbol" }, 404)),
    );

    const error = await fetchCandles("NOPE").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(CandlesError);
    expect((error as CandlesError).status).toBe(404);
    expect((error as CandlesError).message).toBe("Unknown symbol");
  });
});
