import type { FastifyInstance } from "fastify";
import { afterEach, describe, expect, it, vi } from "vitest";
import { buildApp, HEALTH_PING_TIMEOUT_MS } from "./app.js";

const apps: FastifyInstance[] = [];
const FIXED_503_BODY = { ok: false, error: "events_database_unavailable" };

afterEach(async () => {
  vi.useRealTimers();
  await Promise.all(apps.splice(0).map((app) => app.close()));
});

function appWith(eventsPing?: () => Promise<void>): FastifyInstance {
  const app = buildApp({
    query: async () => ({ rows: [] }),
    ...(eventsPing ? { eventsPing } : {}),
  });
  apps.push(app);
  return app;
}

describe("GET /api/health with the events ping", () => {
  it("returns 200 {ok:true} when no ping is wired", async () => {
    const app = appWith();
    const res = await app.inject({ method: "GET", url: "/api/health" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ ok: true });
  });

  it("returns 200 {ok:true} when the ping resolves, with no session cookie", async () => {
    const app = appWith(async () => undefined);
    const res = await app.inject({ method: "GET", url: "/api/health" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ ok: true });
  });

  it("returns the fixed 503 body and hides the error text when the ping rejects", async () => {
    const app = appWith(async () => {
      throw new Error("connect failed: secret-dsn");
    });
    const res = await app.inject({ method: "GET", url: "/api/health" });
    expect(res.statusCode).toBe(503);
    expect(res.headers["cache-control"]).toBe("no-store");
    expect(res.body).not.toContain("secret-dsn");
    expect(res.json()).toEqual(FIXED_503_BODY);
  });

  it("returns 503 when the ping never resolves", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const app = appWith(() => new Promise<void>(() => undefined));
    const pending = app.inject({ method: "GET", url: "/api/health" });
    await vi.advanceTimersByTimeAsync(HEALTH_PING_TIMEOUT_MS);
    const res = await pending;
    expect(res.statusCode).toBe(503);
    expect(res.headers["cache-control"]).toBe("no-store");
    expect(res.json()).toEqual(FIXED_503_BODY);
  });
});
