/** Client for POST /api/collector/index-eod/refresh. The server owns the post-market rule and the DB insert. */

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
    response = await fetch(INDEX_EOD_STATUS_URL, { signal: options.signal });
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

/** Queues a manual index_eod run. 202 is queued, 200 is already queued, 409 is market hours. */
export async function requestIndexEodRefresh(options: { signal?: AbortSignal } = {}): Promise<IndexEodRefreshResult> {
  let response: Response;
  try {
    response = await fetch(INDEX_EOD_REFRESH_URL, { method: "POST", signal: options.signal });
  } catch (error) {
    if (typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError") {
      throw error;
    }
    throw new CollectorRefreshError("Network error", null);
  }

  if (response.status === 202) return { kind: "queued" };
  if (response.status === 409) return { kind: "market_open" };
  if (response.status === 200) return { kind: "already_queued" };

  let message = `HTTP ${response.status}`;
  try {
    const body = (await response.json()) as { error?: unknown };
    if (typeof body.error === "string" && body.error.length > 0) message = body.error;
  } catch {
    // Body is not JSON; keep the status message.
  }
  throw new CollectorRefreshError(message, response.status);
}
