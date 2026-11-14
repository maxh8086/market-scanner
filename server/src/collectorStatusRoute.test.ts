import type { FastifyInstance } from "fastify";
import { afterEach, describe, expect, it } from "vitest";
import { buildApp, type QueryResult } from "./app.js";
import { buildDueQueries } from "./collectorDue.js";
import { checkIngestToken } from "./homeEventsAuth.js";
import { browserSession } from "./sessionTestHelper.js";

const TOKEN = "fake-watchdog-token-for-tests";
const AUTH = { authorization: `Bearer ${TOKEN}` };
const apps: FastifyInstance[] = [];

afterEach(async () => {
  await Promise.all(apps.splice(0).map((app) => app.close()));
});

const checkToken = (authorization: string | undefined) =>
  checkIngestToken(authorization, "collector_watchdog", { collector_watchdog: TOKEN });

/** Every due query returns no rows; the poll itself is what matters here. */
function emptyQuery() {
  const q = buildDueQueries();
  const known = new Set([q.settings, q.lastOk, q.lastAttempt, q.requests, q.cooldowns]);
  return async (sql: string): Promise<QueryResult> => {
    if (!known.has(sql)) throw new Error(`unexpected sql: ${sql}`);
    return { rows: [] };
  };
}

async function buildTestApp(clock: { now: Date }, withWatchdog = true): Promise<FastifyInstance> {
  const app = buildApp({
    query: emptyQuery(),
    ...(withWatchdog
      ? {
          collectorDue: {
            checkToken,
            loadServices: () => ({ sources: {} }),
            now: () => clock.now,
          },
        }
      : {}),
  });
  apps.push(app);
  await app.ready();
  return app;
}

describe("GET /api/collector/status", () => {
  it("is not registered without collectorDue (404)", async () => {
    const app = await buildTestApp({ now: new Date("2026-11-16T19:00:00+05:30") }, false);
    const session = await browserSession(app);
    const res = await app.inject({
      method: "GET",
      url: "/api/collector/status",
      headers: { cookie: session.cookie },
    });
    expect(res.statusCode).toBe(404);
  });

  it("is paused with since null before any poll, and sends no-store", async () => {
    const app = await buildTestApp({ now: new Date("2026-11-16T19:00:00+05:30") });
    const session = await browserSession(app);
    const res = await app.inject({
      method: "GET",
      url: "/api/collector/status",
      headers: { cookie: session.cookie },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ collector: { paused: true, since: null } });
    expect(res.headers["cache-control"]).toBe("no-store");
  });

  it("is not paused after an authenticated /internal/due poll, then paused after 4 minutes", async () => {
    const clock = { now: new Date("2026-11-16T19:00:00+05:30") };
    const app = await buildTestApp(clock);
    const session = await browserSession(app);

    const poll = await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect(poll.statusCode).toBe(200);

    const fresh = await app.inject({
      method: "GET",
      url: "/api/collector/status",
      headers: { cookie: session.cookie },
    });
    const freshBody = fresh.json() as { collector: { paused: boolean; since: string | null } };
    expect(freshBody.collector.paused).toBe(false);
    expect(freshBody.collector.since).toBe("2026-11-16T19:00:00.000+05:30");

    clock.now = new Date("2026-11-16T19:04:00+05:30");
    const stale = await app.inject({
      method: "GET",
      url: "/api/collector/status",
      headers: { cookie: session.cookie },
    });
    expect(stale.json()).toEqual({ collector: { paused: true, since: "2026-11-16T19:00:00.000+05:30" } });
  });

  it("answers without a session cookie the same way another read route does", async () => {
    const app = await buildTestApp({ now: new Date("2026-11-16T19:00:00+05:30") });
    const status = await app.inject({ method: "GET", url: "/api/collector/status" });
    const otherRead = await app.inject({ method: "GET", url: "/api/index-eod" });
    expect(status.statusCode).toBe(401);
    expect(status.json()).toEqual({ error: "session_required" });
    expect(status.statusCode).toBe(otherRead.statusCode);
    expect(status.json()).toEqual(otherRead.json());
  });
});
