import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPreset, deletePreset, listPresets, PresetsError, type Preset } from "./presets";
import { resetCsrfTokenForTests, SESSION_URL } from "./session";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function noContentResponse(): Response {
  return { ok: true, status: 204, json: async () => { throw new SyntaxError("no body"); } } as unknown as Response;
}

/** Answers GET /api/session with a test token and sends every other URL to the handler. */
function sessionAwareFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url === SESSION_URL) {
      return jsonResponse({ csrfToken: "test-csrf" });
    }
    return handler(url, init);
  });
}

const PRESET: Preset = {
  preset_id: "7",
  name: "Watch A",
  filters: { bucket: "A", ltpMin: 100 },
  created_at: "2026-11-09T00:00:00Z",
  updated_at: "2026-11-09T00:00:00Z",
};

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("listPresets", () => {
  it("GETs /api/presets and returns the presets", async () => {
    const fetchMock = sessionAwareFetch(() => jsonResponse({ presets: [PRESET] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listPresets()).resolves.toEqual([PRESET]);
    expect(fetchMock).toHaveBeenCalledWith("/api/presets", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: undefined,
    });
    // Two calls: the session fetch apiGet makes first, then the presets read.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("passes the abort signal through", async () => {
    const fetchMock = sessionAwareFetch(() => jsonResponse({ presets: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await listPresets({ signal: controller.signal });
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ signal: controller.signal });
  });

  it("maps a server error to PresetsError with the error field as the message", async () => {
    vi.stubGlobal("fetch", sessionAwareFetch(() => jsonResponse({ error: "db down" }, 500)));

    const error = await listPresets().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PresetsError);
    expect(error).toMatchObject({ message: "db down", status: 500 });
  });

  it("maps a network failure to PresetsError with a null status", async () => {
    vi.stubGlobal(
      "fetch",
      sessionAwareFetch(() => {
        throw new TypeError("Failed to fetch");
      }),
    );

    const error = await listPresets().catch((e: unknown) => e);
    expect(error).toMatchObject({ status: null, message: "Could not reach the presets service." });
  });

  it("rejects a body without a presets array", async () => {
    vi.stubGlobal("fetch", sessionAwareFetch(() => jsonResponse({ rows: [] })));

    await expect(listPresets()).rejects.toMatchObject({ status: 200 });
  });
});

describe("createPreset", () => {
  it("POSTs the name and filters as JSON with the CSRF header and returns the created row", async () => {
    const fetchMock = sessionAwareFetch((url, init) => {
      expect(init).toMatchObject({ headers: { "X-CSRF-Token": "test-csrf" } });
      return jsonResponse(PRESET, 201);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(createPreset("Watch A", { bucket: "A", ltpMin: 100 })).resolves.toEqual(PRESET);
    expect(fetchMock).toHaveBeenCalledWith("/api/presets", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": "test-csrf" },
      body: JSON.stringify({ name: "Watch A", filters: { bucket: "A", ltpMin: 100 } }),
    });
  });

  it("maps a 400 to PresetsError carrying the server message", async () => {
    vi.stubGlobal("fetch", sessionAwareFetch(() => jsonResponse({ error: "name is required" }, 400)));

    const error = await createPreset("", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PresetsError);
    expect(error).toMatchObject({ message: "name is required", status: 400 });
  });
});

describe("deletePreset", () => {
  it("DELETEs the encoded preset path with the CSRF header and resolves on 204", async () => {
    const fetchMock = sessionAwareFetch(() => noContentResponse());
    vi.stubGlobal("fetch", fetchMock);

    await expect(deletePreset("a/b")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith("/api/presets/a%2Fb", {
      method: "DELETE",
      headers: { "X-CSRF-Token": "test-csrf" },
    });
  });

  it("maps a 404 to PresetsError with a generic message when the body has none", async () => {
    vi.stubGlobal("fetch", sessionAwareFetch(() => jsonResponse({}, 404)));

    const error = await deletePreset("9").catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 404, message: "Request failed with status 404." });
  });
});

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

function sentToken(init: RequestInit | undefined): unknown {
  return (init?.headers as Record<string, string> | undefined)?.["X-CSRF-Token"];
}

function sessionFetches(fetchMock: ReturnType<typeof sessionWithTokens>): number {
  return fetchMock.mock.calls.filter(([url]) => url === SESSION_URL).length;
}

describe("gate rejection retry on writes", () => {
  it("retries a 403 csrf_required create exactly once with a freshly fetched token", async () => {
    const sentTokens: unknown[] = [];
    const fetchMock = sessionWithTokens(["stale-token", "fresh-token"], (_url, init) => {
      sentTokens.push(sentToken(init));
      return sentTokens.length === 1 ? jsonResponse({ error: "csrf_required" }, 403) : jsonResponse(PRESET, 201);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(createPreset("Watch A", { bucket: "A" })).resolves.toEqual(PRESET);
    expect(sentTokens).toEqual(["stale-token", "fresh-token"]);
    expect(sessionFetches(fetchMock)).toBe(2);
  });

  it("retries a 401 session_required delete once and resolves on 204", async () => {
    let writes = 0;
    const fetchMock = sessionWithTokens(["expired-token", "new-token"], () => {
      writes += 1;
      return writes === 1 ? jsonResponse({ error: "session_required" }, 401) : noContentResponse();
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(deletePreset("9")).resolves.toBeUndefined();
    expect(writes).toBe(2);
  });

  it("surfaces the error after two gate rejections in a row and makes no third write", async () => {
    let writes = 0;
    const fetchMock = sessionWithTokens(["token-a", "token-b", "token-c"], () => {
      writes += 1;
      return jsonResponse({ error: "csrf_required" }, 403);
    });
    vi.stubGlobal("fetch", fetchMock);

    const error = await createPreset("Watch A", { bucket: "A" }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PresetsError);
    expect(error).toMatchObject({ message: "csrf_required", status: 403 });
    expect(writes).toBe(2);
    expect(sessionFetches(fetchMock)).toBe(2);
  });

  it("does not retry a 403 cross_site_request", async () => {
    let writes = 0;
    const fetchMock = sessionWithTokens(["token-a", "token-b"], () => {
      writes += 1;
      return jsonResponse({ error: "cross_site_request" }, 403);
    });
    vi.stubGlobal("fetch", fetchMock);

    const error = await deletePreset("9").catch((e: unknown) => e);
    expect(error).toMatchObject({ message: "cross_site_request", status: 403 });
    expect(writes).toBe(1);
    expect(sessionFetches(fetchMock)).toBe(1);
  });
});

describe("session start failure on writes", () => {
  it("maps a network failure on /api/session to the presets network message", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === SESSION_URL) {
        throw new TypeError("Failed to fetch");
      }
      return jsonResponse(PRESET, 201);
    });
    vi.stubGlobal("fetch", fetchMock);

    const error = await createPreset("Watch A", { bucket: "A" }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PresetsError);
    expect(error).toMatchObject({ message: "Could not reach the presets service.", status: null });
    expect(fetchMock.mock.calls.filter(([url]) => url !== SESSION_URL)).toHaveLength(0);
  });
});
