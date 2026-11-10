/**
 * Validation and SQL building for POST /internal/events/batch (home_filings ingest, spec 4.6).
 *
 * validateBatch keeps each row that passes every check and counts the rest in `invalid`; one bad row
 * does not fail the batch. buildInsert builds one parameterised multi-row INSERT with
 * ON CONFLICT (dedupe_key) DO NOTHING. Every value is bound; nothing from a row is put into the SQL text.
 *
 * The enum lists must match the CHECK constraints in db/events_migrations/001_home_events.sql and the
 * Python FEEDS table. No test ties them together (spec 8); they are checked by hand at review.
 */

export const MAX_BATCH_ROWS = 500;
export const MAX_HEADLINE_LENGTH = 500;
export const EVENTS_EXCHANGES = ["NSE"] as const;
export const EVENT_TYPES = [
  "results",
  "insider_trade",
  "governance",
  "corporate_action",
  "shareholding",
  "related_party",
] as const;
export const FEED_TIERS = ["high_priority", "catalyst"] as const;

export interface HomeEventRow {
  dedupe_key: string;
  exchange: string;
  feed_code: string;
  source_id: string | null;
  source_url: string;
  isin: string;
  symbol: string;
  company: string | null;
  event_type: string;
  feed_tier: string;
  headline: string;
  published_at: string;
}

export interface BatchValidation {
  rows: HomeEventRow[];
  invalid: number;
}

export interface Built {
  text: string;
  values: unknown[];
}

const INSERT_COLUMNS: ReadonlyArray<keyof HomeEventRow> = [
  "dedupe_key",
  "exchange",
  "feed_code",
  "source_id",
  "source_url",
  "isin",
  "symbol",
  "company",
  "event_type",
  "feed_tier",
  "headline",
  "published_at",
];

// ISO 8601 date and time that must end in Z or a +hh:mm / -hh:mm offset.
const ISO_WITH_OFFSET = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})$/;

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isOptionalString(value: unknown): value is string | null {
  return value === null || value === undefined || typeof value === "string";
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function isValidPublishedAt(value: unknown): value is string {
  if (typeof value !== "string" || !ISO_WITH_OFFSET.test(value)) return false;
  return !Number.isNaN(Date.parse(value));
}

/** Returns the row with optional fields normalised to null, or null when any check fails. */
function checkRow(raw: unknown): HomeEventRow | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;

  if (!isNonEmptyString(row.dedupe_key)) return null;
  if (!(EVENTS_EXCHANGES as readonly unknown[]).includes(row.exchange)) return null;
  if (!isNonEmptyString(row.feed_code)) return null;
  if (!isOptionalString(row.source_id)) return null;
  if (!isNonEmptyString(row.source_url) || !isHttpUrl(row.source_url)) return null;
  if (!isNonEmptyString(row.isin)) return null;
  if (!isNonEmptyString(row.symbol)) return null;
  if (!isOptionalString(row.company)) return null;
  if (!(EVENT_TYPES as readonly unknown[]).includes(row.event_type)) return null;
  if (!(FEED_TIERS as readonly unknown[]).includes(row.feed_tier)) return null;
  if (!isNonEmptyString(row.headline) || row.headline.length > MAX_HEADLINE_LENGTH) return null;
  if (!isValidPublishedAt(row.published_at)) return null;

  return {
    dedupe_key: row.dedupe_key,
    exchange: row.exchange as string,
    feed_code: row.feed_code,
    source_id: row.source_id ?? null,
    source_url: row.source_url,
    isin: row.isin,
    symbol: row.symbol,
    company: row.company ?? null,
    event_type: row.event_type as string,
    feed_tier: row.feed_tier as string,
    headline: row.headline,
    published_at: row.published_at,
  };
}

/**
 * Splits a parsed request body `{rows: [...]}` into valid rows and a count of invalid ones.
 * A body without a rows array yields no rows and no invalid count; the route answers that shape with 400.
 */
export function validateBatch(body: unknown): BatchValidation {
  const rawRows =
    typeof body === "object" && body !== null && Array.isArray((body as { rows?: unknown }).rows)
      ? ((body as { rows: unknown[] }).rows)
      : [];
  const rows: HomeEventRow[] = [];
  let invalid = 0;
  for (const raw of rawRows) {
    const checked = checkRow(raw);
    if (checked) rows.push(checked);
    else invalid += 1;
  }
  return { rows, invalid };
}

/**
 * Builds the batch INSERT. Throws RangeError when there are no rows or more than MAX_BATCH_ROWS
 * (the route answers the over-limit case with 413 before it gets here).
 */
export function buildInsert(rows: HomeEventRow[]): Built {
  if (rows.length === 0) {
    throw new RangeError("buildInsert needs at least one row");
  }
  if (rows.length > MAX_BATCH_ROWS) {
    throw new RangeError(`buildInsert accepts at most ${MAX_BATCH_ROWS} rows, got ${rows.length}`);
  }
  const values: unknown[] = [];
  const groups: string[] = [];
  for (const row of rows) {
    const placeholders: string[] = [];
    for (const column of INSERT_COLUMNS) {
      values.push(row[column]);
      placeholders.push(`$${values.length}`);
    }
    groups.push(`(${placeholders.join(", ")})`);
  }
  const text =
    `INSERT INTO home_events (${INSERT_COLUMNS.join(", ")}) VALUES ${groups.join(", ")} ` +
    "ON CONFLICT (dedupe_key) DO NOTHING";
  return { text, values };
}
