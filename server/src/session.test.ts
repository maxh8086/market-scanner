import http, { type IncomingHttpHeaders } from "node:http";
import type { AddressInfo } from "node:net";
import { describe, expect, it } from "vitest";
import { buildApp, type QueryFn } from "./app.js";
import { createSessionStore, SESSION_TTL_MS, type Session } from "./session.js";
import { browserSession } from "./sessionTestHelper.js";

const PRESET_ID = "9b2e4c1a-3f5d-4e6a-8b7c-0d1e2f3a4b5c";
const VALID_BODY = { name: "A", filters: { bucket: "B" } };

function fakeQuery(rows: Array<Record<string, unknown>> = []): {
  query: QueryFn;
  calls: Array<{ sql: string; values: unknown[] }>;
} {
  const calls: Array<{ sql: string; values: unknown[] }> = [];
  const query: QueryFn = async (sql, values) => {
    calls.push({ sql, values });
    return { rows };
  };
  return { query, calls };
}

describe("GET /api/session", () => {
  it("returns a csrfToken and sets an HttpOnly, SameSite=Strict session cookie", async () => {
    const app = buildApp({ query: fakeQuery().query });
    const res = await app.inject({ method: "GET", url: "/api/session" });
    expect(res.statusCode).toBe(200);
    expect(typeof res.json().csrfToken).toBe("string");
    const setCookie = String(res.headers["set-cookie"]);
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("Secure");
    expect(setCookie).toContain("SameSite=Strict");
    expect(setCookie).toContain("Path=/");
    expect(setCookie).toContain("Max-Age=43200");
    expect(setCookie).toContain("ms_session=");
    await app.close();
  });

  it("returns the same csrfToken for a live session and sends no new cookie", async () => {
    const app = buildApp({ query: fakeQuery().query });
    const first = await browserSession(app);
    const res = await app.inject({ method: "GET", url: "/api/session", headers: { cookie: first.cookie } });
    expect(res.statusCode).toBe(200);
    expect(res.json().csrfToken).toBe(first.csrf);
    expect(res.headers["set-cookie"]).toBeUndefined();
    await app.close();
  });
});

