import { describe, expect, it } from "vitest";
import { buildApp, type QueryFn } from "../src/app.js";
import { buildFilterOptionsQuery, shapeFilterOptions } from "../src/filterOptions.js";

const RUN_ID = "11111111-2222-3333-4444-555555555555";

function fakeQuery(optionRows: Array<Record<string, unknown>>): {
  query: QueryFn;
  calls: Array<{ sql: string; values: unknown[] }>;
} {
  const calls: Array<{ sql: string; values: unknown[] }> = [];
  const query: QueryFn = async (sql, values) => {
    calls.push({ sql, values });
    if (sql.includes("FROM runs")) {
      const known = values[0] === RUN_ID;
      return { rows: known ? [{ run_id: RUN_ID }] : [] };
    }
    return { rows: optionRows };
  };
  return { query, calls };
}

describe("buildFilterOptionsQuery", () => {
  it("uses a $1 placeholder for the run id and does not interpolate it", () => {
    const { sql, values } = buildFilterOptionsQuery(RUN_ID);
    expect(sql).toContain("ss.run_id = $1");
    expect(sql).not.toContain("$2");
    expect(sql).not.toContain(RUN_ID);
    expect(values).toEqual([RUN_ID]);
  });

  it("reads both columns from stock_snapshots with non-empty filters", () => {
    const { sql } = buildFilterOptionsQuery(RUN_ID);
    expect(sql).toContain("FROM stock_snapshots ss");
    expect(sql).toContain("array_agg(DISTINCT ss.bucket ORDER BY ss.bucket)");
    expect(sql).toContain("array_agg(DISTINCT ss.stance ORDER BY ss.stance)");
    expect(sql).toContain("ss.bucket <> ''");
    expect(sql).toContain("ss.stance <> ''");
  });
});

describe("shapeFilterOptions", () => {
  it("returns sorted, deduplicated lists without nulls or empty strings", () => {
    const shaped = shapeFilterOptions([
      {
        bucket: ["B", "A", "B", null, "", "C"],
        stance: ["SELL", "BUY", "BUY"],
      },
    ]);
    expect(shaped).toEqual({ bucket: ["A", "B", "C"], stance: ["BUY", "SELL"] });
  });

  it("returns empty lists when there is no row", () => {
    expect(shapeFilterOptions([])).toEqual({ bucket: [], stance: [] });
  });

  it("returns empty lists when the columns are null", () => {
    expect(shapeFilterOptions([{ bucket: null, stance: null }])).toEqual({
      bucket: [],
      stance: [],
    });
  });
});

describe("GET /api/runs/:runId/filter-options", () => {
  it("returns 200 with the bucket and stance shape", async () => {
    const { query, calls } = fakeQuery([{ bucket: ["A", "B"], stance: ["BUY"] }]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: `/api/runs/${RUN_ID}/filter-options` });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ bucket: ["A", "B"], stance: ["BUY"] });
    expect(calls.some((c) => c.sql.includes("array_agg(DISTINCT ss.bucket"))).toBe(true);
    await app.close();
  });

  it("returns empty lists for a run with no rows", async () => {
    const { query } = fakeQuery([{ bucket: [], stance: [] }]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: `/api/runs/${RUN_ID}/filter-options` });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ bucket: [], stance: [] });
    await app.close();
  });

  it("returns empty lists without a 404 for an unknown run id", async () => {
    const { query, calls } = fakeQuery([{ bucket: ["A"], stance: ["BUY"] }]);
    const app = buildApp({ query });
    const res = await app.inject({
      method: "GET",
      url: "/api/runs/99999999-9999-9999-9999-999999999999/filter-options",
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ bucket: [], stance: [] });
    expect(calls.every((c) => c.sql.includes("FROM runs"))).toBe(true);
    await app.close();
  });

  it("returns empty lists for a malformed run id", async () => {
    const { query } = fakeQuery([]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/api/runs/not-a-run/filter-options" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ bucket: [], stance: [] });
    await app.close();
  });

  it("does not shadow the latest and results routes", async () => {
    const { query } = fakeQuery([{ bucket: ["A"], stance: [] }]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: `/api/runs/${RUN_ID}/results` });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toHaveProperty("results");
    await app.close();
  });
});
