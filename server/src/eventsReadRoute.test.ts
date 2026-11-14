import type { FastifyInstance } from "fastify";
import { afterEach, describe, expect, it } from "vitest";
import { buildApp } from "./app.js";
import { browserSession } from "./sessionTestHelper.js";

type Row = Record<string, unknown>;

const apps: FastifyInstance[] = [];

afterEach(async () => {
  await Promise.all(apps.splice(0).map((app) => app.close()));
});

interface FakeOptions {
  events?: Row[];
  latest?: unknown;
  noLatestRow?: boolean;
  error?: unknown;
}

/** Fake events query. The latest-fetched query is recognised by its max(fetched_at) text. */
function fakeEvents(options: FakeOptions = {}) {
  const calls: Array<{ sql: string; values: unknown[] }> = [];
  const eventsQuery = async (sql: string, values: unknown[]) => {
    calls.push({ sql, values });
    if (options.error !== undefined) throw options.error;
    if (sql.includes("max(fetched_at)")) {
      return { rows: options.noLatestRow ? [] : [{ latest: options.latest ?? null }] };
    }
    return { rows: options.events ?? [] };
  };
  return { eventsQuery, calls };
}

async function buildTestApp(options?: FakeOptions, withEvents = true): Promise<FastifyInstance> {
  const fake = fakeEvents(options);
  const app = buildApp({
    query: async () => ({ rows: [] }),
    ...(withEvents ? { eventsQuery: fake.eventsQuery } : {}),
  });
  apps.push(app);
  await app.ready();
  return Object.assign(app, { fakeCalls: fake.calls });
}

function callsOf(app: FastifyInstance): Array<{ sql: string; values: unknown[] }> {
  return (app as FastifyInstance & { fakeCalls: Array<{ sql: string; values: unknown[] }> }).fakeCalls;
}

const TWO_ROWS: Row[] = [
  {
    dedupe_key: "nse:Financial_Results:1",
    symbol: "ABC",
    isin: "INE000A01010",
    company: "ABC Ltd",
    event_type: "results",
    feed_tier: "high_priority",
    feed_code: "Sast_Regulation31",
    headline: "Quarterly results",
    published_at: new Date("2026-11-14T12:30:00Z"),
    fetched_at: new Date("2026-11-14T12:35:02Z"),
    source_url: "https://www.nseindia.com/a",
  },
  {
    dedupe_key: "nse:Corporate_action:2",
    symbol: "XYZ",
    isin: "INE000B01010",
    company: "XYZ Ltd",
    event_type: "corporate_action",
    feed_tier: "catalyst",
    feed_code: "Corporate_action",
    headline: "Record date set",
    published_at: "2026-11-14T10:00:00Z",
    fetched_at: "2026-11-14T10:01:00Z",
    source_url: "https://www.nseindia.com/b",
  },
];

describe("GET /api/events 200 response", () => {
  it("returns generated_at, latest_fetched_at, window_days and the mapped events", async () => {
    const app = await buildTestApp({ events: TWO_ROWS, latest: new Date("2026-11-14T12:35:03Z") });
    const session = await browserSession(app);
    const res = await app.inject({ method: "GET", url: "/api/events", headers: { cookie: session.cookie } });

    expect(res.statusCode).toBe(200);
    const body = res.json() as Record<string, unknown>;
    expect(body.generated_at).toMatch(/\+05:30$/);
    expect(body.latest_fetched_at).toBe("2026-11-14T18:05:03.000+05:30");
    expect(body.window_days).toBe(7);
    expect(body.events).toEqual([
      {
        id: "nse:Financial_Results:1",
        symbol: "ABC",
        isin: "INE000A01010",
        company: "ABC Ltd",
        event_type: "results",
        feed_tier: "high_priority",
        feed_code: "Sast_Regulation31",
        headline: "Quarterly results",
        published_at: "2026-11-14T18:00:00.000+05:30",
        fetched_at: "2026-11-14T18:05:02.000+05:30",
        source_url: "https://www.nseindia.com/a",
      },
      {
        id: "nse:Corporate_action:2",
        symbol: "XYZ",
        isin: "INE000B01010",
        company: "XYZ Ltd",
        event_type: "corporate_action",
        feed_tier: "catalyst",
        feed_code: "Corporate_action",
        headline: "Record date set",
        published_at: "2026-11-14T15:30:00.000+05:30",
        fetched_at: "2026-11-14T15:31:00.000+05:30",
        source_url: "https://www.nseindia.com/b",
      },
    ]);
  });

  it("returns latest_fetched_at null when the newest value is null", async () => {
    const app = await buildTestApp({ events: [], latest: null });
    const session = await browserSession(app);
    const res = await app.inject({ method: "GET", url: "/api/events", headers: { cookie: session.cookie } });
    expect(res.statusCode).toBe(200);
    expect((res.json() as Row).latest_fetched_at).toBeNull();
    expect((res.json() as Row).events).toEqual([]);
  });

  it("returns latest_fetched_at null when the latest query has no row", async () => {
    const app = await buildTestApp({ events: [], noLatestRow: true });
    const session = await browserSession(app);
    const res = await app.inject({ method: "GET", url: "/api/events", headers: { cookie: session.cookie } });
    expect((res.json() as Row).latest_fetched_at).toBeNull();
  });

  it("echoes window_days and passes the parsed params to the query values", async () => {
    const app = await buildTestApp({ events: [], latest: null });
    const session = await browserSession(app);
    const res = await app.inject({
      method: "GET",
      url: "/api/events?days=3&tier=catalyst&limit=5&symbol=abc",
      headers: { cookie: session.cookie },
    });
    expect(res.statusCode).toBe(200);
    expect((res.json() as Row).window_days).toBe(3);
    const calls = callsOf(app);
    expect(calls[0].values).toEqual([3, "catalyst", "ABC", 5]);
    expect(calls[1].values).toEqual([3]);
  });
});

