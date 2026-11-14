/**
 * Pure query parsing, SQL builders and row mapper for GET /api/events. No database access here.
 * Every user value is passed as a $N placeholder. The events database holds home_events only.
 */
import { toIstIso } from "./collectorDue.js";

export interface Built {
  sql: string;
  values: unknown[];
}

export type EventsTier = "high_priority" | "catalyst";

export interface EventsQuery {
  days: number;
  tier: EventsTier | undefined;
  limit: number;
  symbol: string | undefined;
}

export type ParseResult = { ok: true; value: EventsQuery } | { ok: false };

type Field<T> = { ok: true; value: T } | { ok: false };

export const DEFAULT_DAYS = 7;
export const MAX_DAYS = 30;
export const DEFAULT_LIMIT = 100;
export const MAX_LIMIT = 200;

const INTEGER_RE = /^[0-9]+$/;
const SYMBOL_RE = /^[A-Z0-9&-]{1,20}$/;
const TIERS: ReadonlySet<string> = new Set(["high_priority", "catalyst"]);

/** An integer query value in [min, max]. Absent gives the default; anything else is invalid. */
function readInt(value: unknown, fallback: number, min: number, max: number): Field<number> {
  if (value === undefined) return { ok: true, value: fallback };
  if (typeof value !== "string" || !INTEGER_RE.test(value)) return { ok: false };
  const n = Number(value);
  return n >= min && n <= max ? { ok: true, value: n } : { ok: false };
}

function readTier(value: unknown): Field<EventsTier | undefined> {
  if (value === undefined) return { ok: true, value: undefined };
  if (typeof value === "string" && TIERS.has(value)) return { ok: true, value: value as EventsTier };
  return { ok: false };
}

/** Upper-cases the symbol first, so lowercase input is accepted. */
function readSymbol(value: unknown): Field<string | undefined> {
  if (value === undefined) return { ok: true, value: undefined };
  if (typeof value !== "string") return { ok: false };
  const upper = value.toUpperCase();
  return SYMBOL_RE.test(upper) ? { ok: true, value: upper } : { ok: false };
}

/** Parses the raw querystring. Unknown params are ignored; arrays and empty strings are invalid. */
export function parseEventsQuery(raw: Record<string, unknown>): ParseResult {
  const days = readInt(raw.days, DEFAULT_DAYS, 1, MAX_DAYS);
  const limit = readInt(raw.limit, DEFAULT_LIMIT, 1, MAX_LIMIT);
  const tier = readTier(raw.tier);
  const symbol = readSymbol(raw.symbol);
  if (!days.ok || !limit.ok || !tier.ok || !symbol.ok) return { ok: false };
  return { ok: true, value: { days: days.value, tier: tier.value, limit: limit.value, symbol: symbol.value } };
}

/**
 * Events for the window. The 3-per-stock cap (rn <= 3) is a display cap only: a symbol
 * query skips it and returns every stored row for that symbol.
 */
export function buildEventsSql(q: EventsQuery): Built {
  const sql = `SELECT dedupe_key, symbol, isin, company, event_type, feed_tier, feed_code,
       headline, published_at, fetched_at, source_url
FROM (
  SELECT *, row_number() OVER (PARTITION BY isin ORDER BY published_at DESC) AS rn
  FROM home_events
  WHERE published_at >= now() - make_interval(days => $1)
    AND ($2::text IS NULL OR feed_tier = $2)
    AND ($3::text IS NULL OR symbol = $3)
) t
WHERE ($3::text IS NOT NULL OR rn <= 3)
ORDER BY (feed_tier = 'high_priority') DESC, published_at DESC
LIMIT $4;`;
  return { sql, values: [q.days, q.tier ?? null, q.symbol ?? null, q.limit] };
}

/** Newest fetched_at in the window across all stored rows (the data-age stamp). */
export function buildLatestFetchedSql(days: number): Built {
  return {
    sql: "SELECT max(fetched_at) AS latest FROM home_events WHERE published_at >= now() - make_interval(days => $1)",
    values: [days],
  };
}

export interface EventItem {
  id: string | null;
  symbol: string | null;
  isin: string | null;
  company: string | null;
  event_type: string | null;
  feed_tier: string | null;
  feed_code: string | null;
  headline: string | null;
  published_at: string | null;
  fetched_at: string | null;
  source_url: string | null;
}

/** An instant as an ISO string in IST, from a pg Date or a string. Null when it cannot be read. */
export function toIsoOrNull(value: unknown): string | null {
  const instant = value instanceof Date ? value : typeof value === "string" ? new Date(value) : null;
  if (instant === null || Number.isNaN(instant.getTime())) return null;
  return toIstIso(instant);
}

function textOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** Maps one events row to the response shape. Text is returned verbatim; the UI renders it as text only. */
export function mapEventRow(row: Record<string, unknown>): EventItem {
  return {
    id: textOrNull(row.dedupe_key),
    symbol: textOrNull(row.symbol),
    isin: textOrNull(row.isin),
    company: textOrNull(row.company),
    event_type: textOrNull(row.event_type),
    feed_tier: textOrNull(row.feed_tier),
    feed_code: textOrNull(row.feed_code),
    headline: textOrNull(row.headline),
    published_at: toIsoOrNull(row.published_at),
    fetched_at: toIsoOrNull(row.fetched_at),
    source_url: textOrNull(row.source_url),
  };
}
