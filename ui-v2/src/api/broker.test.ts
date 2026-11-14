import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetCsrfTokenForTests, SESSION_URL } from "./session";
import { BrokerError, fetchBrokerStatus, LOGIN_REQUIRED_MESSAGE, requestLoginUrl, syncPortfolio } from "./broker";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    clone: () => jsonResponse(body, status),
  } as unknown as Response;
}

/** Stubs fetch: the session route always answers with a token; every other URL goes to the given router. */
function stubFetch(route: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === SESSION_URL) {
      return jsonResponse({ csrfToken: "csrf-1" });
    }
    return route(url, init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function callsTo(fetchMock: ReturnType<typeof vi.fn>, url: string) {
  return fetchMock.mock.calls.filter(([called]) => called === url);
}

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchBrokerStatus", () => {
  it("reads the connection state for the default profile", async () => {
    const fetchMock = stubFetch(() => jsonResponse({ connected: true, expiresAt: "2026-11-14T00:30:00.000Z" }));

    await expect(fetchBrokerStatus("kite")).resolves.toEqual({
      connected: true,
      expiresAt: "2026-11-14T00:30:00.000Z",
    });
    expect(callsTo(fetchMock, "/api/broker/kite/status?profile=default")).toHaveLength(1);
  });

  it("reports not connected with a null expiry", async () => {
    stubFetch(() => jsonResponse({ connected: false, expiresAt: null }));

    await expect(fetchBrokerStatus("kite")).resolves.toEqual({ connected: false, expiresAt: null });
  });

  it("throws a typed error with the server message and status on a failed response", async () => {
    stubFetch(() => jsonResponse({ error: "broker service unavailable" }, 502));

    const error = await fetchBrokerStatus("kite").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(BrokerError);
    expect((error as BrokerError).message).toBe("broker service unavailable");
    expect((error as BrokerError).status).toBe(502);
  });

  it("reports a network failure with a null status", async () => {
    stubFetch(() => {
      throw new TypeError("network down");
    });

    const error = await fetchBrokerStatus("kite").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(BrokerError);
    expect((error as BrokerError).status).toBeNull();
  });

  it("rejects a body without a boolean connected field", async () => {
    stubFetch(() => jsonResponse({ expiresAt: null }));

    await expect(fetchBrokerStatus("kite")).rejects.toThrow("unexpected shape");
  });
});

describe("requestLoginUrl", () => {
  it("posts the profile with the CSRF header and returns the login URL", async () => {
    const loginUrl = "https://kite.zerodha.com/connect/login?v=3&api_key=test";
    const fetchMock = stubFetch(() => jsonResponse({ url: loginUrl }));

    await expect(requestLoginUrl("kite")).resolves.toBe(loginUrl);
    const [, init] = callsTo(fetchMock, "/api/broker/kite/login-url")[0];
    expect(init).toMatchObject({ method: "POST", body: JSON.stringify({ profile: "default" }) });
    expect((init as RequestInit).headers).toMatchObject({ "X-CSRF-Token": "csrf-1" });
  });

  it("retries once with a fresh token after a session_required rejection", async () => {
    let attempts = 0;
    const fetchMock = stubFetch(() => {
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse({ error: "session_required" }, 401);
      }
      return jsonResponse({ url: "https://kite.zerodha.com/connect/login" });
    });

    await expect(requestLoginUrl("kite")).resolves.toBe("https://kite.zerodha.com/connect/login");
    expect(callsTo(fetchMock, "/api/broker/kite/login-url")).toHaveLength(2);
    expect(callsTo(fetchMock, SESSION_URL)).toHaveLength(2);
  });

  it("throws the server message when no api key is configured", async () => {
    stubFetch(() => jsonResponse({ detail: "api key not configured" }, 409));

    const error = await requestLoginUrl("kite").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(BrokerError);
    expect((error as BrokerError).status).toBe(409);
  });

  it("rejects a login URL that is not https", async () => {
    stubFetch(() => jsonResponse({ url: "javascript:alert(1)" }));

    await expect(requestLoginUrl("kite")).rejects.toThrow("unexpected shape");
  });
});

describe("syncPortfolio", () => {
  it("posts the profile and broker and returns the sync result", async () => {
    const fetchMock = stubFetch(() =>
      jsonResponse({ syncedAt: "2026-11-13T10:15:00.000Z", broker: "kite", rowCount: 3 }),
    );

    await expect(syncPortfolio("kite")).resolves.toEqual({
      syncedAt: "2026-11-13T10:15:00.000Z",
      broker: "kite",
      rowCount: 3,
    });
    const [, init] = callsTo(fetchMock, "/api/holdings/sync")[0];
    expect(init).toMatchObject({ method: "POST" });
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ profile: "default", broker: "kite" });
  });

  it("maps a 401 to the login required message", async () => {
    stubFetch(() => jsonResponse({ error: "login required" }, 401));

    const error = await syncPortfolio("kite").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(BrokerError);
    expect((error as BrokerError).message).toBe(LOGIN_REQUIRED_MESSAGE);
    expect((error as BrokerError).status).toBe(401);
  });

  it("keeps the server message for other failures", async () => {
    stubFetch(() => jsonResponse({ error: "Kite session expired. Log in again." }, 403));

    const error = await syncPortfolio("kite").catch((caught: unknown) => caught);
    expect((error as BrokerError).message).toBe("Kite session expired. Log in again.");
    expect((error as BrokerError).status).toBe(403);
  });

  it("rejects a body that is not a sync result", async () => {
    stubFetch(() => jsonResponse({ broker: "upstox", rowCount: 1 }));

    await expect(syncPortfolio("kite")).rejects.toThrow("unexpected shape");
  });
});
