/**
 * Pure validation, SQL builder and response shaping for GET /api/recent-closes.
 * It returns the last N daily closes for many symbols in one call, so the scan
 * table can draw a sparkline per row without one candles request per row.
 * No database access here. Every user value is passed as a $N placeholder.
 */

import type { Built, ValidationResult } from "./candles.js";

export const DEFAULT_CLOSES_LIMIT = 30;
export const MIN_CLOSES_LIMIT = 1;
export const MAX_CLOSES_LIMIT = 60;
export const MAX_CLOSES_SYMBOLS = 100;
export const MAX_SYMBOL_LENGTH = 30;

const SYMBOL_RE = /^[A-Z0-9&-]+$/;
const LIMIT_RE = /^\d+$/;

export interface RecentClosesRequest {
  symbols: string[];
  limit: number;
}

export interface RecentClosesResponse {
  /** Closes per symbol, oldest first. Symbols with no stored candles are left out. */
  closes: Record<string, number[]>;
}

export interface RecentClosesRequestParams {
  symbols?: unknown;
  limit?: unknown;
}

/** Splits the comma-separated `symbols` param, validates each symbol and the count, and the limit. */
export function validateRecentClosesRequest(
  params: RecentClosesRequestParams,
): ValidationResult<RecentClosesRequest> {
  if (typeof params.symbols !== "string" || params.symbols.trim() === "") {
    return { ok: false, error: "Invalid symbols" };
  }
  const parts = params.symbols.split(",").map((part) => part.trim().toUpperCase());
  const unique = [...new Set(parts)];
  if (unique.length > MAX_CLOSES_SYMBOLS) {
    return { ok: false, error: `At most ${MAX_CLOSES_SYMBOLS} symbols` };
  }
  for (const symbol of unique) {
    if (symbol.length < 1 || symbol.length > MAX_SYMBOL_LENGTH || !SYMBOL_RE.test(symbol)) {
      return { ok: false, error: "Invalid symbols" };
    }
  }

  const limit = validateLimit(params.limit);
  if (!limit.ok) return limit;

  return { ok: true, value: { symbols: unique, limit: limit.value } };
}

function validateLimit(raw: unknown): ValidationResult<number> {
  if (raw === undefined) return { ok: true, value: DEFAULT_CLOSES_LIMIT };
  let limit: number;
  if (typeof raw === "number") {
    limit = raw;
  } else if (typeof raw === "string" && LIMIT_RE.test(raw)) {
    limit = Number(raw);
  } else {
    return { ok: false, error: "Invalid limit" };
  }
  if (!Number.isInteger(limit) || limit < MIN_CLOSES_LIMIT || limit > MAX_CLOSES_LIMIT) {
    return { ok: false, error: "Invalid limit" };
  }
  return { ok: true, value: limit };
}

/**
 * Ranks each symbol's candles newest first, keeps the top `limit` per symbol, then
 * returns them oldest first. The symbol list and the limit are bound as values.
 */
export function buildRecentClosesQuery(request: RecentClosesRequest): Built {
  const values: unknown[] = [request.symbols, request.limit];
  const sql = `
SELECT symbol, date, close
FROM (
  SELECT symbol, date, close,
         ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
  FROM candles
  WHERE symbol = ANY($1)
) ranked
WHERE rn <= $2
ORDER BY symbol ASC, date ASC`;
  return { sql, values };
}

/** Converts a pg value to a number. Null, undefined and non-numeric values become null. */
function toNumberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

/** Groups rows by symbol. NUMERIC closes may arrive as strings, so they are converted. Null closes are skipped. */
export function shapeRecentCloses(rows: Array<Record<string, unknown>>): RecentClosesResponse {
  const closes: Record<string, number[]> = {};
  for (const row of rows) {
    const symbol = String(row.symbol);
    const close = toNumberOrNull(row.close);
    if (close === null) continue;
    (closes[symbol] ??= []).push(close);
  }
  return { closes };
}
