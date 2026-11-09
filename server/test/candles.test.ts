import { describe, expect, it } from "vitest";
import { buildApp, type QueryFn } from "../src/app.js";
import {
  buildCandlesQuery,
  shapeCandles,
  validateCandlesRequest,
} from "../src/candles.js";

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

describe("validateCandlesRequest", () => {
  it("accepts a good symbol with no optional params and applies the default limit", () => {
    const checked = validateCandlesRequest({ symbol: "RELIANCE" });
    expect(checked).toEqual({ ok: true, value: { symbol: "RELIANCE", limit: 500 } });
  });

  it("uppercases the symbol and accepts & and - and digits", () => {
    const checked = validateCandlesRequest({ symbol: "m&m-2" });
    expect(checked.ok && checked.value.symbol).toBe("M&M-2");
  });

  it("accepts a full valid range and limit", () => {
    const checked = validateCandlesRequest({
      symbol: "TCS",
      from: "2024-01-01",
      to: "2024-12-31",
      limit: "1500",
    });
    expect(checked).toEqual({
      ok: true,
      value: { symbol: "TCS", from: "2024-01-01", to: "2024-12-31", limit: 1500 },
    });
  });

  it("rejects a symbol with other characters", () => {
    expect(validateCandlesRequest({ symbol: "BRK.B" })).toEqual({
      ok: false,
      error: "Invalid symbol",
    });
  });

  it("rejects an empty symbol and a symbol over 30 characters", () => {
    expect(validateCandlesRequest({ symbol: "" }).ok).toBe(false);
    expect(validateCandlesRequest({ symbol: "A".repeat(31) }).ok).toBe(false);
    expect(validateCandlesRequest({ symbol: "A".repeat(30) }).ok).toBe(true);
  });

  it("rejects a bad date", () => {
    expect(validateCandlesRequest({ symbol: "TCS", from: "2024-02-30" })).toEqual({
      ok: false,
      error: "Invalid from",
    });
    expect(validateCandlesRequest({ symbol: "TCS", to: "01-02-2024" })).toEqual({
      ok: false,
      error: "Invalid to",
    });
  });

  it("rejects from later than to", () => {
    const checked = validateCandlesRequest({ symbol: "TCS", from: "2024-06-01", to: "2024-05-31" });
    expect(checked.ok).toBe(false);
  });

  it("rejects limit 0, limit 1501 and non-integer limits", () => {
    expect(validateCandlesRequest({ symbol: "TCS", limit: "0" }).ok).toBe(false);
    expect(validateCandlesRequest({ symbol: "TCS", limit: "1501" }).ok).toBe(false);
    expect(validateCandlesRequest({ symbol: "TCS", limit: "1.5" }).ok).toBe(false);
    expect(validateCandlesRequest({ symbol: "TCS", limit: "abc" }).ok).toBe(false);
    expect(validateCandlesRequest({ symbol: "TCS", limit: 2.5 }).ok).toBe(false);
  });
});

describe("buildCandlesQuery", () => {
  it("uses placeholders and never interpolates the symbol", () => {
    const { sql, values } = buildCandlesQuery({
      symbol: "RELIANCE",
      from: "2024-01-01",
      to: "2024-02-01",
      limit: 10,
    });
    expect(sql).toContain("symbol = $1");
    expect(sql).toContain("date >= $2");
    expect(sql).toContain("date <= $3");
    expect(sql).toContain("LIMIT $4");
    expect(sql).not.toContain("RELIANCE");
    expect(sql).not.toContain("2024-01-01");
    expect(values).toEqual(["RELIANCE", "2024-01-01", "2024-02-01", 10]);
  });

  it("omits date clauses when no range is given and sorts the outer query ascending", () => {
    const { sql, values } = buildCandlesQuery({ symbol: "TCS", limit: 500 });
    expect(sql).not.toContain("date >= ");
    expect(sql).not.toContain("date <= ");
    expect(sql).toContain("ORDER BY date DESC");
    expect(sql).toMatch(/ORDER BY date ASC$/);
    expect(values).toEqual(["TCS", 500]);
  });
});

describe("shapeCandles", () => {
  it("converts numeric strings to numbers and maps null values to null", () => {
    const shaped = shapeCandles("TCS", [
      {
        symbol: "TCS",
        date: "2024-01-02",
        open: "100.5",
        high: "101",
        low: null,
        close: "100.75",
        volume: "123456",
      },
    ]);
    expect(shaped).toEqual({
      symbol: "TCS",
      candles: [
        {
          date: "2024-01-02",
          open: 100.5,
          high: 101,
          low: null,
          close: 100.75,
          volume: 123456,
        },
      ],
    });
  });

  it("formats Date values as YYYY-MM-DD and sorts candles ascending", () => {
    const shaped = shapeCandles("TCS", [
      { symbol: "TCS", date: "2024-01-03", open: 1, high: 1, low: 1, close: 1, volume: 1 },
      { symbol: "TCS", date: "2024-01-02", open: 1, high: 1, low: 1, close: 1, volume: 1 },
    ]);
    expect(shaped.candles.map((c) => c.date)).toEqual(["2024-01-02", "2024-01-03"]);
  });

  it("returns an empty candles array for no rows", () => {
    expect(shapeCandles("NOPE", [])).toEqual({ symbol: "NOPE", candles: [] });
  });
});

describe("GET /api/stocks/:symbol/candles", () => {
  it("returns 200 with the candle shape", async () => {
    const { query } = fakeQuery([
      { symbol: "TCS", date: "2024-01-02", open: "1.5", high: "2", low: "1", close: "1.9", volume: "10" },
    ]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/api/stocks/tcs/candles" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      symbol: "TCS",
      candles: [{ date: "2024-01-02", open: 1.5, high: 2, low: 1, close: 1.9, volume: 10 }],
    });
    await app.close();
  });

  it("passes the symbol and limit to the query as values", async () => {
    const { query, calls } = fakeQuery([]);
    const app = buildApp({ query });
    await app.inject({ method: "GET", url: "/api/stocks/TCS/candles?limit=20" });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.values).toEqual(["TCS", 20]);
    expect(calls[0]?.sql).not.toContain("TCS");
    await app.close();
  });

  it("returns 400 for a bad symbol without querying", async () => {
    const { query, calls } = fakeQuery([]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/api/stocks/BAD%24SYM/candles" });
    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: "Invalid symbol" });
    expect(calls).toHaveLength(0);
    await app.close();
  });

  it("returns 400 for a bad date, from after to, and a bad limit", async () => {
    const { query } = fakeQuery([]);
    const app = buildApp({ query });
    const badDate = await app.inject({ method: "GET", url: "/api/stocks/TCS/candles?from=2024-13-01" });
    expect(badDate.statusCode).toBe(400);
    expect(badDate.json()).toHaveProperty("error");

    const reversed = await app.inject({
      method: "GET",
      url: "/api/stocks/TCS/candles?from=2024-06-01&to=2024-05-01",
    });
    expect(reversed.statusCode).toBe(400);

    const badLimit = await app.inject({ method: "GET", url: "/api/stocks/TCS/candles?limit=1501" });
    expect(badLimit.statusCode).toBe(400);
    expect(badLimit.json()).toHaveProperty("error");
    await app.close();
  });

  it("returns 200 with an empty candles array for an unknown symbol", async () => {
    const { query } = fakeQuery([]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/api/stocks/UNKNOWN/candles" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ symbol: "UNKNOWN", candles: [] });
    await app.close();
  });
});
