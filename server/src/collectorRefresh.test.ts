import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildApp, type QueryResult } from "./app.js";
import {
  buildIndexEodRefreshInsert,
  buildLastIndexEodRunQuery,
  isBeforeCloseOnTradingDayIst,
  lastRefreshedAtFromRow,
  lastRunSecondsFromRow,
} from "./collectorRefresh.js";

// IST is UTC+05:30 with no DST, so these instants are fixed.
function ist(y: number, m: number, d: number, hh: number, mm: number): Date {
  return new Date(Date.UTC(y, m - 1, d, hh - 5, mm - 30));
}

beforeEach(() => {
  // Only Date is faked, so Fastify inject keeps its real timers.
  vi.useFakeTimers({ toFake: ["Date"] });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("isBeforeCloseOnTradingDayIst", () => {
  it("is true on a weekday before 15:30 IST and false from 15:30", () => {
    expect(isBeforeCloseOnTradingDayIst(ist(2026, 11, 9, 10, 0))).toBe(true);
    expect(isBeforeCloseOnTradingDayIst(ist(2026, 11, 9, 15, 29))).toBe(true);
    expect(isBeforeCloseOnTradingDayIst(ist(2026, 11, 9, 15, 30))).toBe(false);
  });

  it("is false on weekends at any time", () => {
    // Saturday 2026-11-07 and Sunday 2026-11-08
    expect(isBeforeCloseOnTradingDayIst(ist(2026, 11, 7, 10, 0))).toBe(false);
    expect(isBeforeCloseOnTradingDayIst(ist(2026, 11, 8, 9, 0))).toBe(false);
  });
});

describe("buildIndexEodRefreshInsert", () => {
  it("uses bound values only and the index_eod source", () => {
    const insert = buildIndexEodRefreshInsert("11111111-1111-4111-8111-111111111111");
    expect(insert.sql).toContain("INSERT INTO collector_requests (id, source, requested_at)");
    expect(insert.sql).toContain("ON CONFLICT DO NOTHING");
    expect(insert.values).toEqual(["11111111-1111-4111-8111-111111111111", "index_eod"]);
  });
});

describe("POST /api/collector/index-eod/refresh", () => {
  it("responds 409 before 15:30 IST on a weekday and does not touch the database", async () => {
    vi.setSystemTime(ist(2026, 11, 9, 11, 0));
    const calls: unknown[][] = [];
    const query = async (...args: unknown[]): Promise<QueryResult> => {
      calls.push(args);
      return { rows: [] };
    };
    const app = buildApp({ query });
    const response = await app.inject({ method: "POST", url: "/api/collector/index-eod/refresh" });
    expect(response.statusCode).toBe(409);
    expect(response.json()).toEqual({
      error: "market_hours",
      message: "Refresh opens after 15:30 IST on trading days.",
    });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("responds 202 with queued true when a row was inserted", async () => {
    vi.setSystemTime(ist(2026, 11, 9, 16, 0));
    const calls: Array<{ sql: string; values: unknown[] }> = [];
    const query = async (sql: string, values: unknown[]): Promise<QueryResult> => {
      calls.push({ sql, values });
      return { rows: [{ id: values[0] }] };
    };
    const app = buildApp({ query });
    const response = await app.inject({ method: "POST", url: "/api/collector/index-eod/refresh" });
    expect(response.statusCode).toBe(202);
    expect(response.json()).toEqual({ queued: true });
    expect(calls).toHaveLength(1);
    expect(calls[0].sql).toContain("INSERT INTO collector_requests");
    expect(calls[0].values[1]).toBe("index_eod");
    expect(String(calls[0].values[0])).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    await app.close();
  });

  it("responds 200 with queued false when a request is already queued", async () => {
    vi.setSystemTime(ist(2026, 11, 9, 16, 0));
    const query = async (): Promise<QueryResult> => ({ rows: [] });
    const app = buildApp({ query });
    const response = await app.inject({ method: "POST", url: "/api/collector/index-eod/refresh" });
    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({ queued: false, message: "A refresh is already queued." });
    await app.close();
  });

  it("allows a weekend request at any time", async () => {
    vi.setSystemTime(ist(2026, 11, 7, 9, 0));
    const query = async (_sql: string, values: unknown[]): Promise<QueryResult> => ({ rows: [{ id: values[0] }] });
    const app = buildApp({ query });
    const response = await app.inject({ method: "POST", url: "/api/collector/index-eod/refresh" });
    expect(response.statusCode).toBe(202);
    await app.close();
  });

  it("responds 500 with a JSON error when the database call fails", async () => {
    vi.setSystemTime(ist(2026, 11, 9, 16, 0));
    const query = async (): Promise<QueryResult> => {
      throw new Error("connection refused");
    };
    const app = buildApp({ query });
    const response = await app.inject({ method: "POST", url: "/api/collector/index-eod/refresh" });
    expect(response.statusCode).toBe(500);
    expect(response.json()).toEqual({ error: "Could not queue the refresh." });
    await app.close();
  });
});

describe("buildLastIndexEodRunQuery", () => {
  it("reads the latest successful index_eod finish time with a bound source only", () => {
    const query = buildLastIndexEodRunQuery();
    expect(query.values).toEqual(["index_eod"]);
    expect(query.sql).toContain("FROM collector_runs");
    expect(query.sql).toContain("status = 'ok'");
    expect(query.sql).toContain("ORDER BY finished_at DESC LIMIT 1");
    expect(query.sql).not.toMatch(/SELECT \*/);
  });
});

describe("lastRefreshedAtFromRow", () => {
  it("returns an ISO string for a Date or a timestamp string, and null otherwise", () => {
    expect(lastRefreshedAtFromRow(new Date("2026-11-09T10:22:00Z"))).toBe("2026-11-09T10:22:00.000Z");
    expect(lastRefreshedAtFromRow("2026-11-09T10:22:00Z")).toBe("2026-11-09T10:22:00.000Z");
    expect(lastRefreshedAtFromRow(undefined)).toBeNull();
    expect(lastRefreshedAtFromRow("garbage")).toBeNull();
  });
});

describe("GET /api/collector/index-eod/status", () => {
  it("returns the database finish time, last run duration and pickup interval", async () => {
    const { buildApp: build } = await import("./app.js");
    const app = build({
      query: async () => ({ rows: [{ finished_at: new Date("2026-11-09T10:22:00Z"), duration_seconds: "14.19" }] }),
    });
    const response = await app.inject({ method: "GET", url: "/api/collector/index-eod/status" });
    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({
      lastRefreshedAt: "2026-11-09T10:22:00.000Z",
      lastRunSeconds: 14,
      pickupSeconds: 60,
    });
    await app.close();
  });

  it("returns null timestamps and duration when no run has finished yet", async () => {
    const { buildApp: build } = await import("./app.js");
    const app = build({ query: async () => ({ rows: [] }) });
    const response = await app.inject({ method: "GET", url: "/api/collector/index-eod/status" });
    expect(response.json()).toEqual({ lastRefreshedAt: null, lastRunSeconds: null, pickupSeconds: 60 });
    await app.close();
  });

  it("parses the run duration from a numeric string, and rejects negative or missing values", () => {
    expect(lastRunSecondsFromRow("14.19")).toBe(14);
    expect(lastRunSecondsFromRow(9.6)).toBe(10);
    expect(lastRunSecondsFromRow(null)).toBeNull();
    expect(lastRunSecondsFromRow("-3")).toBeNull();
    expect(lastRunSecondsFromRow("abc")).toBeNull();
  });
});
