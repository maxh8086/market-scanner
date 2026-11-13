/** Client for GET /api/runs/:runId/filter-options. Shape mirrors the server route that lists filter values. */

import { apiGet } from "./session";

export interface FilterOptions {
  bucket: string[];
  stance: string[];
}

export interface FetchFilterOptionsOptions {
  signal?: AbortSignal;
}

/** Failure from the filter-options API: a non-OK status, a network error or a bad body. */
export class FilterOptionsError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "FilterOptionsError";
    this.status = status;
  }
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

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isFilterOptions(body: unknown): body is FilterOptions {
  if (typeof body !== "object" || body === null) {
    return false;
  }
  const options = body as Partial<FilterOptions>;
  return isStringArray(options.bucket) && isStringArray(options.stance);
}

export async function fetchFilterOptions(
  runId: string,
  options: FetchFilterOptionsOptions = {},
): Promise<FilterOptions> {
  const url = `/api/runs/${encodeURIComponent(runId)}/filter-options`;

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
    throw new FilterOptionsError("Could not reach the filter options service.", null);
  }

  if (!response.ok) {
    throw new FilterOptionsError(await readErrorMessage(response), response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new FilterOptionsError("The filter options response was not valid JSON.", response.status);
  }

  if (!isFilterOptions(body)) {
    throw new FilterOptionsError("The filter options response had an unexpected shape.", response.status);
  }
  return body;
}
