/** Client for POST /api/collector/index-eod/refresh. The server owns the post-market rule and the DB insert. */

import { apiGet, CSRF_HEADER, getCsrfToken, invalidateCsrfToken } from "./session";

export const INDEX_EOD_REFRESH_URL = "/api/collector/index-eod/refresh";

export type IndexEodRefreshResult =
  | { kind: "queued" }
  | { kind: "already_queued" }
  | { kind: "market_open" };

/** Failure from the refresh API: a network error, an unexpected status or a bad body. */
export class CollectorRefreshError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "CollectorRefreshError";
    this.status = status;
  }
}

export const INDEX_EOD_STATUS_URL = "/api/collector/index-eod/status";

/** What the database recorded about the index_eod source. All times come from collector_runs. */
export interface IndexEodStatus {
  /** ISO time the last successful run finished, or null if none has run. */
  lastRefreshedAt: string | null;
  /** How long the last successful run took, in seconds, or null if none has run. */
  lastRunSeconds: number | null;
  /** Longest wait before the collector picks up a queued request. */
  pickupSeconds: number;
}

/**
 * Reads the index_eod status from the database. Throws CollectorRefreshError on failure.
 */
export async function fetchIndexEodStatus(options: { signal?: AbortSignal } = {}): Promise<IndexEodStatus> {
  let response: Response;
  try {
    response = await apiGet(INDEX_EOD_STATUS_URL, { signal: options.signal });
  } catch (error) {
    if (typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError") {
      throw error;
    }
    throw new CollectorRefreshError("Network error", null);
  }
  if (!response.ok) {
    throw new CollectorRefreshError(`HTTP ${response.status}`, response.status);
  }
  const body = (await response.json()) as {
    lastRefreshedAt?: unknown;
    lastRunSeconds?: unknown;
    pickupSeconds?: unknown;
  };
  return {
    lastRefreshedAt: typeof body.lastRefreshedAt === "string" ? body.lastRefreshedAt : null,
    lastRunSeconds: typeof body.lastRunSeconds === "number" ? body.lastRunSeconds : null,
    pickupSeconds: typeof body.pickupSeconds === "number" ? body.pickupSeconds : 60,
  };
}

/** Error codes the CSRF gate returns when the refresh write needs a fresh session or token. */
const GATE_RETRY_CODES = new Set(["session_required", "csrf_required"]);

/**
 * Sends the refresh POST with the CSRF token from the given promise, so a retry can pass a fresh one.
 * A failure to start the session is reported as a network error.
 */
async function postRefresh(signal: AbortSignal | undefined, tokenPromise: Promise<string>): Promise<Response> {
  let csrfToken: string;
  try {
    csrfToken = await tokenPromise;
  } catch {
    throw new CollectorRefreshError("Network error", null);
  }
  try {
    return await fetch(INDEX_EOD_REFRESH_URL, {
      method: "POST",
      headers: { [CSRF_HEADER]: csrfToken },
      signal,
    });
  } catch (error) {
    if (typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError") {
      throw error;
    }
    throw new CollectorRefreshError("Network error", null);
  }
}

async function readErrorField(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { error?: unknown };
    if (typeof body.error === "string" && body.error.length > 0) return body.error;
  } catch {
    // Body is not JSON; the caller falls back to the status message.
  }
  return undefined;
}

/**
 * Queues a manual index_eod run. 202 is queued, 200 is already queued, 409 is market hours.
 * A gate rejection (401 session_required or 403 csrf_required) retries the POST exactly once with a fresh token.
 */
export async function requestIndexEodRefresh(options: { signal?: AbortSignal } = {}): Promise<IndexEodRefreshResult> {
  let tokenPromise = getCsrfToken();
  let response = await postRefresh(options.signal, tokenPromise);
  // bodyError holds the error field when the current response body was already read.
  let bodyRead = false;
  let bodyError: string | undefined;
  if (response.status === 401 || response.status === 403) {
    bodyError = await readErrorField(response);
    bodyRead = true;
    if (bodyError !== undefined && GATE_RETRY_CODES.has(bodyError)) {
      invalidateCsrfToken(tokenPromise);
      tokenPromise = getCsrfToken();
      response = await postRefresh(options.signal, tokenPromise);
      bodyRead = false;
      bodyError = undefined;
    }
  }

  if (response.status === 202) return { kind: "queued" };
  if (response.status === 409) return { kind: "market_open" };
  if (response.status === 200) return { kind: "already_queued" };

  const error = bodyRead ? bodyError : await readErrorField(response);
  throw new CollectorRefreshError(error ?? `HTTP ${response.status}`, response.status);
}