describe("CSRF gate on POST, PUT and DELETE under /api/", () => {
  it("returns 401 session_required when no cookie is sent", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "POST", url: "/api/presets", payload: VALID_BODY });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("returns 403 csrf_required when the cookie is sent without x-csrf-token", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const { cookie } = await browserSession(app);
    const res = await app.inject({
      method: "POST",
      url: "/api/presets",
      headers: { cookie },
      payload: VALID_BODY,
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toEqual({ error: "csrf_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("returns 403 when x-csrf-token is wrong", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const { cookie } = await browserSession(app);
    const res = await app.inject({
      method: "POST",
      url: "/api/presets",
      headers: { cookie, "x-csrf-token": "not-the-token" },
      payload: VALID_BODY,
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toEqual({ error: "csrf_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("returns 403 on DELETE without a token and never runs the route", async () => {
    const { query, calls } = fakeQuery([{ preset_id: PRESET_ID }]);
    const app = buildApp({ query });
    const { cookie } = await browserSession(app);
    const res = await app.inject({
      method: "DELETE",
      url: `/api/presets/${PRESET_ID}`,
      headers: { cookie },
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toEqual({ error: "csrf_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("lets a POST with a matching cookie and token reach the route", async () => {
    const { query, calls } = fakeQuery([{ preset_id: PRESET_ID, name: "A", filters: { bucket: "B" } }]);
    const app = buildApp({ query });
    const { cookie, csrf } = await browserSession(app);
    const res = await app.inject({
      method: "POST",
      url: "/api/presets",
      headers: { cookie, "x-csrf-token": csrf },
      payload: VALID_BODY,
    });
    expect(res.statusCode).toBe(201);
    expect(calls).toHaveLength(1);
    await app.close();
  });

  it("returns 401 for a POST with a cookie whose session has expired", async () => {
    let clock = 1_800_000_000_000;
    const sessions = createSessionStore({ now: () => clock });
    const { query, calls } = fakeQuery();
    const app = buildApp({ query, sessions });
    const { cookie, csrf } = await browserSession(app);
    clock += SESSION_TTL_MS;
    const res = await app.inject({
      method: "POST",
      url: "/api/presets",
      headers: { cookie, "x-csrf-token": csrf },
      payload: VALID_BODY,
    });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("returns 401 session_required for a cross-site POST with no session cookie", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({
      method: "POST",
      url: "/api/presets",
      headers: { "sec-fetch-site": "cross-site" },
      payload: VALID_BODY,
    });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("returns 403 cross_site_request for a valid session and mixed-case Sec-Fetch-Site: Cross-Site", async () => {
    const { query, calls } = fakeQuery([{ preset_id: PRESET_ID, name: "A", filters: { bucket: "B" } }]);
    const app = buildApp({ query });
    const { cookie, csrf } = await browserSession(app);
    const res = await app.inject({
      method: "POST",
      url: "/api/presets",
      headers: { cookie, "x-csrf-token": csrf, "sec-fetch-site": "Cross-Site" },
      payload: VALID_BODY,
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toEqual({ error: "cross_site_request" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("returns 403 csrf_required for a PATCH with a valid session and a wrong x-csrf-token", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    let handlerRan = false;
    app.patch("/api/probe", async () => {
      handlerRan = true;
      return { ok: true };
    });
    const { cookie } = await browserSession(app);
    const res = await app.inject({
      method: "PATCH",
      url: "/api/probe",
      headers: { cookie, "x-csrf-token": "not-the-token" },
      payload: {},
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toEqual({ error: "csrf_required" });
    expect(handlerRan).toBe(false);
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("returns 403 cross_site_request for duplicate Sec-Fetch-Site headers when one is cross-site", async () => {
    const { query, calls } = fakeQuery([{ preset_id: PRESET_ID, name: "A", filters: { bucket: "B" } }]);
    const app = buildApp({ query });
    const { cookie, csrf } = await browserSession(app);
    const res = await app.inject({
      method: "POST",
      url: "/api/presets",
      headers: {
        cookie,
        "x-csrf-token": csrf,
        "sec-fetch-site": ["same-origin", "cross-site"] as unknown as string,
      },
      payload: VALID_BODY,
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toEqual({ error: "cross_site_request" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("does not gate /internal/* routes (no route is registered without checkToken, so 404)", async () => {
    const { query } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({
      method: "POST",
      url: "/internal/events/batch",
      payload: { rows: [] },
    });
    expect(res.statusCode).toBe(404);
    await app.close();
  });

  it("gates GET /internal (no trailing slash) with no cookie: 401 session_required", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/internal" });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("gates GET /internalx/probe with no cookie: 401 session_required", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/internalx/probe" });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("gates GET /Internal/probe with no cookie: 401 session_required", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/Internal/probe" });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });
});

// ---- Gate bypass and hardening tests ----

/** Sends a raw request line over a real socket so the absolute-form target reaches the server unchanged. */
async function rawRequest(
  app: ReturnType<typeof buildApp>,
  method: string,
  target: string,
  headers: Record<string, string> = {},
): Promise<{ status: number; body: string; headers: IncomingHttpHeaders }> {
  await app.listen({ port: 0, host: "127.0.0.1" });
  const address = app.server.address() as AddressInfo;
  try {
    return await new Promise((resolve, reject) => {
      const req = http.request(
        { host: "127.0.0.1", port: address.port, method, path: target, headers },
        (res) => {
          let body = "";
          res.setEncoding("utf8");
          res.on("data", (chunk: string) => {
            body += chunk;
          });
          res.on("end", () =>
            resolve({ status: res.statusCode ?? 0, body, headers: res.headers }),
          );
        },
      );
      req.on("error", reject);
      req.end();
    });
  } finally {
    await app.close();
  }
}

describe("CSRF gate: path encoding, absolute-form targets and methods", () => {
  it("gates a percent-encoded first segment on DELETE (no cookie, no token)", async () => {
    const { query, calls } = fakeQuery([{ preset_id: PRESET_ID }]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "DELETE", url: `/%61pi/presets/${PRESET_ID}` });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("gates a percent-encoded first segment on POST /%61pi/presets (no cookie, no token)", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "POST", url: "/%61pi/presets", payload: VALID_BODY });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("gates a percent-encoded first segment on POST /%61pi/collector/index-eod/refresh", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "POST", url: "/%61pi/collector/index-eod/refresh" });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("gates an absolute-form request target on DELETE over a raw socket", async () => {
    const { query, calls } = fakeQuery([{ preset_id: PRESET_ID }]);
    const app = buildApp({ query });
    const res = await rawRequest(app, "DELETE", `http://127.0.0.1/api/presets/${PRESET_ID}`);
    expect(res.status).toBe(401);
    expect(JSON.parse(res.body)).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
  });

  it("exempts an absolute-form GET http://127.0.0.1/api/health over a raw socket (no cookie)", async () => {
    const { query } = fakeQuery();
    const app = buildApp({ query });
    const res = await rawRequest(app, "GET", "http://127.0.0.1/api/health");
    expect(res.status).toBe(200);
    expect(JSON.parse(res.body)).toEqual({ ok: true });
  });

  it("gates a PATCH under /api (probe route registered in the test app only)", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    let handlerRan = false;
    app.patch("/api/probe", async () => {
      handlerRan = true;
      return { ok: true };
    });
    const res = await app.inject({ method: "PATCH", url: "/api/probe", payload: {} });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(handlerRan).toBe(false);
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it.each(["//api/presets", "/API/presets"])(
    "POST %s without a session is gated with 401 session_required",
    async (url) => {
      const { query, calls } = fakeQuery();
      const app = buildApp({ query });
      const res = await app.inject({ method: "POST", url, payload: VALID_BODY });
      expect(res.statusCode).toBe(401);
      expect(res.json()).toEqual({ error: "session_required" });
      expect(calls).toHaveLength(0);
      await app.close();
    },
  );

  it("does not gate /internal/* (POST /internal/probe without cookie or token is 404)", async () => {
    const { query } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "POST", url: "/internal/probe", payload: {} });
    expect(res.statusCode).toBe(404);
    await app.close();
  });
});

describe("session cookie and Sec-Fetch-Site", () => {
  it("marks the session cookie Secure", async () => {
    const app = buildApp({ query: fakeQuery().query });
    const res = await app.inject({ method: "GET", url: "/api/session" });
    const setCookie = String(res.headers["set-cookie"]);
    expect(setCookie).toContain("Secure");
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("SameSite=Strict");
    expect(setCookie).toContain("Path=/");
    expect(setCookie).toContain("Max-Age=43200");
    await app.close();
  });

  it("returns 403 cross_site_request for a valid cookie and token sent cross-site", async () => {
    const { query, calls } = fakeQuery([{ preset_id: PRESET_ID, name: "A", filters: { bucket: "B" } }]);
    const app = buildApp({ query });
    const { cookie, csrf } = await browserSession(app);
    const res = await app.inject({
      method: "POST",
      url: "/api/presets",
      headers: { cookie, "x-csrf-token": csrf, "sec-fetch-site": "cross-site" },
      payload: VALID_BODY,
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toEqual({ error: "cross_site_request" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("accepts a valid cookie and token sent same-origin", async () => {
    const { query, calls } = fakeQuery([{ preset_id: PRESET_ID, name: "A", filters: { bucket: "B" } }]);
    const app = buildApp({ query });
    const { cookie, csrf } = await browserSession(app);
    const res = await app.inject({
      method: "POST",
      url: "/api/presets",
      headers: { cookie, "x-csrf-token": csrf, "sec-fetch-site": "same-origin" },
      payload: VALID_BODY,
    });
    expect(res.statusCode).toBe(201);
    expect(calls).toHaveLength(1);
    await app.close();
  });
});

describe("createSessionStore bounds and cost", () => {
  it("never holds more than maxSessions and evicts the oldest first", () => {
    let clock = 1_800_000_000_000;
    const store = createSessionStore({ now: () => clock, maxSessions: 3 });
    const created: Session[] = [];
    for (let i = 0; i < 4; i++) {
      created.push(store.create());
      const live = created.filter((s) => store.get(s.id) !== undefined).length;
      expect(live).toBeLessThanOrEqual(3);
    }
    expect(store.get(created[0].id)).toBeUndefined();
    expect(store.get(created[3].id)).toBeDefined();
  });

  it("creates 20000 sessions on one store in under 2000 ms with a fake clock", () => {
    const clock = 1_800_000_000_000;
    const store = createSessionStore({ now: () => clock });
    const start = performance.now();
    for (let i = 0; i < 20_000; i++) store.create();
    const elapsed = performance.now() - start;
    expect(elapsed).toBeLessThan(2000);
  }, 60_000);
});

describe("session required on safe methods under /api/", () => {
  it("returns 401 session_required for GET /api/presets with no cookie and never runs the route", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/api/presets" });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("returns 200 with a presets array for GET /api/presets with a valid session cookie", async () => {
    const { query } = fakeQuery();
    const app = buildApp({ query });
    const { cookie } = await browserSession(app);
    const res = await app.inject({ method: "GET", url: "/api/presets", headers: { cookie } });
    expect(res.statusCode).toBe(200);
    expect(Array.isArray(res.json().presets)).toBe(true);
    await app.close();
  });

  it("returns 200 and sets the session cookie for GET /api/session with no cookie", async () => {
    const app = buildApp({ query: fakeQuery().query });
    const res = await app.inject({ method: "GET", url: "/api/session" });
    expect(res.statusCode).toBe(200);
    expect(String(res.headers["set-cookie"])).toContain("ms_session=");
    await app.close();
  });

  it("does not return the session gate 401 for a /internal/ path with no session", async () => {
    const { query } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/internal/probe" });
    expect(res.statusCode).toBe(404);
    await app.close();
  });

  it.each(["/API/presets", "/%61pi/presets"])(
    "gates GET %s with no cookie: 401 session_required, route not run",
    async (url) => {
      const { query, calls } = fakeQuery();
      const app = buildApp({ query });
      const res = await app.inject({ method: "GET", url });
      expect(res.statusCode).toBe(401);
      expect(res.json()).toEqual({ error: "session_required" });
      expect(calls).toHaveLength(0);
      await app.close();
    },
  );

  it("returns 200 for GET /api/health with no cookie (exact-path exemption)", async () => {
    const app = buildApp({ query: fakeQuery().query });
    const res = await app.inject({ method: "GET", url: "/api/health" });
    expect(res.statusCode).not.toBe(401);
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ ok: true });
    await app.close();
  });

  it("does not exempt POST /api/health: 401 session_required with no cookie", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "POST", url: "/api/health", payload: {} });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("does not exempt /api/healthz (near-miss path): 401 session_required with no cookie", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/api/healthz" });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("does not exempt /api/health/ (trailing slash): 401 session_required with no cookie", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/api/health/" });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "session_required" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("exempts GET /api/health?x=1 (query string stripped by requestPath): 200 with no cookie", async () => {
    const app = buildApp({ query: fakeQuery().query });
    const res = await app.inject({ method: "GET", url: "/api/health?x=1" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ ok: true });
    await app.close();
  });
});
