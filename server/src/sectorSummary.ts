/**
 * Pure SQL builder and response shaper for the run sector-summary endpoint.
 * No database access here. The period key is mapped to a fixed interval text
 * in code; user input never reaches the SQL text.
 */

import type { Built } from "./results.js";

/** Whitelist of period keys to Postgres interval text. */
export const SECTOR_PERIODS: Readonly<Record<string, string>> = {
  "1d": "1 day",
  "1w": "7 days",
  "1m": "1 month",
  "3m": "3 months",
  "6m": "6 months",
  "12m": "12 months",
};

const DEFAULT_PERIOD = "1d";
const UNCLASSIFIED = "Unclassified";

export interface SectorSummaryRow {
  sector: string;
  count: number;
  avgChangePct: number;
  advancers: number;
  decliners: number;
}

export interface SectorSummary {
  period: string;
  sectors: SectorSummaryRow[];
}

function hasPeriod(key: string): boolean {
  return Object.prototype.hasOwnProperty.call(SECTOR_PERIODS, key);
}

/**
 * Accepts an undefined value (defaults to "1d") or one of the SECTOR_PERIODS
 * keys. Anything else, including non-string values, is rejected.
 */
export function validateSectorPeriod(
  value: unknown,
): { ok: true; value: string } | { ok: false; error: string } {
  if (value === undefined) return { ok: true, value: DEFAULT_PERIOD };
  if (typeof value === "string" && hasPeriod(value)) return { ok: true, value };
  return { ok: false, error: "Invalid period" };
}

/**
 * One statement returning one row per sector with count, avgChangePct,
 * advancers and decliners. Placeholders: $1 = run id, $2 = interval text.
 *
 * Per symbol: latest close is the candle with the greatest date. The base is
 * the close of the latest candle dated on or before (latest date - interval).
 * Symbols without a base, or with a zero base, are excluded.
 */
export function buildSectorSummaryQuery(runId: string, period: string): Built {
  if (!hasPeriod(period)) {
    throw new Error("Invalid sector period");
  }
  const interval = SECTOR_PERIODS[period] as string;

  const sql = `
WITH run_symbols AS (
  SELECT DISTINCT ss.symbol
    FROM stock_snapshots ss
   WHERE ss.run_id = $1
),
latest AS (
  SELECT DISTINCT ON (c.symbol) c.symbol, c.date, c.close
    FROM candles c
    JOIN run_symbols rs ON rs.symbol = c.symbol
   ORDER BY c.symbol, c.date DESC
),
base AS (
  SELECT l.symbol, l.close AS latest_close, b.close AS base_close
    FROM latest l
    CROSS JOIN LATERAL (
      SELECT c.close
        FROM candles c
       WHERE c.symbol = l.symbol
         AND c.date <= l.date - $2::interval
       ORDER BY c.date DESC
       LIMIT 1
    ) b
),
changes AS (
  SELECT b.symbol,
         (b.latest_close - b.base_close) / NULLIF(b.base_close, 0) * 100 AS pct
    FROM base b
)
SELECT COALESCE(NULLIF(sec.nse_industry, ''), 'Unclassified') AS sector,
       COUNT(*) AS count,
       AVG(ch.pct) AS avg_change_pct,
       COUNT(*) FILTER (WHERE ch.pct > 0) AS advancers,
       COUNT(*) FILTER (WHERE ch.pct < 0) AS decliners
  FROM changes ch
  LEFT JOIN symbol_sector sec ON sec.symbol = ch.symbol
 WHERE ch.pct IS NOT NULL
 GROUP BY 1`;

  return { sql, values: [runId, interval] };
}

/** Converts a pg numeric value (number or string) to a number, NaN when absent. */
function toNumber(value: unknown): number {
  if (value === null || value === undefined || value === "") return Number.NaN;
  return Number(value);
}

function compareSectors(a: SectorSummaryRow, b: SectorSummaryRow): number {
  if (a.count !== b.count) return b.count - a.count;
  if (a.sector < b.sector) return -1;
  if (a.sector > b.sector) return 1;
  return 0;
}

/**
 * Converts the rows from buildSectorSummaryQuery into the response shape.
 * Numeric strings are coerced, NULL or empty sectors become 'Unclassified',
 * rows with a non-finite average are dropped, and the average is rounded to
 * two decimal places. Sectors are sorted by count descending, then name.
 */
export function shapeSectorSummary(
  rows: Array<Record<string, unknown>>,
  period: string,
): SectorSummary {
  const sectors: SectorSummaryRow[] = [];
  for (const row of rows) {
    const avg = toNumber(row.avg_change_pct);
    if (!Number.isFinite(avg)) continue;
    const rawSector = row.sector;
    const sector =
      rawSector === null || rawSector === undefined || rawSector === ""
        ? UNCLASSIFIED
        : String(rawSector);
    sectors.push({
      sector,
      count: toNumber(row.count),
      avgChangePct: Math.round(avg * 100) / 100,
      advancers: toNumber(row.advancers),
      decliners: toNumber(row.decliners),
    });
  }
  sectors.sort(compareSectors);
  return { period, sectors };
}
