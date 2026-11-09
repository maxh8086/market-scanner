/**
 * Pure SQL builder and response shaper for the run filter-options endpoint.
 * No database access here. The run id is always a $1 placeholder.
 */

import type { Built } from "./results.js";

export interface FilterOptions {
  bucket: string[];
  stance: string[];
}

/**
 * One statement that returns the distinct non-empty bucket and stance values
 * for a run as two text[] columns. Each array is sorted ascending and falls
 * back to an empty array when the run has no matching rows.
 */
export function buildFilterOptionsQuery(runId: string): Built {
  const sql = `
SELECT
  COALESCE(
    (SELECT array_agg(DISTINCT ss.bucket ORDER BY ss.bucket)
       FROM stock_snapshots ss
      WHERE ss.run_id = $1 AND ss.bucket IS NOT NULL AND ss.bucket <> ''),
    ARRAY[]::text[]
  ) AS bucket,
  COALESCE(
    (SELECT array_agg(DISTINCT ss.stance ORDER BY ss.stance)
       FROM stock_snapshots ss
      WHERE ss.run_id = $1 AND ss.stance IS NOT NULL AND ss.stance <> ''),
    ARRAY[]::text[]
  ) AS stance`;

  return { sql, values: [runId] };
}

function cleanList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  for (const item of value) {
    if (typeof item === "string" && item !== "") seen.add(item);
  }
  return [...seen].sort();
}

/**
 * Converts the single row from buildFilterOptionsQuery into the response shape.
 * Drops nulls and empty strings, removes duplicates, and sorts ascending.
 * Returns empty lists when there is no row.
 */
export function shapeFilterOptions(rows: Array<Record<string, unknown>>): FilterOptions {
  const row = rows[0];
  if (!row) return { bucket: [], stance: [] };
  return { bucket: cleanList(row.bucket), stance: cleanList(row.stance) };
}
