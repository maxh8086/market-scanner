import { describe, expect, it } from "vitest";
import { buildApp, type QueryFn } from "../src/app.js";
import {
  buildRecentClosesQuery,
  shapeRecentCloses,
  validateRecentClosesRequest,
} from "../src/recentCloses.js";

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

describe("validateRecentClosesRequest", () => {
  it("splits, uppercases and de-duplicates symbols and applies the default limit", () => {
    const checked = validateRecentClosesRequest({ symbols: "tcs, reliance,TCS" });
    expect(checked).toEqual({ ok: true, value: { symbols: ["TCS", "RELIANCE"], limit: 30 } });
  });

  it("accepts & and - and digits in symbols and a numeric limit", () => {
    const checked = validateRecentClosesRequest({ symbols: "m&m-2", limit: "60" });
    expect(checked).toEqual({ ok: true, value: { symbols: ["M&M-2"], limit: 60 } });
  });

  it("rejects a missing or blank symbols param", () => {
    expect(validateRecentClosesRequest({})).toEqual({ ok: false, error: "Invalid symbols" });
    expect(validateRecentClosesRequest({ symbols: "  " })).toEqual({ ok: false, error: "Invalid symbols" });
  });

  it("rejects a symbol with other characters or an empty entry", () => {
    expect(validateRecentClosesRequest({ symbols: "TCS,BAD SYM" }).ok).toBe(false);
    expect(validateRecentClosesRequest({ symbols: "TCS,,RELIANCE" }).ok).toBe(false);
  });

  it("rejects more than 100 symbols", () => {
    const many = Array.from({ length: 101 }, (_, i) => `S${i}`).join(",");
    expect(validateRecentClosesRequest({ symbols: many })).toEqual({
      ok: false,
      error: "At most 100 symbols",
    });
  });

  it("rejects limit 0, limit 61 and non-integer limits", () => {
    for (const limit of ["0", "61", "2.5", "abc"]) {
      expect(validateRecentClosesRequest({ symbols: "TCS", limit })).toEqual({
        ok: false,
        error: "Invalid limit",
      });
    }
  });
});

describe("buildRecentClosesQuery", () => {
  it("binds the symbol list and limit as values and never interpolates them", () => {
    const built = buildRecentClosesQuery({ symbols: ["TCS", "RELIANCE"], limit: 30 });
    expect(built.values).toEqual([["TCS", "RELIANCE"], 30]);
    expect(built.sql).toContain("symbol = ANY($1)");
    expect(built.sql).toContain("rn <= $2");
    expect(built.sql).not.toContain("TCS");
  });

  it("ranks newest first per symbol and returns the rows oldest first", () => {
    const { sql } = buildRecentClosesQuery({ symbols: ["TCS"], limit: 5 });
    expect(sql).toContain("ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC)");
    expect(sql).toContain("ORDER BY symbol ASC, date ASC");
  });
});

describe("shapeRecentCloses", () => {
  it("groups closes by symbol in order and converts numeric strings", () => {
    const shaped = shapeRecentCloses([
      { symbol: "RELIANCE", date: "2024-01-02", close: "2950.5" },
      { symbol: "TCS", date: "2024-01-02", close: 3800 },
      { symbol: "TCS", date: "2024-01-03", close: "3810" },
    ]);
    expect(shaped).toEqual({
      closes: { RELIANCE: [2950.5], TCS: [3800, 3810] },
    });
  });

  it("skips null closes and returns an empty map for no rows", () => {
    expect(shapeRecentCloses([{ symbol: "TCS", date: "2024-01-02", close: null }])).toEqual({ closes: {} });
    expect(shapeRecentCloses([])).toEqual({ closes: {} });
  });
});

describe("GET /api/recent-closes", () => {
  it("returns 200 with the closes map", async () => {
    const { query } = fakeQuery([{ symbol: "TCS", date: "2024-01-02", close: "1.9" }]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/api/recent-closes?symbols=tcs" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ closes: { TCS: [1.9] } });
    await app.close();
  });

  it("passes the symbol list and limit to the query as values", async () => {
    const { query, calls } = fakeQuery([]);
    const app = buildApp({ query });
    await app.inject({ method: "GET", url: "/api/recent-closes?symbols=TCS,RELIANCE&limit=20" });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.values).toEqual([["TCS", "RELIANCE"], 20]);
    await app.close();
  });

  it("returns 400 for a bad symbol or limit without querying", async () => {
    const { query, calls } = fakeQuery([]);
    const app = buildApp({ query });
    const bad = await app.inject({ method: "GET", url: "/api/recent-closes?symbols=BAD%20SYM" });
    const badLimit = await app.inject({ method: "GET", url: "/api/recent-closes?symbols=TCS&limit=999" });
    expect(bad.statusCode).toBe(400);
    expect(badLimit.statusCode).toBe(400);
    expect(calls).toHaveLength(0);
    await app.close();
  });
});
