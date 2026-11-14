import { describe, expect, it } from "vitest";
import { buildEventsSql, buildLatestFetchedSql, mapEventRow, parseEventsQuery, toIsoOrNull } from "./eventsRead.js";

function parsed(raw: Record<string, unknown>) {
  const result = parseEventsQuery(raw);
  if (!result.ok) throw new Error(`expected a valid query for ${JSON.stringify(raw)}`);
  return result.value;
}

describe("parseEventsQuery defaults", () => {
  it("uses 7 days, both tiers, 100 rows and no symbol when nothing is given", () => {
    expect(parseEventsQuery({})).toEqual({
      ok: true,
      value: { days: 7, tier: undefined, limit: 100, symbol: undefined },
    });
  });

  it("ignores unknown params", () => {
    expect(parsed({ foo: "x", days: "3" }).days).toBe(3);
  });
});

describe("parseEventsQuery bounds", () => {
  it.each([
    ["days", "0"],
    ["days", "31"],
    ["days", "1.5"],
    ["days", "abc"],
    ["limit", "0"],
    ["limit", "201"],
    ["limit", "2.5"],
    ["tier", "other"],
    ["symbol", "bad sym"],
    ["symbol", "A".repeat(21)],
  ])("rejects %s=%s", (key, value) => {
    expect(parseEventsQuery({ [key]: value })).toEqual({ ok: false });
  });

  it("accepts the edges of the integer ranges", () => {
    expect(parsed({ days: "1" }).days).toBe(1);
    expect(parsed({ days: "30" }).days).toBe(30);
    expect(parsed({ limit: "1" }).limit).toBe(1);
    expect(parsed({ limit: "200" }).limit).toBe(200);
  });

  it("accepts both tiers", () => {
    expect(parsed({ tier: "high_priority" }).tier).toBe("high_priority");
    expect(parsed({ tier: "catalyst" }).tier).toBe("catalyst");
  });

  it("accepts a lowercase symbol and upper-cases it", () => {
    expect(parsed({ symbol: "abc" }).symbol).toBe("ABC");
    expect(parsed({ symbol: "a&b-1" }).symbol).toBe("A&B-1");
  });

  it("accepts a 20-character symbol", () => {
    expect(parsed({ symbol: "A".repeat(20) }).symbol).toBe("A".repeat(20));
  });
});

describe("parseEventsQuery arrays and empty strings", () => {
  it("rejects an array for any param", () => {
    expect(parseEventsQuery({ days: ["7"] })).toEqual({ ok: false });
    expect(parseEventsQuery({ symbol: ["ABC"] })).toEqual({ ok: false });
    expect(parseEventsQuery({ tier: ["catalyst"] })).toEqual({ ok: false });
  });

  it("rejects an empty string for an optional param", () => {
    expect(parseEventsQuery({ days: "" })).toEqual({ ok: false });
    expect(parseEventsQuery({ limit: "" })).toEqual({ ok: false });
    expect(parseEventsQuery({ tier: "" })).toEqual({ ok: false });
    expect(parseEventsQuery({ symbol: "" })).toEqual({ ok: false });
  });

  it("rejects a non-string value", () => {
    expect(parseEventsQuery({ days: 7 })).toEqual({ ok: false });
  });
});

describe("buildEventsSql", () => {
  it("binds only $1 to $4 and never puts a user value in the text", () => {
    const built = buildEventsSql(parsed({ symbol: "A&B", tier: "catalyst", days: "5", limit: "9" }));
    expect(built.sql).toContain("$1");
    expect(built.sql).toContain("$4");
    expect(built.sql).not.toContain("$5");
    expect(built.sql).not.toContain("A&B");
    expect(built.sql).not.toContain("catalyst");
    expect(built.sql).not.toContain("'5'");
  });

  it("passes values in the order days, tier, symbol, limit", () => {
    expect(buildEventsSql(parsed({ symbol: "A&B", tier: "catalyst", days: "5", limit: "9" })).values).toEqual([
      5,
      "catalyst",
      "A&B",
      9,
    ]);
  });

  it("passes null for an absent tier and symbol", () => {
    expect(buildEventsSql(parsed({})).values).toEqual([7, null, null, 100]);
  });

  it("guards the 3-per-stock cap with the symbol parameter", () => {
    expect(buildEventsSql(parsed({})).sql).toContain("WHERE ($3::text IS NOT NULL OR rn <= 3)");
  });
});

describe("buildLatestFetchedSql", () => {
  it("takes the newest fetched_at in the window as its only parameter", () => {
    const built = buildLatestFetchedSql(7);
    expect(built.sql).toContain("max(fetched_at)");
    expect(built.sql).toContain("make_interval(days => $1)");
    expect(built.values).toEqual([7]);
  });
});

describe("toIsoOrNull and mapEventRow", () => {
  it("reads a Date and a string as the same IST instant", () => {
    expect(toIsoOrNull(new Date("2026-11-14T12:30:00Z"))).toBe("2026-11-14T18:00:00.000+05:30");
    expect(toIsoOrNull("2026-11-14T12:30:00Z")).toBe("2026-11-14T18:00:00.000+05:30");
  });

  it("returns null for null, an unreadable string or an invalid Date", () => {
    expect(toIsoOrNull(null)).toBeNull();
    expect(toIsoOrNull("not a date")).toBeNull();
    expect(toIsoOrNull(new Date("nope"))).toBeNull();
  });

  it("maps a row to the response fields", () => {
    const item = mapEventRow({
      dedupe_key: "nse:Financial_Results:1",
      symbol: "ABC",
      isin: "INE000A01010",
      company: "ABC Ltd",
      event_type: "results",
      feed_tier: "high_priority",
      feed_code: "Sast_Regulation31",
      headline: "Quarterly results",
      published_at: new Date("2026-11-14T12:30:00Z"),
      fetched_at: "2026-11-14T12:35:02Z",
      source_url: "https://www.nseindia.com/x",
      extra_column: "ignored",
    });
    expect(item).toEqual({
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
      source_url: "https://www.nseindia.com/x",
    });
  });
});
