import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetCsrfTokenForTests, SESSION_URL } from "./session";
import { fetchSectorSummary, SectorSummaryError, type SectorSummaryResponse } from "./sectorSummary";

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

const BODY: SectorSummaryResponse = {
  period: "1w",
  sectors: [
    { sector: "IT", count: 10, avgChangePct: 1.23, advancers: 6, decliners: 4 },
    { sector: "Banks", count: 5, avgChangePct: -0.87, advancers: 1, decliners: 4 },
  ],
};

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchSectorSummary", () => {
  it("requests the encoded run path with the period query", async () => {
    const fetchMock = withSession(async () => jsonResponse(BODY));
    vi.stubGlobal("fetch", fetchMock);

    await fetchSectorSummary("run/42", "1w");

    // Call 0 is the session fetch that apiGet makes first; call 1 is the sector-summary read.
    expect(fetchMock.mock.calls[1][0]).toBe("/api/runs/run%2F42/sector-summary?period=1w");
  });

  it("returns the parsed body on success", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse(BODY)),
    );

    await expect(fetchSectorSummary("run-42", "1w")).resolves.toEqual(BODY);
  });

  it("throws a SectorSummaryError when a sector has an unexpected shape", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ period: "1d", sectors: [{ sector: "IT", count: "10" }] })),
    );

    const error = await fetchSectorSummary("run-42", "1d").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(SectorSummaryError);
    expect((error as SectorSummaryError).message).toBe("The sector summary response had an unexpected shape.");
  });

  it("throws a SectorSummaryError with the status and the server error message on a non-OK response", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ error: "period must be one of 1d, 1w" }, 400)),
    );

    const error = await fetchSectorSummary("run-42", "1d").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(SectorSummaryError);
    expect((error as SectorSummaryError).status).toBe(400);
    expect((error as SectorSummaryError).message).toBe("period must be one of 1d, 1w");
  });
});
