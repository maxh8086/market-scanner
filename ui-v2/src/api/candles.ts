/** Client for GET /api/stocks/:symbol/candles. Shape mirrors the server candles endpoint. */

import { apiGet } from "./session";

export interface Candle {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
}

export interface CandlesResponse {
  symbol: string;
  candles: Candle[];
}

export interface CandlesQuery {
  from?: string;
  to?: string;
  limit?: number;
}

export interface FetchCandlesOptions extends CandlesQuery {
  signal?: AbortSignal;
}

/** Failure from the candles API: a non-OK status, a network error or a bad body. */
export class CandlesError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "CandlesError";
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

const isNumberOrNull = (value: unknown): value is number | null =>
  value === null || (typeof value === "number" && Number.isFinite(value));

function isCandle(value: unknown): value is Candle {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candle = value as Record<string, unknown>;
  return (
    typeof candle.date === "string" &&
    isNumberOrNull(candle.open) &&
    isNumberOrNull(candle.high) &&
    isNumberOrNull(candle.low) &&
    isNumberOrNull(candle.close) &&
    isNumberOrNull(candle.volume)
  );
}

function isCandlesResponse(body: unknown): body is CandlesResponse {
  if (typeof body !== "object" || body === null) {
    return false;
  }
  const response = body as Partial<CandlesResponse>;
  return Array.isArray(response.candles) && response.candles.every(isCandle);
}

/** Builds the query string from the params that are set. */
function buildCandlesQueryString(query: CandlesQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  return params.toString();
}

export async function fetchCandles(symbol: string, options: FetchCandlesOptions = {}): Promise<CandlesResponse> {
  const { signal, ...query } = options;
  const queryString = buildCandlesQueryString(query);
  const path = `/api/stocks/${encodeURIComponent(symbol)}/candles`;
  const url = queryString ? `${path}?${queryString}` : path;

  let response: Response;
  try {
    response = await apiGet(url, {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new CandlesError("Could not reach the candles service.", null);
  }

  if (!response.ok) {
    throw new CandlesError(await readErrorMessage(response), response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new CandlesError("The candles response was not valid JSON.", response.status);
  }

  if (!isCandlesResponse(body)) {
    throw new CandlesError("The candles response had an unexpected shape.", response.status);
  }
  return body;
}
