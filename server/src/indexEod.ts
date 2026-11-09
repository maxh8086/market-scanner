/**
 * Query builder and response shaping for GET /api/index-eod: the last two stored daily closes
 * for each benchmark index (candles rows under IDX:<NAME>, written by the index_eod source).
 * No database access here. The query takes no user input.
 */

import { formatRunDate } from "./results.js";

export interface Built {
  sql: string;
  values: unknown[];
}

export const IDX_PREFIX = "IDX:";

/** Latest two daily bars per index symbol, newest first (rn = 1 is the latest bar). */
export const INDEX_EOD_SQL = `WITH ranked AS (
  SELECT symbol, date, open, high, low, close,
         row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
  FROM candles
  WHERE symbol LIKE 'IDX:%' AND date >= CURRENT_DATE - 14
)
SELECT symbol, date, open, high, low, close, rn FROM ranked WHERE rn <= 2 ORDER BY symbol, rn`;

export interface IndexEod {
  name: string;
  date: string | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  prevClose: number | null;
}

export interface IndexEodResponse {
  indices: IndexEod[];
}

export function buildIndexEodQuery(): Built {
  return { sql: INDEX_EOD_SQL, values: [] };
}

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Turns the query rows into one entry per index, without the IDX: prefix. */
export function shapeIndexEod(rows: ReadonlyArray<Record<string, unknown>>): IndexEodResponse {
  const byName = new Map<string, IndexEod>();
  for (const row of rows) {
    const symbol = String(row.symbol ?? "");
    const name = symbol.startsWith(IDX_PREFIX) ? symbol.slice(IDX_PREFIX.length) : symbol;
    const rank = Number(row.rn);
    const close = toNumber(row.close);
    if (rank === 1) {
      byName.set(name, {
        name,
        date: formatRunDate(row.date),
        open: toNumber(row.open),
        high: toNumber(row.high),
        low: toNumber(row.low),
        close,
        prevClose: null,
      });
    } else if (rank === 2) {
      const entry = byName.get(name);
      if (entry) entry.prevClose = close;
    }
  }
  return { indices: [...byName.values()] };
}
