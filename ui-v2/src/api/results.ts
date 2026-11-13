/** Client for GET /api/runs/:runId/results. Shape mirrors server/src/app.ts. */

import { apiGet } from "./session";

export interface Row {
  symbol: string;
  company: string | null;
  industry: string | null;
  ltp: number | null;
  distance_pct: number | null;
  ath_date: string | null;
  one_year_return_pct: number | null;
  order_pct_of_sales: number | null;
  stance: string | null;
  bucket: string | null;
  changed: boolean;
}

export type SortOrder = "asc" | "desc";

export interface ResultsQuery {
  page?: number;
  perPage?: number;
  sort?: string;
  order?: SortOrder;
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

export interface ResultsPage {
  results: Row[];
  total: number;
  page: number;
  perPage: number;
}

export interface FetchResultsOptions {
  signal?: AbortSignal;
}

/** Failure from the results API: a non-OK status, a network error or a bad body. */
export class ResultsError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "ResultsError";
    this.status = status;
  }
}

/** Builds a query string from the params that are set. Empty and undefined values are skipped. */
export function buildResultsQueryString(query: ResultsQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  return params.toString();
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: unknown };
    if (typeof body.error === "string" && body.error.length > 0) {
      return body.error;
    }
  } catch {
    // Body is not JSON; fall through to the generic message.
  }
  return `Request failed with status ${response.status}.`;
}

function isResultsPage(body: unknown): body is ResultsPage {
  if (typeof body !== "object" || body === null) {
    return false;
  }
  const page = body as Partial<ResultsPage>;
  return (
    Array.isArray(page.results) &&
    typeof page.total === "number" &&
    typeof page.page === "number" &&
    typeof page.perPage === "number"
  );
}

export async function fetchResults(
  runId: string,
  query: ResultsQuery = {},
  options: FetchResultsOptions = {},
): Promise<ResultsPage> {
  const queryString = buildResultsQueryString(query);
  const path = `/api/runs/${encodeURIComponent(runId)}/results`;
  const url = queryString ? `${path}?${queryString}` : path;

  let response: Response;
  try {
    response = await apiGet(url, {
      headers: { Accept: "application/json" },
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new ResultsError("Could not reach the results service.", null);
  }

  if (!response.ok) {
    throw new ResultsError(await readErrorMessage(response), response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ResultsError("The results response was not valid JSON.", response.status);
  }

  if (!isResultsPage(body)) {
    throw new ResultsError("The results response had an unexpected shape.", response.status);
  }
  return body;
}
