import { describe, expect, it } from "vitest";
import { buildInsert, MAX_BATCH_ROWS, validateBatch, type HomeEventRow } from "./homeEventsBatch.js";

function validRow(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    dedupe_key: "nse:Financial_Results:123",
    exchange: "NSE",
    feed_code: "nse:Financial_Results",
    source_id: "123",
    source_url: "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
    isin: "INE000000001",
    symbol: "ABC",
    company: "ABC Ltd",
    event_type: "results",
    feed_tier: "high_priority",
    headline: "Quarterly results for the period",
    published_at: "2026-11-09T16:30:00+05:30",
    ...overrides,
  };
}

describe("validateBatch", () => {
  it("valid_row_accepted", () => {
    const result = validateBatch({ rows: [validRow()] });
    expect(result.invalid).toBe(0);
    expect(result.rows).toHaveLength(1);
    expect(result.rows[0].dedupe_key).toBe("nse:Financial_Results:123");
    expect(result.rows[0].published_at).toBe("2026-11-09T16:30:00+05:30");
  });

  it("bad_enum_rejected_and_counted", () => {
    const result = validateBatch({
      rows: [validRow({ event_type: "dividend" }), validRow({ feed_tier: "low" }), validRow()],
    });
    expect(result.invalid).toBe(2);
    expect(result.rows).toHaveLength(1);
  });

  it("bad_date_rejected_and_counted", () => {
    const result = validateBatch({
      rows: [
        validRow({ published_at: "2026-11-09T16:30:00" }),
        validRow({ published_at: "not-a-date" }),
        validRow({ published_at: "2026-11-09T16:30:00+05:30" }),
      ],
    });
    expect(result.invalid).toBe(2);
    expect(result.rows).toHaveLength(1);
  });

  it("non_http_url_rejected", () => {
    const result = validateBatch({
      rows: [
        validRow({ source_url: "javascript:alert(1)" }),
        validRow({ source_url: "ftp://example.com/file.xml" }),
        validRow({ source_url: "not a url" }),
        validRow({ source_url: "http://example.com/ok" }),
      ],
    });
    expect(result.invalid).toBe(3);
    expect(result.rows).toHaveLength(1);
  });

  it("headline_too_long_rejected", () => {
    const result = validateBatch({
      rows: [validRow({ headline: "x".repeat(501) }), validRow({ headline: "x".repeat(500) })],
    });
    expect(result.invalid).toBe(1);
    expect(result.rows).toHaveLength(1);
  });
});

describe("buildInsert", () => {
  const rows: HomeEventRow[] = validateBatch({ rows: [validRow()] }).rows;

  it("sql_uses_on_conflict_do_nothing", () => {
    const built = buildInsert(rows);
    expect(built.text).toContain("INSERT INTO home_events");
    expect(built.text).toContain("ON CONFLICT (dedupe_key) DO NOTHING");
    // Row values are bound parameters, never interpolated into the SQL text.
    expect(built.text).not.toContain("ABC Ltd");
    expect(built.text).toContain("$1");
    expect(built.values).toHaveLength(12);
    expect(built.values[0]).toBe("nse:Financial_Results:123");
  });

  it("over_500_rows_rejected", () => {
    const many: HomeEventRow[] = Array.from({ length: MAX_BATCH_ROWS + 1 }, (_, i) => ({
      ...rows[0],
      dedupe_key: `key-${i}`,
    }));
    expect(() => buildInsert(many)).toThrow(RangeError);
    expect(() => buildInsert(many.slice(0, MAX_BATCH_ROWS))).not.toThrow();
  });
});