describe("GET /api/events invalid_query", () => {
  it.each(["days=0", "days=31", "limit=201", "tier=other", "symbol=bad%20sym", "days=", "days=1&days=2"])(
    "answers 400 for %s without running a query",
    async (qs) => {
      const app = await buildTestApp({ events: [], latest: null });
      const session = await browserSession(app);
      const res = await app.inject({ method: "GET", url: `/api/events?${qs}`, headers: { cookie: session.cookie } });
      expect(res.statusCode).toBe(400);
      expect(res.json()).toEqual({ error: "invalid_query" });
      expect(callsOf(app)).toEqual([]);
    },
  );
});

describe("GET /api/events errors", () => {
  it("answers 503 with the fixed body on a connection error", async () => {
    const connectionError = Object.assign(new Error("terminated"), { code: "08006" });
    const app = await buildTestApp({ error: connectionError });
    const session = await browserSession(app);
    const res = await app.inject({ method: "GET", url: "/api/events", headers: { cookie: session.cookie } });
    expect(res.statusCode).toBe(503);
    expect(res.json()).toEqual({ error: "events_database_unavailable" });
  });

  it("answers 500 with the fixed body and no error text on any other error", async () => {
    const app = await buildTestApp({ error: new Error("secret-dsn") });
    const session = await browserSession(app);
    const res = await app.inject({ method: "GET", url: "/api/events", headers: { cookie: session.cookie } });
    expect(res.statusCode).toBe(500);
    expect(res.body).not.toContain("secret-dsn");
    expect(res.json()).toEqual({ error: "internal_error" });
  });
});

describe("GET /api/events cache and session", () => {
  it("sets Cache-Control no-store on 200, 400, 503 and 500", async () => {
    const session200 = await buildTestApp({ events: [], latest: null });
    const s1 = await browserSession(session200);
    const ok = await session200.inject({ method: "GET", url: "/api/events", headers: { cookie: s1.cookie } });
    const bad = await session200.inject({ method: "GET", url: "/api/events?days=0", headers: { cookie: s1.cookie } });
    expect(ok.headers["cache-control"]).toBe("no-store");
    expect(bad.headers["cache-control"]).toBe("no-store");

    const app503 = await buildTestApp({ error: Object.assign(new Error("x"), { code: "08006" }) });
    const s2 = await browserSession(app503);
    const unavailable = await app503.inject({ method: "GET", url: "/api/events", headers: { cookie: s2.cookie } });
    expect(unavailable.headers["cache-control"]).toBe("no-store");

    const app500 = await buildTestApp({ error: new Error("boom") });
    const s3 = await browserSession(app500);
    const failed = await app500.inject({ method: "GET", url: "/api/events", headers: { cookie: s3.cookie } });
    expect(failed.headers["cache-control"]).toBe("no-store");
  });

  it("answers without a session cookie the same way another read route does", async () => {
    const app = await buildTestApp({ events: [], latest: null });
    const events = await app.inject({ method: "GET", url: "/api/events" });
    const otherRead = await app.inject({ method: "GET", url: "/api/index-eod" });
    expect(events.statusCode).toBe(401);
    expect(events.json()).toEqual({ error: "session_required" });
    expect(events.statusCode).toBe(otherRead.statusCode);
    expect(events.json()).toEqual(otherRead.json());
    expect(callsOf(app)).toEqual([]);
  });

  it("is not registered when eventsQuery is not passed", async () => {
    const app = await buildTestApp(undefined, false);
    const session = await browserSession(app);
    const res = await app.inject({ method: "GET", url: "/api/events", headers: { cookie: session.cookie } });
    expect(res.statusCode).toBe(404);
  });
});
