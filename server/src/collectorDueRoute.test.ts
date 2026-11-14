import Fastify, { type FastifyInstance } from "fastify";
import { afterEach, describe, expect, it } from "vitest";
import { buildApp, type QueryResult } from "./app.js";
import { buildDueQueries, type ServicesFile } from "./collectorDue.js";
import { registerCollectorDueRoute, type CollectorDueAuthResult } from "./collectorDueRoute.js";
import { checkIngestToken } from "./homeEventsAuth.js";

const TOKEN = "fake-watchdog-token-for-tests";
const apps: FastifyInstance[] = [];

afterEach(async () => {
  await Promise.all(apps.splice(0).map((app) => app.close()));
});

interface Tables {
  settings?: Array<Record<string, unknown>>;
  lastOk?: Array<Record<string, unknown>>;
  lastAttempt?: Array<Record<string, unknown>>;
  requests?: Array<Record<string, unknown>>;
  cooldowns?: Array<Record<string, unknown>>;
}

/** Fake QueryFn keyed by the exact SQL text. An error, when given, rejects every query. */
function fakeQuery(tables: Tables = {}, error?: unknown) {
  const q = buildDueQueries();
  const calls: string[] = [];
  const query = async (sql: string): Promise<QueryResult> => {
    calls.push(sql);
    if (error !== undefined) throw error;
    const rows =
      sql === q.settings ? tables.settings
      : sql === q.lastOk ? tables.lastOk
      : sql === q.lastAttempt ? tables.lastAttempt
      : sql === q.requests ? tables.requests
      : sql === q.cooldowns ? tables.cooldowns
      : undefined;
    return { rows: rows ?? [] };
  };
  return { query, calls };
}

const checkToken = (authorization: string | undefined, role: "collector_watchdog"): CollectorDueAuthResult =>
  checkIngestToken(authorization, role, { collector_watchdog: TOKEN });

const MON_1900 = new Date("2026-11-16T19:00:00+05:30");
const AUTH = { authorization: `Bearer ${TOKEN}` };

function services(sources: ServicesFile["sources"]) {
  return () => ({ sources });
}

async function buildTestApp(options: {
  tables?: Tables;
  error?: unknown;
  services?: () => ServicesFile;
  now?: Date;
}): Promise<FastifyInstance> {
  const app = buildApp({
    query: fakeQuery(options.tables, options.error).query,
    collectorDue: {
      checkToken,
      loadServices: options.services ?? services({ case_src: { service: "case_src", host: "nse" } }),
      now: () => options.now ?? MON_1900,
    },
  });
  apps.push(app);
  await app.ready();
  return app;
}

const dueTables: Tables = {
  settings: [{ source: "case_src", mode: "scheduled", cron: "35 18 * * 1-5" }],
};

