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
