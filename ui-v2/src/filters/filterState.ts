import { buildResultsQueryString, type ResultsQuery } from "../api/results";

/** The filter fields of a results query. Paging and sort are kept by the table, not here. */
export type FilterState = Pick<
  ResultsQuery,
  | "bucket"
  | "stance"
  | "search"
  | "industry"
  | "ltpMin"
  | "ltpMax"
  | "distanceMin"
  | "distanceMax"
  | "athFrom"
  | "athTo"
>;

/** True when at least one filter would be sent to the results API. */
export function hasActiveFilters(filters: FilterState): boolean {
  return buildResultsQueryString(filters) !== "";
}

/** Reads the raw input strings for the given filter keys. Missing keys read as "". */
export function readFilterValues(filters: FilterState, keys: readonly (keyof FilterState)[]): string[] {
  return keys.map((key) => {
    const value = filters[key];
    return value === undefined || value === null ? "" : String(value);
  });
}

/**
 * Writes raw input strings back to the given filter keys. An empty string removes the key, so it
 * is not sent. Numeric keys drop values that are not finite numbers.
 */
export function writeFilterValues(
  filters: FilterState,
  keys: readonly (keyof FilterState)[],
  values: readonly string[],
  numeric: boolean,
): FilterState {
  const copy: Record<string, unknown> = { ...filters };
  keys.forEach((key, index) => {
    const raw = (values[index] ?? "").trim();
    const parsed = numeric && raw !== "" ? Number(raw) : raw;
    if (raw === "" || (typeof parsed === "number" && !Number.isFinite(parsed))) {
      delete copy[key];
    } else {
      copy[key] = parsed;
    }
  });
  return copy as FilterState;
}
