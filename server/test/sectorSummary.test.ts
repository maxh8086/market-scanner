import { browserSession } from "../src/sessionTestHelper.js";
import { describe, expect, it } from "vitest";
import { buildApp, type QueryFn } from "../src/app.js";
import {
  buildSectorSummaryQuery,
  shapeSectorSummary,
  validateSectorPeriod,
} from "../src/sectorSummary.js";

const RUN_ID = "11111111-2222-3333-4444-555555555555";

function fakeQuery(sectorRows: Array<Record<string, unknown>>): {
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
    return { rows: sectorRows };
  };
  return { query, calls };
}

describe("validateSectorPeriod", () => {
  it("defaults to 1d when omitted", () => {
    expect(validateSectorPeriod(undefined)).toEqual({ ok: true, value: "1d" });
  });

  it("accepts a whitelisted key", () => {
    expect(validateSectorPeriod("12m")).toEqual({ ok: true, value: "12m" });
  });

  it("rejects an unknown key", () => {
    expect(validateSectorPeriod("2y")).toEqual({ ok: false, error: "Invalid period" });
  });

  it("rejects a non-string value", () => {
    expect(validateSectorPeriod(5)).toEqual({ ok: false, error: "Invalid period" });
  });
});

describe("buildSectorSummaryQuery", () => {
  it("passes the run id and the mapped interval as values", () => {
    const { values } = buildSectorSummaryQuery(RUN_ID, "1w");
    expect(values).toEqual([RUN_ID, "7 days"]);
  });

  it("uses only $1 and $2 placeholders and does not inline the run id", () => {
    const { sql } = buildSectorSummaryQuery(RUN_ID, "1m");
    expect(sql).toContain("$1");
    expect(sql).toContain("$2");
    expect(sql).not.toContain("$3");
    expect(sql).not.toContain(RUN_ID);
  });

  it("reads from candles and symbol_sector", () => {
    const { sql } = buildSectorSummaryQuery(RUN_ID, "1d");
    expect(sql).toContain("symbol_sector");
    expect(sql).toContain("candles");
  });
});

describe("shapeSectorSummary", () => {
  it("coerces string numerics to numbers and rounds the average", () => {
    const shaped = shapeSectorSummary(
      [
        {
          sector: "Banks",
          count: "2",
          avg_change_pct: "1.23456",
          advancers: "1",
          decliners: "1",
        },
      ],
      "1d",
    );
    expect(shaped).toEqual({
      period: "1d",
      sectors: [{ sector: "Banks", count: 2, avgChangePct: 1.23, advancers: 1, decliners: 1 }],
    });
  });

  it("maps a null sector to Unclassified", () => {
    const shaped = shapeSectorSummary(
      [{ sector: null, count: 1, avg_change_pct: 0.5, advancers: 1, decliners: 0 }],
      "1d",
    );
    expect(shaped.sectors[0]?.sector).toBe("Unclassified");
  });

  it("sorts by count descending, then sector ascending", () => {
    const shaped = shapeSectorSummary(
      [
        { sector: "Zeta", count: 2, avg_change_pct: 1, advancers: 2, decliners: 0 },
        { sector: "Beta", count: 5, avg_change_pct: 1, advancers: 5, decliners: 0 },
        { sector: "Alpha", count: 2, avg_change_pct: 1, advancers: 2, decliners: 0 },
      ],
      "3m",
    );
    expect(shaped.sectors.map((s) => s.sector)).toEqual(["Beta", "Alpha", "Zeta"]);
  });

  it("drops rows whose average is not finite", () => {
    const shaped = shapeSectorSummary(
      [
        { sector: "A", count: 1, avg_change_pct: null, advancers: 0, decliners: 0 },
        { sector: "B", count: 1, avg_change_pct: "2", advancers: 1, decliners: 0 },
      ],
      "1d",
    );
    expect(shaped.sectors.map((s) => s.sector)).toEqual(["B"]);
  });

  it("returns an empty sector list for no rows", () => {
    expect(shapeSectorSummary([], "6m")).toEqual({ period: "6m", sectors: [] });
  });
});

describe("GET /api/runs/:runId/sector-summary", () => {
  it("returns 400 for an invalid period without running any query", async () => {
    const { query, calls } = fakeQuery([]);
    const app = buildApp({ query });
    const res = await app.inject({ headers: { cookie: (await browserSession(app)).cookie },
      method: "GET",
      url: `/api/runs/${RUN_ID}/sector-summary?period=2y`,
    });
    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: "Invalid period" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("returns 200 with the sector shape", async () => {
    const { query, calls } = fakeQuery([
      { sector: "Banks", count: "3", avg_change_pct: "1.5", advancers: "2", decliners: "1" },
    ]);
    const app = buildApp({ query });
    const res = await app.inject({ headers: { cookie: (await browserSession(app)).cookie },
      method: "GET",
      url: `/api/runs/${RUN_ID}/sector-summary?period=1w`,
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      period: "1w",
      sectors: [{ sector: "Banks", count: 3, avgChangePct: 1.5, advancers: 2, decliners: 1 }],
    });
    const data = calls.find((c) => c.sql.includes("symbol_sector"));
    expect(data?.values).toEqual([RUN_ID, "7 days"]);
    await app.close();
  });

  it("defaults to 1d when the period is omitted", async () => {
    const { query } = fakeQuery([]);
    const app = buildApp({ query });
    const res = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: `/api/runs/${RUN_ID}/sector-summary` });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ period: "1d", sectors: [] });
    await app.close();
  });

  it("returns empty sectors without a 404 for an unknown run id", async () => {
    const { query, calls } = fakeQuery([
      { sector: "Banks", count: 1, avg_change_pct: 1, advancers: 1, decliners: 0 },
    ]);
    const app = buildApp({ query });
    const res = await app.inject({ headers: { cookie: (await browserSession(app)).cookie },
      method: "GET",
      url: "/api/runs/99999999-9999-9999-9999-999999999999/sector-summary?period=3m",
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ period: "3m", sectors: [] });
    expect(calls.every((c) => c.sql.includes("FROM runs"))).toBe(true);
    await app.close();
  });
});
