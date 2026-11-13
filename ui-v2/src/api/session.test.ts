import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getCsrfToken, invalidateCsrfToken, resetCsrfTokenForTests, SESSION_URL } from "./session";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getCsrfToken", () => {
  it("calls GET /api/session once and returns the token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ csrfToken: "abc123" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getCsrfToken()).resolves.toBe("abc123");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(SESSION_URL, { credentials: "same-origin" });
  });

  it("reuses the cached token on later calls without fetching again", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ csrfToken: "abc123" }));
    vi.stubGlobal("fetch", fetchMock);

    await getCsrfToken();
    await expect(getCsrfToken()).resolves.toBe("abc123");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("throws on a failed response and retries on the next call", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ error: "down" }, 500))
      .mockResolvedValueOnce(jsonResponse({ csrfToken: "retry-token" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getCsrfToken()).rejects.toThrow("Could not start a session.");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await expect(getCsrfToken()).resolves.toBe("retry-token");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("invalidateCsrfToken", () => {
  it("makes the next getCsrfToken fetch a new session", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ csrfToken: "old-token" }))
      .mockResolvedValueOnce(jsonResponse({ csrfToken: "new-token" }));
    vi.stubGlobal("fetch", fetchMock);

    const first = getCsrfToken();
    await expect(first).resolves.toBe("old-token");
    invalidateCsrfToken(first);
    await expect(getCsrfToken()).resolves.toBe("new-token");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("ignores a stale promise and keeps a newer cached token", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ csrfToken: "old-token" }))
      .mockResolvedValueOnce(jsonResponse({ csrfToken: "new-token" }));
    vi.stubGlobal("fetch", fetchMock);

    const stale = getCsrfToken();
    await expect(stale).resolves.toBe("old-token");
    invalidateCsrfToken(stale);
    const newer = getCsrfToken();
    await expect(newer).resolves.toBe("new-token");

    invalidateCsrfToken(stale);
    await expect(getCsrfToken()).resolves.toBe("new-token");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("getCsrfToken concurrency and failures", () => {
  it("shares one fetch between two calls made before either resolves", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ csrfToken: "shared" }));
    vi.stubGlobal("fetch", fetchMock);

    const a = getCsrfToken();
    const b = getCsrfToken();
    await expect(Promise.all([a, b])).resolves.toEqual(["shared", "shared"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects when fetch rejects, then fetches again on the next call", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse({ csrfToken: "after-failure" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getCsrfToken()).rejects.toThrow("Failed to fetch");
    await expect(getCsrfToken()).resolves.toBe("after-failure");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
