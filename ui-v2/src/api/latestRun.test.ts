import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchLatestRun, LatestRunError } from "./latestRun";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchLatestRun", () => {
  it("requests the latest run path and returns the run", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ runId: "run-42", runDate: "2026-11-09" }));
    vi.stubGlobal("fetch", fetchMock);

    const run = await fetchLatestRun();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/runs/latest");
    expect(run).toEqual({ runId: "run-42", runDate: "2026-11-09" });
  });

  it("throws a typed 'No current run' error on 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ error: "no run" }, 404)),
    );

    const error = await fetchLatestRun().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(LatestRunError);
    expect((error as LatestRunError).message).toBe("No current run");
    expect((error as LatestRunError).status).toBe(404);
  });

  it("throws a LatestRunError with the server message on other failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ error: "database down" }, 500)),
    );

    const error = await fetchLatestRun().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(LatestRunError);
    expect((error as LatestRunError).message).toBe("database down");
    expect((error as LatestRunError).status).toBe(500);
  });

  it("throws a LatestRunError when the network request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const error = await fetchLatestRun().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(LatestRunError);
    expect((error as LatestRunError).status).toBeNull();
  });

  it("rejects a body without a runId", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ runDate: "2026-11-09" })),
    );

    await expect(fetchLatestRun()).rejects.toBeInstanceOf(LatestRunError);
  });
});
