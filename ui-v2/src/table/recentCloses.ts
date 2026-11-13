/**
 * Client for GET /api/recent-closes. It fetches the last closes for many symbols at once, for the
 * scan table sparklines. Symbols go out in batches of 100, the server's cap per request.
 */

/** Symbols per request. Matches the server's MAX_CLOSES_SYMBOLS. */
export const RECENT_CLOSES_BATCH_SIZE = 100;
/** Closes per symbol. Matches the server default. */
export const RECENT_CLOSES_LIMIT = 30;

import { apiGet } from "../api/session";

export type RecentCloses = Record<string, number[]>;

/** Failure from the closes API: a network error, a non-OK status or a bad body. */
export class RecentClosesError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "RecentClosesError";
    this.status = status;
  }
}

export interface FetchRecentClosesOptions {
  signal?: AbortSignal;
}

function isClosesBody(value: unknown): value is { closes: RecentCloses } {
  if (typeof value !== "object" || value === null || !("closes" in value)) {
    return false;
  }
  const closes = (value as { closes: unknown }).closes;
  return (
    typeof closes === "object" &&
    closes !== null &&
    Object.values(closes).every((list) => Array.isArray(list) && list.every((n) => typeof n === "number"))
  );
}

async function fetchBatch(symbols: readonly string[], options: FetchRecentClosesOptions): Promise<RecentCloses> {
  const params = new URLSearchParams({
    symbols: symbols.join(","),
    limit: String(RECENT_CLOSES_LIMIT),
  });

  let response: Response;
  try {
    response = await apiGet(`/api/recent-closes?${params.toString()}`, {
      signal: options.signal,
      headers: { Accept: "application/json" },
    });
  } catch {
    throw new RecentClosesError("Could not reach the closes service.", null);
  }

  if (!response.ok) {
    throw new RecentClosesError(`Closes request failed with status ${response.status}.`, response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new RecentClosesError("The closes response was not valid JSON.", response.status);
  }
  if (!isClosesBody(body)) {
    throw new RecentClosesError("The closes response had an unexpected shape.", response.status);
  }
  return body.closes;
}

/**
 * Closes for the given symbols, oldest first. Symbols with no stored candles are absent from the
 * result. Rejects when any batch fails, so the caller can decide whether to retry.
 */
export async function fetchRecentCloses(
  symbols: readonly string[],
  options: FetchRecentClosesOptions = {},
): Promise<RecentCloses> {
  const batches: string[][] = [];
  for (let start = 0; start < symbols.length; start += RECENT_CLOSES_BATCH_SIZE) {
    batches.push(symbols.slice(start, start + RECENT_CLOSES_BATCH_SIZE));
  }
  const parts = await Promise.all(batches.map((batch) => fetchBatch(batch, options)));
  return Object.assign({}, ...parts) as RecentCloses;
}