describe("GET /internal/due", () => {
  it("answers 401 with no authorization header", async () => {
    const app = await buildTestApp({ tables: dueTables });
    const res = await app.inject({ method: "GET", url: "/internal/due" });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "unauthorized" });
  });

  it("answers 401 for a wrong token, and runs no query", async () => {
    const q = fakeQuery(dueTables);
    const app = buildApp({
      query: q.query,
      collectorDue: { checkToken, loadServices: services({}) },
    });
    apps.push(app);
    const res = await app.inject({
      method: "GET",
      url: "/internal/due",
      headers: { authorization: "Bearer not-the-token" },
    });
    expect(res.statusCode).toBe(401);
    expect(q.calls).toEqual([]);
  });

  it("answers 200 with an empty list for an empty services file", async () => {
    const app = await buildTestApp({ tables: dueTables, services: services({}), now: MON_1900 });
    const res = await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { generated_at: string; sources: unknown[] };
    expect(body.sources).toEqual([]);
    expect(body.generated_at).toMatch(/\+05:30$/);
  });

  it("answers 200 with a due source and its fields", async () => {
    const app = await buildTestApp({ tables: dueTables });
    const res = await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect(res.statusCode).toBe(200);
    expect((res.json() as { sources: unknown[] }).sources).toEqual([
      { name: "case_src", service: "case_src", reason: "catchup", request_id: null, order: 1 },
    ]);
  });

  it("never returns a source that is not in the services file", async () => {
    const app = await buildTestApp({
      tables: {
        settings: [
          { source: "ghost", mode: "scheduled", cron: "35 18 * * 1-5" },
          { source: "case_src", mode: "scheduled", cron: "35 18 * * 1-5" },
        ],
      },
    });
    const res = await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    const body = res.json() as { sources: Array<{ name: string }> };
    expect(body.sources.map((s) => s.name)).toEqual(["case_src"]);
  });

  it("omits a source whose host cooldown is active and returns it once expired", async () => {
    const active = await buildTestApp({
      tables: {
        ...dueTables,
        cooldowns: [{ host: "nse", cooldown_until: "2026-11-16T19:30:00+05:30" }],
      },
    });
    const omitted = await active.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect((omitted.json() as { sources: unknown[] }).sources).toEqual([]);

    const expired = await buildTestApp({
      tables: {
        ...dueTables,
        cooldowns: [{ host: "nse", cooldown_until: "2026-11-16T18:50:00+05:30" }],
      },
    });
    const returned = await expired.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect((returned.json() as { sources: Array<{ name: string }> }).sources.map((s) => s.name)).toEqual(["case_src"]);
  });

  it("answers 503 on a connection-class database error, with a fixed body", async () => {
    const app = await buildTestApp({
      error: Object.assign(new Error("connect ECONNREFUSED 10.0.0.5:5432"), { code: "ECONNREFUSED" }),
    });
    const res = await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect(res.statusCode).toBe(503);
    expect(res.json()).toEqual({ error: "database_unavailable" });
    expect(res.body).not.toContain("10.0.0.5");
  });

  it("answers 500 on another error, and the body has no SQL", async () => {
    const app = await buildTestApp({ error: new Error("SELECT secret FROM collector_settings failed") });
    const res = await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect(res.statusCode).toBe(500);
    expect(res.json()).toEqual({ error: "due_failed" });
    expect(res.body).not.toContain("SELECT");
  });

  it("answers 500 when the services file cannot be read, with a fixed body", async () => {
    const app = await buildTestApp({
      services: () => {
        throw new Error("ENOENT: /secret/path/collector_services.json");
      },
    });
    const res = await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect(res.statusCode).toBe(500);
    expect(res.json()).toEqual({ error: "services_unavailable" });
    expect(res.body).not.toContain("secret/path");
  });

  it("sends Cache-Control no-store on success and on 401", async () => {
    const app = await buildTestApp({ tables: dueTables });
    const ok = await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect(ok.headers["cache-control"]).toBe("no-store");
    const denied = await app.inject({ method: "GET", url: "/internal/due" });
    expect(denied.headers["cache-control"]).toBe("no-store");
  });

  it("is not registered when collectorDue is not set", async () => {
    const app = buildApp({ query: fakeQuery().query });
    apps.push(app);
    const res = await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect(res.statusCode).toBe(404);
  });
});

describe("registerCollectorDueRoute poll time", () => {
  async function appWithClock(clock: { now: Date }) {
    const app = Fastify();
    const route = registerCollectorDueRoute(app, {
      query: fakeQuery().query,
      checkToken,
      loadServices: () => ({ sources: {} }),
      now: () => clock.now,
    });
    apps.push(app);
    await app.ready();
    return { app, route };
  }

  it("is null before any poll, set after an authenticated poll, and unchanged by a 401", async () => {
    const clock = { now: new Date("2026-11-16T19:00:00+05:30") };
    const { app, route } = await appWithClock(clock);
    expect(route.getLastDuePollAt()).toBeNull();

    await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect(route.getLastDuePollAt()?.getTime()).toBe(clock.now.getTime());

    clock.now = new Date("2026-11-16T19:05:00+05:30");
    await app.inject({ method: "GET", url: "/internal/due", headers: { authorization: "Bearer wrong" } });
    expect(route.getLastDuePollAt()?.getTime()).toBe(new Date("2026-11-16T19:00:00+05:30").getTime());
  });

  it("is set even when the authenticated poll fails", async () => {
    const clock = { now: new Date("2026-11-16T19:00:00+05:30") };
    const app = Fastify();
    const route = registerCollectorDueRoute(app, {
      query: fakeQuery({}, new Error("boom")).query,
      checkToken,
      loadServices: () => ({ sources: {} }),
      now: () => clock.now,
    });
    apps.push(app);
    await app.ready();
    const res = await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect(res.statusCode).toBe(500);
    expect(route.getLastDuePollAt()?.getTime()).toBe(clock.now.getTime());
  });
});
