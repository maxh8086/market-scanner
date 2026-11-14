/** Client for GET /api/holdings: the latest stored portfolio snapshot for a profile (no live broker call). */

import { apiGet } from "./session";
import type { BrokerName } from "./broker";

export interface Holding {
  symbol: string;
  isin: string | null;
  quantity: number;
  averagePrice: number;
  lastPrice: number;
  pnl: number;
  dayChange: number | null;
  dayChangePct: number | null;
}

/** The stored snapshot. syncedAt and broker are null when no sync has run yet. */
export interface HoldingsSnapshot {
  holdings: Holding[];
  syncedAt: string | null;
  broker: BrokerName | null;
}

export class HoldingsError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "HoldingsError";
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

function isHoldingsBody(body: unknown): body is { holdings: Holding[] } {
  return typeof body === "object" && body !== null && Array.isArray((body as { holdings?: unknown }).holdings);
}

export async function fetchHoldings(options: { signal?: AbortSignal } = {}): Promise<HoldingsSnapshot> {
  let response: Response;
  try {
    response = await apiGet("/api/holdings", {
      headers: { Accept: "application/json" },
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new HoldingsError("Could not reach the holdings service.", null);
  }

  if (!response.ok) {
    throw new HoldingsError(await readErrorMessage(response), response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new HoldingsError("The holdings response was not valid JSON.", response.status);
  }
  if (!isHoldingsBody(body)) {
    throw new HoldingsError("The holdings response had an unexpected shape.", response.status);
  }
  const { syncedAt, broker } = body as { syncedAt?: unknown; broker?: unknown };
  return {
    holdings: body.holdings,
    syncedAt: typeof syncedAt === "string" ? syncedAt : null,
    broker: broker === "kite" ? "kite" : null,
  };
}
