import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CollectorStatusError, fetchCollectorStatus } from "./collectorStatus";
import { resetCsrfTokenForTests, SESSION_URL } from "./session";

const STATUS_URL = "/api/collector/status";

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

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchCollectorStatus", () => {
  it("requests /api/collector/status and returns paused and since", async () => {
    const fetchMock = withSession(async () =>
      jsonResponse({ collector: { paused: false, since: "2026-11-16T19:00:00.000+05:30" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchCollectorStatus()).resolves.toEqual({
      paused: false,
      since: "2026-11-16T19:00:00.000+05:30",
    });
    expect(fetchMock.mock.calls.map((call) => call[0])).toContain(STATUS_URL);
  });

  it("returns paused true with since null", async () => {
    vi.stubGlobal("fetch", withSession(async () => jsonResponse({ collector: { paused: true, since: null } })));
    await expect(fetchCollectorStatus()).resolves.toEqual({ paused: true, since: null });
  });

  it("throws a CollectorStatusError with the status for a non-OK response", async () => {
    vi.stubGlobal("fetch", withSession(async () => jsonResponse({ error: "server_down" }, 503)));
    const error = await fetchCollectorStatus().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(CollectorStatusError);
    expect((error as CollectorStatusError).status).toBe(503);
  });

  it("throws a CollectorStatusError with a null status on a network error", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    const error = await fetchCollectorStatus().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(CollectorStatusError);
    expect((error as CollectorStatusError).status).toBeNull();
  });

  it("throws a CollectorStatusError with the status when the body has the wrong shape", async () => {
    vi.stubGlobal("fetch", withSession(async () => jsonResponse({ collector: { paused: "yes", since: null } })));
    const error = await fetchCollectorStatus().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(CollectorStatusError);
    expect((error as CollectorStatusError).status).toBe(200);
  });

  it("rethrows an abort without wrapping it", async () => {
    const abort = Object.assign(new Error("aborted"), { name: "AbortError" });
    vi.stubGlobal(
      "fetch",
      withSession(async () => {
        throw abort;
      }),
    );
    await expect(fetchCollectorStatus()).rejects.toBe(abort);
  });
});
