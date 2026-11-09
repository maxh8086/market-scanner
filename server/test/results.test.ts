import { describe, expect, it } from "vitest";
import { buildApp, type QueryFn } from "../src/app.js";
import { buildCountQuery, buildResultsQuery, type ResultsParams } from "../src/results.js";

const RUN_ID = "11111111-2222-3333-4444-555555555555";
const base: ResultsParams = { runId: RUN_ID };

function placeholderCount(sql: string): number {
  const nums = new Set([...sql.matchAll(/\$(\d+)/g)].map((m) => Number(m[1])));
  return nums.size;
}

function fakeQuery(): { query: QueryFn; calls: Array<{ sql: string; values: unknown[] }> } {
  const calls: Array<{ sql: string; values: unknown[] }> = [];
  const query: QueryFn = async (sql, values) => {
    calls.push({ sql, values });
    if (sql.includes("FROM runs")) {
      const known = values[0] === RUN_ID || values[0] === "2026-01-02";
      return { rows: known ? [{ run_id: RUN_ID }] : [] };
    }
    if (sql.includes("COUNT(*)")) {
      return { rows: [{ total: 2 }] };
    }
    return {
      rows: [
        { symbol: "AAA", company: "AAA Ltd", changed: true },
        { symbol: "BBB", company: "BBB Ltd", changed: false },
      ],
    };
  };
  return { query, calls };
}

describe("buildResultsQuery", () => {
  it("falls back to symbol for a sort key outside the whitelist", () => {
    const { sql } = buildResultsQuery({ ...base, sort: "symbol; DROP TABLE runs" });
    expect(sql).toContain("ORDER BY ss.symbol ASC NULLS LAST");
    expect(sql).not.toContain("DROP");
  });

  it("falls back to symbol for prototype keys", () => {
    const { sql } = buildResultsQuery({ ...base, sort: "constructor" });
    expect(sql).toContain("ORDER BY ss.symbol ASC");
  });

  it("uses a whitelisted sort column and direction", () => {
    const { sql } = buildResultsQuery({ ...base, sort: "ltp", order: "desc" });
    expect(sql).toContain("ORDER BY ss.ltp DESC NULLS LAST");
  });

  it("numbers placeholders to match the values array", () => {
    const params: ResultsParams = {
      ...base,
      bucket: "A",
      stance: "BUY",
      search: "tata",
      industry: "auto",
      ltpMin: 1,
      ltpMax: 500,
      distanceMin: -5,
      distanceMax: 5,
      athFrom: "2025-01-01",
      athTo: "2026-01-01",
      page: 2,
      perPage: 10,
    };
    const { sql, values } = buildResultsQuery(params);
    expect(placeholderCount(sql)).toBe(values.length);
    expect(values).toHaveLength(14);
    expect(values[0]).toBe(RUN_ID);
  });

  it("computes offset from page and perPage", () => {
    const { values } = buildResultsQuery({ ...base, page: 3, perPage: 10 });
    expect(values.slice(-2)).toEqual([10, 20]);
  });

  it("clamps perPage to 100 and defaults to 20", () => {
    expect(buildResultsQuery({ ...base, perPage: 500 }).values.slice(-2)).toEqual([100, 0]);
    expect(buildResultsQuery(base).values.slice(-2)).toEqual([20, 0]);
  });

  it("adds filter clauses only when given", () => {
    const bare = buildResultsQuery(base);
    expect(bare.values).toEqual([RUN_ID, 20, 0]);
    expect(bare.sql).not.toContain("ILIKE");
    expect(bare.sql).not.toContain("ss.ltp >=");
    expect(bare.sql).not.toContain("ss.bucket =");

    const withLtpMin = buildResultsQuery({ ...base, ltpMin: 10 });
    expect(withLtpMin.sql).toContain("ss.ltp >= $2");
    expect(withLtpMin.sql).not.toContain("ss.ltp <=");
  });

  it("ignores bucket and stance set to all", () => {
    const { sql } = buildResultsQuery({ ...base, bucket: "all", stance: "all" });
    expect(sql).not.toContain("ss.bucket =");
    expect(sql).not.toContain("ss.stance =");
  });

  it("keeps user search text out of the SQL string", () => {
    const { sql, values } = buildResultsQuery({ ...base, search: "x' OR '1'='1" });
    expect(sql).not.toContain("OR '1'");
    expect(values).toContain("%x' OR '1'='1%");
  });
});

describe("buildCountQuery", () => {
  it("uses the same filters and placeholder numbering as the rows query", () => {
    const params: ResultsParams = { ...base, search: "abc", ltpMax: 90 };
    const count = buildCountQuery(params);
    expect(placeholderCount(count.sql)).toBe(count.values.length);
    expect(count.values).toEqual([RUN_ID, "%abc%", "%abc%", 90]);
  });
});

describe("GET /api/runs/:runId/results", () => {
  it("returns 200 with results, total, page and perPage", async () => {
    const { query, calls } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({
      method: "GET",
      url: `/api/runs/${RUN_ID}/results?page=1&perPage=20&sort=ltp&order=desc`,
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      results: [
        { symbol: "AAA", company: "AAA Ltd", changed: true },
        { symbol: "BBB", company: "BBB Ltd", changed: false },
      ],
      total: 2,
      page: 1,
      perPage: 20,
    });
    expect(calls.some((c) => c.sql.includes("ORDER BY ss.ltp DESC"))).toBe(true);
    await app.close();
  });

  it("resolves a run date to its run id", async () => {
    const { query } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/api/runs/2026-01-02/results" });
    expect(res.statusCode).toBe(200);
    await app.close();
  });

  it("returns 404 for an unknown run", async () => {
    const { query } = fakeQuery();
    const app = buildApp({ query });
    const unknown = await app.inject({
      method: "GET",
      url: "/api/runs/99999999-9999-9999-9999-999999999999/results",
    });
    expect(unknown.statusCode).toBe(404);
    expect(unknown.json()).toEqual({ error: "Run not found" });

    const badId = await app.inject({ method: "GET", url: "/api/runs/not-a-run/results" });
    expect(badId.statusCode).toBe(404);
    await app.close();
  });

  it("returns 400 when perPage is above 100", async () => {
    const { query } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({
      method: "GET",
      url: `/api/runs/${RUN_ID}/results?perPage=500`,
    });
    expect(res.statusCode).toBe(400);
    await app.close();
  });

  it("returns 400 for an impossible ath date", async () => {
    const { query } = fakeQuery();
    const app = buildApp({ query });
    const res = await app.inject({
      method: "GET",
      url: `/api/runs/${RUN_ID}/results?athFrom=2026-02-30`,
    });
    expect(res.statusCode).toBe(400);
    await app.close();
  });

  it("serves the health check", async () => {
    const app = buildApp({ query: fakeQuery().query });
    const res = await app.inject({ method: "GET", url: "/api/health" });
    expect(res.json()).toEqual({ ok: true });
    await app.close();
  });
});
