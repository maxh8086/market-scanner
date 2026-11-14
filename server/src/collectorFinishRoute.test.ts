import Fastify, { type FastifyInstance } from "fastify";
import { afterEach, describe, expect, it } from "vitest";
import { buildApp, type QueryResult } from "./app.js";
import type { ServicesFile } from "./collectorDue.js";
import { type CollectorDueAuthResult, registerCollectorDueRoute } from "./collectorDueRoute.js";
import { FINISH_KILLED_SQL, registerCollectorFinishRoute } from "./collectorFinishRoute.js";
import { checkIngestToken } from "./homeEventsAuth.js";

const TOKEN = "fake-watchdog-token-for-tests";
const AUTH = { authorization: `Bearer ${TOKEN}` };
const apps: FastifyInstance[] = [];

afterEach(async () => {
  await Promise.all(apps.splice(0).map((app) => app.close()));
});

const checkToken = (authorization: string | undefined, role: "collector_watchdog"): CollectorDueAuthResult =>
  checkIngestToken(authorization, role, { collector_watchdog: TOKEN });

interface Call {
  sql: string;
  values: unknown[];
}

/** Fake QueryFn. It records every call. `rows` is the result rows; `error`, when given, rejects the call. */
function fakeQuery(rows: Array<Record<string, unknown>> = [], error?: unknown) {
  const calls: Call[] = [];
  const query = async (sql: string, values: unknown[]): Promise<QueryResult> => {
    calls.push({ sql, values });
    if (error !== undefined) throw error;
    return { rows };
  };
  return { query, calls };
}

function services(sources: ServicesFile["sources"] = { case_src: { service: "case_src", host: "nse" } }) {
  return () => ({ sources });
}

function buildTestApp(options: {
  rows?: Array<Record<string, unknown>>;
  error?: unknown;
  services?: () => ServicesFile;
}) {
  const q = fakeQuery(options.rows, options.error);
  const app = buildApp({
    query: q.query,
    collectorDue: { checkToken, loadServices: options.services ?? services() },
  });
  apps.push(app);
  return { app, calls: q.calls };
}

function post(app: FastifyInstance, payload: unknown, headers: Record<string, string> = AUTH) {
  return app.inject({
    method: "POST",
    url: "/internal/due/finish",
    headers,
    ...(payload === undefined ? {} : { payload: payload as Record<string, unknown> }),
  });
}

