import { browserSession } from "./sessionTestHelper.js";
import { describe, expect, it } from "vitest";
import { buildApp } from "./app.js";
import { buildIndexEodQuery, INDEX_EOD_SQL, shapeIndexEod } from "./indexEod.js";

describe("index EOD query", () => {
  it("reads only IDX rows from the last two weeks, with no user values and no SELECT *", () => {
    const query = buildIndexEodQuery();
    expect(query.values).toEqual([]);
    expect(query.sql).toBe(INDEX_EOD_SQL);
    expect(query.sql).toContain("symbol LIKE 'IDX:%'");
    expect(query.sql).toContain("CURRENT_DATE - 14");
    expect(query.sql).not.toMatch(/SELECT \*/);
  });
});

describe("shapeIndexEod", () => {
  it("returns an empty list when there are no rows", () => {
    expect(shapeIndexEod([])).toEqual({ indices: [] });
  });

  it("maps latest bar (open, high, low, close) and previous close per index, stripping the IDX: prefix", () => {
    const rows = [
      { symbol: "IDX:NIFTY 50", date: "2026-11-06", open: "25010", high: "25150", low: "24990", close: "25100.5", rn: "1" },
      { symbol: "IDX:NIFTY 50", date: "2026-11-05", open: "24900", high: "25020", low: "24880", close: "25000", rn: "2" },
      { symbol: "IDX:NIFTY BANK", date: "2026-11-06", open: 56100, high: 56300, low: 55900, close: 56000, rn: "1" },
    ];
    expect(shapeIndexEod(rows)).toEqual({
      indices: [
        { name: "NIFTY 50", date: "2026-11-06", open: 25010, high: 25150, low: 24990, close: 25100.5, prevClose: 25000 },
        { name: "NIFTY BANK", date: "2026-11-06", open: 56100, high: 56300, low: 55900, close: 56000, prevClose: null },
      ],
    });
  });

  it("returns null for a missing or non-numeric close", () => {
    const rows = [{ symbol: "IDX:SENSEX", date: "2026-11-06", open: null, high: null, low: null, close: null, rn: "1" }];
    expect(shapeIndexEod(rows).indices[0]).toEqual({
      name: "SENSEX", date: "2026-11-06", open: null, high: null, low: null, close: null, prevClose: null,
    });
  });
});

describe("GET /api/index-eod", () => {
  it("responds 200 with the shaped indices", async () => {
    const query = async () => ({
      rows: [{ symbol: "IDX:NIFTY 50", date: "2026-11-06", open: "25010", high: "25150", low: "24990", close: "25100", rn: "1" }],
    });
    const app = buildApp({ query });
    const response = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: "/api/index-eod" });
    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({
      indices: [{ name: "NIFTY 50", date: "2026-11-06", open: 25010, high: 25150, low: 24990, close: 25100, prevClose: null }],
    });
    await app.close();
  });
});
