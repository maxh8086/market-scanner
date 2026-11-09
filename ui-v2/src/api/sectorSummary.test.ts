import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchSectorSummary, SectorSummaryError, type SectorSummaryResponse } from "./sectorSummary";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

const BODY: SectorSummaryResponse = {
  period: "1w",
  sectors: [
    { sector: "IT", count: 10, avgChangePct: 1.23, advancers: 6, decliners: 4 },
    { sector: "Banks", count: 5, avgChangePct: -0.87, advancers: 1, decliners: 4 },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchSectorSummary", () => {
  it("requests the encoded run path with the period query", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(BODY));
    vi.stubGlobal("fetch", fetchMock);

    await fetchSectorSummary("run/42", "1w");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/runs/run%2F42/sector-summary?period=1w");
  });

  it("returns the parsed body on success", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(BODY)));

    await expect(fetchSectorSummary("run-42", "1w")).resolves.toEqual(BODY);
  });

  it("throws a SectorSummaryError when a sector has an unexpected shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ period: "1d", sectors: [{ sector: "IT", count: "10" }] })),
    );

    const error = await fetchSectorSummary("run-42", "1d").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(SectorSummaryError);
    expect((error as SectorSummaryError).message).toBe("The sector summary response had an unexpected shape.");
  });

  it("throws a SectorSummaryError with the status and the server error message on a non-OK response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "period must be one of 1d, 1w" }, 400)));

    const error = await fetchSectorSummary("run-42", "1d").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(SectorSummaryError);
    expect((error as SectorSummaryError).status).toBe(400);
    expect((error as SectorSummaryError).message).toBe("period must be one of 1d, 1w");
  });
});
