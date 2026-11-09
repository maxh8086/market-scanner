/**
 * Pure validation, SQL builder and response shaping for the daily candles
 * endpoint. No database access here. Every user value is passed as a $N
 * placeholder.
 */

import { formatRunDate, isIsoDate } from "./results.js";

export interface Built {
  sql: string;
  values: unknown[];
}

export type ValidationResult<T> = { ok: true; value: T } | { ok: false; error: string };

export interface CandlesRequestParams {
  symbol: string;
  from?: unknown;
  to?: unknown;
  limit?: unknown;
}

export interface CandlesRequest {
  symbol: string;
  from?: string;
  to?: string;
  limit: number;
}

export interface Candle {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
}

export interface CandlesResponse {
  symbol: string;
  candles: Candle[];
}

export const DEFAULT_LIMIT = 500;
export const MIN_LIMIT = 1;
export const MAX_LIMIT = 1500;
export const MAX_SYMBOL_LENGTH = 30;

const SYMBOL_RE = /^[A-Z0-9&-]+$/;
const LIMIT_RE = /^\d+$/;

function validateSymbol(raw: string): ValidationResult<string> {
  const symbol = raw.toUpperCase();
  if (symbol.length < 1 || symbol.length > MAX_SYMBOL_LENGTH || !SYMBOL_RE.test(symbol)) {
    return { ok: false, error: "Invalid symbol" };
  }
  return { ok: true, value: symbol };
}

function validateDate(raw: unknown, name: "from" | "to"): ValidationResult<string | undefined> {
  if (raw === undefined) return { ok: true, value: undefined };
  if (typeof raw !== "string" || !isIsoDate(raw)) {
    return { ok: false, error: `Invalid ${name}` };
  }
  return { ok: true, value: raw };
}

function validateLimit(raw: unknown): ValidationResult<number> {
  if (raw === undefined) return { ok: true, value: DEFAULT_LIMIT };
  let limit: number;
  if (typeof raw === "number") {
    limit = raw;
  } else if (typeof raw === "string" && LIMIT_RE.test(raw)) {
    limit = Number(raw);
  } else {
    return { ok: false, error: "Invalid limit" };
  }
  if (!Number.isInteger(limit) || limit < MIN_LIMIT || limit > MAX_LIMIT) {
    return { ok: false, error: "Invalid limit" };
  }
  return { ok: true, value: limit };
}

/** Checks the symbol path param and the optional from, to and limit query params. */
export function validateCandlesRequest(
  params: CandlesRequestParams,
): ValidationResult<CandlesRequest> {
  const symbol = validateSymbol(typeof params.symbol === "string" ? params.symbol : "");
  if (!symbol.ok) return symbol;

  const from = validateDate(params.from, "from");
  if (!from.ok) return from;
  const to = validateDate(params.to, "to");
  if (!to.ok) return to;

  if (from.value !== undefined && to.value !== undefined && from.value > to.value) {
    return { ok: false, error: "from must not be after to" };
  }

  const limit = validateLimit(params.limit);
  if (!limit.ok) return limit;

  const value: CandlesRequest = { symbol: symbol.value, limit: limit.value };
  if (from.value !== undefined) value.from = from.value;
  if (to.value !== undefined) value.to = to.value;
  return { ok: true, value };
}

/**
 * Returns the most recent `limit` candles inside the range. The inner query
 * picks the newest rows, and the outer query puts them back in ascending order.
 */
export function buildCandlesQuery(request: CandlesRequest): Built {
  const values: unknown[] = [];
  const ph = (value: unknown): string => {
    values.push(value);
    return `$${values.length}`;
  };

  const clauses: string[] = [`symbol = ${ph(request.symbol)}`];
  if (request.from !== undefined) clauses.push(`date >= ${ph(request.from)}`);
  if (request.to !== undefined) clauses.push(`date <= ${ph(request.to)}`);
  const limitPlaceholder = ph(request.limit);

  const sql = `
SELECT symbol, date, open, high, low, close, volume
FROM (
  SELECT symbol, date, open, high, low, close, volume
  FROM candles
  WHERE ${clauses.join(" AND ")}
  ORDER BY date DESC
  LIMIT ${limitPlaceholder}
) recent
ORDER BY date ASC`;

  return { sql, values };
}

/** Converts a pg value to a number. Null, undefined and non-numeric values become null. */
function toNumberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

/**
 * Builds the response body. NUMERIC and BIGINT values may arrive as strings,
 * so they are converted with Number. Candles are sorted by date ascending.
 */
export function shapeCandles(symbol: string, rows: Array<Record<string, unknown>>): CandlesResponse {
  const candles: Candle[] = rows.map((row) => ({
    date: formatRunDate(row.date) ?? String(row.date),
    open: toNumberOrNull(row.open),
    high: toNumberOrNull(row.high),
    low: toNumberOrNull(row.low),
    close: toNumberOrNull(row.close),
    volume: toNumberOrNull(row.volume),
  }));
  candles.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return { symbol, candles };
}
