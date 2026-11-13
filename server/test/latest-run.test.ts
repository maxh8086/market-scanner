import { browserSession } from "../src/sessionTestHelper.js";
import { describe, expect, it } from "vitest";
import { buildApp, type QueryFn } from "../src/app.js";
import { buildLatestRunQuery, formatRunDate } from "../src/results.js";

const RUN_ID = "11111111-2222-3333-4444-555555555555";

function fakeQuery(rows: Array<Record<string, unknown>>): {
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

describe("buildLatestRunQuery", () => {
  it("filters on is_current and keeps LIMIT 1 with no values", () => {
    const { sql, values } = buildLatestRunQuery();
    expect(sql).toContain("is_current = true");
    expect(sql).toContain("FROM runs");
    expect(sql).toMatch(/LIMIT 1$/);
    expect(values).toEqual([]);
  });
});

describe("formatRunDate", () => {
  it("formats a Date using its local calendar date", () => {
    expect(formatRunDate(new Date(2026, 0, 2))).toBe("2026-01-02");
  });

  it("trims a date string to YYYY-MM-DD", () => {
    expect(formatRunDate("2026-01-02")).toBe("2026-01-02");
    expect(formatRunDate("2026-01-02T00:00:00.000Z")).toBe("2026-01-02");
  });

  it("returns null for values that are not dates", () => {
    expect(formatRunDate("not a date")).toBeNull();
    expect(formatRunDate(undefined)).toBeNull();
  });
});

describe("GET /api/runs/latest", () => {
  it("returns 200 with runId and runDate for a current run", async () => {
    const { query, calls } = fakeQuery([{ run_id: RUN_ID, run_date: new Date(2026, 0, 2) }]);
    const app = buildApp({ query });
    const res = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: "/api/runs/latest" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ runId: RUN_ID, runDate: "2026-01-02" });
    expect(calls).toHaveLength(1);
    expect(calls[0].sql).toContain("is_current = true");
    expect(calls[0].values).toEqual([]);
  });

  it("accepts run_date as a string", async () => {
    const { query } = fakeQuery([{ run_id: RUN_ID, run_date: "2026-01-02" }]);
    const app = buildApp({ query });
    const res = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: "/api/runs/latest" });
    expect(res.json()).toEqual({ runId: RUN_ID, runDate: "2026-01-02" });
  });

  it("returns 404 when no current run exists", async () => {
    const { query } = fakeQuery([]);
    const app = buildApp({ query });
    const res = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: "/api/runs/latest" });
    expect(res.statusCode).toBe(404);
    expect(res.json()).toEqual({ error: "No current run" });
  });
});
