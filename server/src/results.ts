/**
 * Pure SQL builders for the run results endpoint. No database access here.
 * Every user value is passed as a $N placeholder. Sort columns come only
 * from the SORT_COLUMNS whitelist.
 */

export interface Built {
  sql: string;
  values: unknown[];
}

export interface ResultsParams {
  runId: string;
  page?: number;
  perPage?: number;
  sort?: string;
  order?: string;
  bucket?: string;
  stance?: string;
  search?: string;
  industry?: string;
  ltpMin?: number;
  ltpMax?: number;
  distanceMin?: number;
  distanceMax?: number;
  athFrom?: string;
  athTo?: string;
}

export const DEFAULT_PER_PAGE = 20;
export const MAX_PER_PAGE = 100;

const SORT_COLUMNS: ReadonlyMap<string, string> = new Map([
  ["symbol", "ss.symbol"],
  ["company", "ss.company"],
  ["ltp", "ss.ltp"],
  ["distance_pct", "ss.distance_pct"],
  ["ath_date", "ss.ath_date"],
  ["one_year_return_pct", "ss.one_year_return_pct"],
  ["order_pct_of_sales", "ss.order_pct_of_sales"],
  ["stance", "ss.stance"],
  ["bucket", "ss.bucket"],
]);

const RUN_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const RUN_UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** True for a real calendar date in YYYY-MM-DD form. */
export function isIsoDate(value: string): boolean {
  if (!RUN_DATE_RE.test(value)) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

export function normalizePaging(
  page: number | undefined,
  perPage: number | undefined,
): { page: number; perPage: number; offset: number } {
  const safePage = page !== undefined && Number.isInteger(page) && page >= 1 ? page : 1;
  const safePerPage =
    perPage !== undefined && Number.isInteger(perPage) && perPage >= 1
      ? Math.min(perPage, MAX_PER_PAGE)
      : DEFAULT_PER_PAGE;
  return { page: safePage, perPage: safePerPage, offset: (safePage - 1) * safePerPage };
}

/** Escapes LIKE wildcards so user text matches literally. */
function likePattern(text: string): string {
  return `%${text.replace(/[\\%_]/g, (c) => `\\${c}`)}%`;
}

function buildWhere(params: ResultsParams): { clause: string; values: unknown[] } {
  const clauses: string[] = [];
  const values: unknown[] = [];
  const ph = (value: unknown): string => {
    values.push(value);
    return `$${values.length}`;
  };

  clauses.push(`ss.run_id = ${ph(params.runId)}`);

  if (params.bucket && params.bucket !== "all") {
    clauses.push(`ss.bucket = ${ph(params.bucket)}`);
  }
  if (params.stance && params.stance !== "all") {
    clauses.push(`ss.stance = ${ph(params.stance)}`);
  }
  if (params.search) {
    const pattern = likePattern(params.search);
    clauses.push(`(ss.symbol ILIKE ${ph(pattern)} OR ss.company ILIKE ${ph(pattern)})`);
  }
  if (params.industry) {
    clauses.push(`ss.industry ILIKE ${ph(likePattern(params.industry))}`);
  }

  const ranges: Array<[string, number | undefined, number | undefined]> = [
    ["ss.ltp", params.ltpMin, params.ltpMax],
    ["ss.distance_pct", params.distanceMin, params.distanceMax],
  ];
  for (const [column, lo, hi] of ranges) {
    if (lo != null) clauses.push(`${column} >= ${ph(lo)}`);
    if (hi != null) clauses.push(`${column} <= ${ph(hi)}`);
  }

  if (params.athFrom) clauses.push(`ss.ath_date >= ${ph(params.athFrom)}`);
  if (params.athTo) clauses.push(`ss.ath_date <= ${ph(params.athTo)}`);

  return { clause: clauses.join(" AND "), values };
}

export function buildResultsQuery(params: ResultsParams): Built {
  const { clause, values } = buildWhere(params);
  const { perPage, offset } = normalizePaging(params.page, params.perPage);
  const sortColumn = SORT_COLUMNS.get(params.sort ?? "symbol") ?? "ss.symbol";
  const direction = params.order?.toLowerCase() === "desc" ? "DESC" : "ASC";

  values.push(perPage);
  const limitPlaceholder = `$${values.length}`;
  values.push(offset);
  const offsetPlaceholder = `$${values.length}`;

  const sql = `
SELECT
  ss.symbol, ss.company, ss.industry, ss.ltp, ss.distance_pct, ss.ath_date,
  ss.one_year_return_pct, ss.order_pct_of_sales, ss.stance, ss.bucket,
  EXISTS (
    SELECT 1 FROM snapshot_changes sc
    WHERE sc.run_id = ss.run_id AND sc.symbol = ss.symbol
  ) AS changed
FROM stock_snapshots ss
WHERE ${clause}
ORDER BY ${sortColumn} ${direction} NULLS LAST, ss.symbol ASC
LIMIT ${limitPlaceholder} OFFSET ${offsetPlaceholder}`;

  return { sql, values };
}

export function buildCountQuery(params: ResultsParams): Built {
  const { clause, values } = buildWhere(params);
  return {
    sql: `SELECT COUNT(*)::int AS total FROM stock_snapshots ss WHERE ${clause}`,
    values,
  };
}

/**
 * Resolves a run id (UUID) or run date (YYYY-MM-DD) to a run row.
 * A date picks the current run for that date, newest first, as api.py does.
 * Returns null when the value is neither a valid UUID nor a valid date.
 */
export function buildRunLookupQuery(runId: string): Built | null {
  if (isIsoDate(runId)) {
    return {
      sql: "SELECT run_id FROM runs WHERE run_date = $1 ORDER BY is_current DESC, started_at DESC LIMIT 1",
      values: [runId],
    };
  }
  if (RUN_UUID_RE.test(runId)) {
    return { sql: "SELECT run_id FROM runs WHERE run_id = $1 LIMIT 1", values: [runId] };
  }
  return null;
}
