import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CollectorRefreshError, requestIndexEodRefresh } from "./collectorRefresh";
import { resetCsrfTokenForTests, SESSION_URL } from "./session";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function emptyResponse(status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      throw new SyntaxError("no body");
    },
  } as unknown as Response;
}

/** Answers GET /api/session with the next token in the list and sends every other URL to the handler. */
function sessionWithTokens(
  tokens: string[],
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>,
) {
  let issued = 0;
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url === SESSION_URL) {
      const token = tokens[Math.min(issued, tokens.length - 1)];
      issued += 1;
      return jsonResponse({ csrfToken: token });
    }
    return handler(url, init);
  });
}

function postCount(fetchMock: ReturnType<typeof sessionWithTokens>): number {
  return fetchMock.mock.calls.filter(([url]) => url !== SESSION_URL).length;
}

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("requestIndexEodRefresh", () => {
  it("maps 202 to queued and 409 to market_open without a retry", async () => {
    const fetchMock = sessionWithTokens(["token-a"], () => emptyResponse(202));
    vi.stubGlobal("fetch", fetchMock);
    await expect(requestIndexEodRefresh()).resolves.toEqual({ kind: "queued" });
    expect(postCount(fetchMock)).toBe(1);

    const marketOpen = sessionWithTokens(["token-a"], () => emptyResponse(409));
    vi.stubGlobal("fetch", marketOpen);
    await expect(requestIndexEodRefresh()).resolves.toEqual({ kind: "market_open" });
    expect(postCount(marketOpen)).toBe(1);
  });

  it("retries a 403 csrf_required refresh once with a freshly fetched token and returns queued", async () => {
    const sentTokens: unknown[] = [];
    const fetchMock = sessionWithTokens(["stale-token", "fresh-token"], (_url, init) => {
      sentTokens.push((init?.headers as Record<string, string>)["X-CSRF-Token"]);
      return sentTokens.length === 1 ? jsonResponse({ error: "csrf_required" }, 403) : emptyResponse(202);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(requestIndexEodRefresh()).resolves.toEqual({ kind: "queued" });
    expect(sentTokens).toEqual(["stale-token", "fresh-token"]);
    expect(fetchMock.mock.calls.filter(([url]) => url === SESSION_URL)).toHaveLength(2);
  });

  it("retries a 401 session_required refresh once and returns already_queued on 200", async () => {
    let writes = 0;
    const fetchMock = sessionWithTokens(["expired-token", "new-token"], () => {
      writes += 1;
      return writes === 1 ? jsonResponse({ error: "session_required" }, 401) : jsonResponse({}, 200);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(requestIndexEodRefresh()).resolves.toEqual({ kind: "already_queued" });
    expect(writes).toBe(2);
  });

  it("surfaces the error after two gate rejections in a row and makes no third write", async () => {
    let writes = 0;
    const fetchMock = sessionWithTokens(["token-a", "token-b", "token-c"], () => {
      writes += 1;
      return jsonResponse({ error: "csrf_required" }, 403);
    });
    vi.stubGlobal("fetch", fetchMock);

    const error = await requestIndexEodRefresh().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(CollectorRefreshError);
    expect(error).toMatchObject({ message: "csrf_required", status: 403 });
    expect(writes).toBe(2);
  });

  it("does not retry a 403 cross_site_request", async () => {
    let writes = 0;
    const fetchMock = sessionWithTokens(["token-a", "token-b"], () => {
      writes += 1;
      return jsonResponse({ error: "cross_site_request" }, 403);
    });
    vi.stubGlobal("fetch", fetchMock);

    const error = await requestIndexEodRefresh().catch((e: unknown) => e);
    expect(error).toMatchObject({ message: "cross_site_request", status: 403 });
    expect(writes).toBe(1);
  });

  it("throws a network error when the /api/session fetch rejects", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === SESSION_URL) {
        throw new TypeError("Failed to fetch");
      }
      return emptyResponse(202);
    });
    vi.stubGlobal("fetch", fetchMock);

    const error = await requestIndexEodRefresh().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(CollectorRefreshError);
    expect(error).toMatchObject({ message: "Network error", status: null });
    expect(postCount(fetchMock)).toBe(0);
  });
});
