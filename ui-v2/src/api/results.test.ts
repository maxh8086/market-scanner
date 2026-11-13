import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildResultsQueryString,
  fetchResults,
  ResultsError,
  type ResultsPage,
} from "./results";
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

const PAGE: ResultsPage = { results: [], total: 0, page: 1, perPage: 50 };

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildResultsQueryString", () => {
  it("includes only the params that are set", () => {
    expect(
      buildResultsQueryString({ page: 2, perPage: 50, sort: undefined, search: "" }),
    ).toBe("page=2&perPage=50");
  });

  it("keeps zero and negative numbers", () => {
    expect(buildResultsQueryString({ ltpMin: 0, distanceMax: -5 })).toBe(
      "ltpMin=0&distanceMax=-5",
    );
  });

  it("encodes text values", () => {
    expect(buildResultsQueryString({ search: "A&B" })).toBe("search=A%26B");
  });

  it("returns an empty string for an empty query", () => {
    expect(buildResultsQueryString({})).toBe("");
  });
});

describe("fetchResults", () => {
  it("requests the run path with the query string and returns the page", async () => {
    const body: ResultsPage = {
      results: [
        {
          symbol: "RELIANCE",
          company: "Reliance Industries",
          industry: "Oil & Gas",
          ltp: 2950.5,
          distance_pct: -4.2,
          ath_date: "2026-08-01",
          one_year_return_pct: 12.3,
          order_pct_of_sales: null,
          stance: "Watch",
          bucket: "A",
          changed: false,
        },
      ],
      total: 1,
      page: 1,
      perPage: 50,
    };
    const fetchMock = withSession(async () => jsonResponse(body));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchResults("2026-11-09", { page: 1, perPage: 50, sort: "ltp", order: "desc" });

    // Call 0 is the session fetch that apiGet makes first; call 1 is the results read.
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/runs/2026-11-09/results?page=1&perPage=50&sort=ltp&order=desc",
    );
    expect(result).toEqual(body);
  });

  it("omits the query string when no params are given", async () => {
    const fetchMock = withSession(async () => jsonResponse(PAGE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchResults("abc");

    expect(fetchMock.mock.calls[1][0]).toBe("/api/runs/abc/results");
  });

  it("throws a ResultsError with the server message on a 404", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ error: "Run not found" }, 404)),
    );

    const error = await fetchResults("missing").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ResultsError);
    expect((error as ResultsError).message).toBe("Run not found");
    expect((error as ResultsError).status).toBe(404);
  });

  it("uses a generic message when an error body is not JSON", async () => {
    const response = {
      ok: false,
      status: 500,
      json: async () => {
        throw new SyntaxError("bad json");
      },
    } as unknown as Response;
    vi.stubGlobal(
      "fetch",
      withSession(async () => response),
    );

    const error = (await fetchResults("abc").catch((e: unknown) => e)) as ResultsError;

    expect(error.message).toBe("Request failed with status 500.");
    expect(error.status).toBe(500);
  });

  it("throws a ResultsError with a null status on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    const error = (await fetchResults("abc").catch((e: unknown) => e)) as ResultsError;

    expect(error).toBeInstanceOf(ResultsError);
    expect(error.status).toBeNull();
    expect(error.message).toBe("Could not reach the results service.");
  });

  it("rethrows an abort without wrapping it", async () => {
    const abort = new DOMException("aborted", "AbortError");
    vi.stubGlobal(
      "fetch",
      withSession(async () => {
        throw abort;
      }),
    );

    await expect(fetchResults("abc")).rejects.toBe(abort);
  });

  it("rejects a 200 response with an unexpected body", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ nope: true })),
    );

    await expect(fetchResults("abc")).rejects.toBeInstanceOf(ResultsError);
  });
});