describe("POST /internal/due/finish", () => {
  it("answers 401 with no authorization header, and runs no query", async () => {
    const { app, calls } = buildTestApp({ rows: [{ id: "r1" }] });
    await app.ready();
    const res = await post(app, { source: "case_src" }, {});
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "unauthorized" });
    expect(calls).toEqual([]);
  });

  it("answers 401 for a wrong token, and runs no query", async () => {
    const { app, calls } = buildTestApp({ rows: [{ id: "r1" }] });
    await app.ready();
    const res = await post(app, { source: "case_src" }, { authorization: "Bearer not-the-token" });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ error: "unauthorized" });
    expect(calls).toEqual([]);
  });

  it("answers 400 invalid_body for a missing body, and runs no query", async () => {
    const { app, calls } = buildTestApp({});
    await app.ready();
    const res = await post(app, undefined);
    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: "invalid_body" });
    expect(calls).toEqual([]);
  });

  it.each([
    ["a number", { source: 5 }],
    ["null", { source: null }],
    ["an array body", ["case_src"]],
    ["an empty string", { source: "" }],
    ["upper case", { source: "CASE_SRC" }],
    ["a dash", { source: "case-src" }],
    ["a space", { source: "case src" }],
    ["an SQL fragment", { source: "case_src; DROP TABLE x" }],
    ["101 characters", { source: "a".repeat(101) }],
    ["an extra field only", { other: "case_src" }],
  ])("answers 400 invalid_body for %s, and runs no query", async (_label, payload) => {
    const { app, calls } = buildTestApp({});
    await app.ready();
    const res = await post(app, payload);
    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: "invalid_body" });
    expect(calls).toEqual([]);
  });

  it("accepts a source of exactly 100 characters when it is in the services file", async () => {
    const name = "a".repeat(100);
    const { app, calls } = buildTestApp({
      rows: [{ id: "r1" }],
      services: services({ [name]: { service: name } }),
    });
    await app.ready();
    const res = await post(app, { source: name });
    expect(res.statusCode).toBe(200);
    expect(calls[0]?.values).toEqual([name]);
  });

  it("answers 400 unknown_source for a source not in the services file, and runs no query", async () => {
    const { app, calls } = buildTestApp({ rows: [{ id: "r1" }] });
    await app.ready();
    const res = await post(app, { source: "ghost" });
    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: "unknown_source" });
    expect(calls).toEqual([]);
  });

  it("answers 200 finalised 1 when a running row was marked failed", async () => {
    const { app, calls } = buildTestApp({ rows: [{ id: "run-1" }] });
    await app.ready();
    const res = await post(app, { source: "case_src" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ finalised: 1 });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.sql).toContain("status = 'running'");
    expect(calls[0]?.sql).toBe(FINISH_KILLED_SQL);
  });

  it("passes the source as a bound parameter and never interpolates it into the SQL", async () => {
    const { app, calls } = buildTestApp({ rows: [{ id: "run-1" }] });
    await app.ready();
    await post(app, { source: "case_src" });
    expect(calls[0]?.values).toEqual(["case_src"]);
    expect(calls[0]?.sql).not.toContain("case_src");
    expect(calls[0]?.sql).toContain("$1");
  });

  it("answers 200 finalised 0 when no running row exists", async () => {
    const { app } = buildTestApp({ rows: [] });
    await app.ready();
    const res = await post(app, { source: "case_src" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ finalised: 0 });
  });

  it("answers 503 database_unavailable on a connection-class error, with a fixed body", async () => {
    const { app } = buildTestApp({
      error: Object.assign(new Error("connect ECONNREFUSED 10.0.0.5:5432"), { code: "ECONNREFUSED" }),
    });
    await app.ready();
    const res = await post(app, { source: "case_src" });
    expect(res.statusCode).toBe(503);
    expect(res.json()).toEqual({ error: "database_unavailable" });
    expect(res.body).not.toContain("10.0.0.5");
  });

  it("answers 500 finish_failed on another error, and the body has no SQL", async () => {
    const { app } = buildTestApp({ error: new Error("UPDATE collector_runs SET status failed") });
    await app.ready();
    const res = await post(app, { source: "case_src" });
    expect(res.statusCode).toBe(500);
    expect(res.json()).toEqual({ error: "finish_failed" });
    expect(res.body).not.toContain("UPDATE");
    expect(res.body).not.toContain("collector_runs");
  });

  it("answers 500 services_unavailable when the services file cannot be read, with a fixed body", async () => {
    const { app, calls } = buildTestApp({
      rows: [{ id: "r1" }],
      services: () => {
        throw new Error("ENOENT: /secret/path/collector_services.json");
      },
    });
    await app.ready();
    const res = await post(app, { source: "case_src" });
    expect(res.statusCode).toBe(500);
    expect(res.json()).toEqual({ error: "services_unavailable" });
    expect(res.body).not.toContain("secret/path");
    expect(calls).toEqual([]);
  });

  it("sends Cache-Control no-store on success and on 401", async () => {
    const { app } = buildTestApp({ rows: [{ id: "r1" }] });
    await app.ready();
    const ok = await post(app, { source: "case_src" });
    expect(ok.headers["cache-control"]).toBe("no-store");
    const denied = await post(app, { source: "case_src" }, {});
    expect(denied.headers["cache-control"]).toBe("no-store");
  });

  it("is not registered when collectorDue is not set", async () => {
    const app = buildApp({ query: fakeQuery().query });
    apps.push(app);
    await app.ready();
    const res = await post(app, { source: "case_src" });
    expect(res.statusCode).toBe(404);
  });
});

describe("finish route does not change the poll time", () => {
  it("leaves getLastDuePollAt unchanged after a finish call", async () => {
    const pollAt = new Date("2026-11-16T19:00:00+05:30");
    const app = Fastify();
    apps.push(app);
    const q = fakeQuery([{ id: "run-1" }]);
    const due = registerCollectorDueRoute(app, {
      query: q.query,
      checkToken,
      loadServices: services(),
      now: () => pollAt,
    });
    registerCollectorFinishRoute(app, { query: q.query, checkToken, loadServices: services() });
    await app.ready();

    expect(due.getLastDuePollAt()).toBeNull();
    const res = await post(app, { source: "case_src" });
    expect(res.statusCode).toBe(200);
    expect(due.getLastDuePollAt()).toBeNull();

    await app.inject({ method: "GET", url: "/internal/due", headers: AUTH });
    expect(due.getLastDuePollAt()?.getTime()).toBe(pollAt.getTime());

    await post(app, { source: "case_src" });
    expect(due.getLastDuePollAt()?.getTime()).toBe(pollAt.getTime());
  });
});
