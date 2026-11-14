/**
 * Upstox long-term holdings. Used only for the holdings list (quantity, average cost, broker LTP and P&L).
 * The access token stays on the server; the app's client_id and secret are not needed for a holdings read.
 * Rows are mapped onto the same Holding shape as Kite, so the stored snapshot is the same for both brokers.
 */
import type { Holding, KiteFetch, KiteFetchResponse, KiteHoldingsResult } from "./kiteHoldings.js";

export const UPSTOX_HOLDINGS_URL = "https://api.upstox.com/v2/portfolio/long-term-holdings";

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Keeps only rows that have a trading_symbol and a quantity. Unknown fields are dropped. */
export function parseUpstoxHoldings(body: unknown): Holding[] | null {
  if (typeof body !== "object" || body === null) return null;
  const data = (body as { data?: unknown }).data;
  if (!Array.isArray(data)) return null;

  const holdings: Holding[] = [];
  for (const raw of data) {
    if (typeof raw !== "object" || raw === null) continue;
    const row = raw as Record<string, unknown>;
    const symbol = typeof row.trading_symbol === "string" ? row.trading_symbol : "";
    const quantity = num(row.quantity);
    if (!symbol || quantity === null) continue;
    holdings.push({
      symbol,
      exchange: typeof row.exchange === "string" ? row.exchange : "",
      isin: typeof row.isin === "string" && row.isin.length > 0 ? row.isin : null,
      quantity,
      averagePrice: num(row.average_price) ?? 0,
      lastPrice: num(row.last_price) ?? 0,
      pnl: num(row.pnl) ?? 0,
      dayChange: num(row.day_change),
      dayChangePct: num(row.day_change_percentage),
    });
  }
  return holdings;
}

export interface UpstoxHoldingsOptions {
  accessToken: string | undefined;
  fetch: KiteFetch;
}

export async function fetchUpstoxHoldings(options: UpstoxHoldingsOptions): Promise<KiteHoldingsResult> {
  if (!options.accessToken) {
    return { ok: false, status: 401, error: "Upstox login required. Log in again." };
  }

  let response: KiteFetchResponse;
  try {
    response = await options.fetch(UPSTOX_HOLDINGS_URL, {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${options.accessToken}`,
      },
    });
  } catch {
    return { ok: false, status: 502, error: "Could not reach Upstox." };
  }

  if (response.status === 401) {
    return { ok: false, status: 401, error: "Upstox login expired. Log in again." };
  }
  if (response.status === 403) {
    return {
      ok: false,
      status: 403,
      error: "Upstox refused the request. Check the static IP setting for the app.",
    };
  }
  if (!response.ok) {
    return { ok: false, status: 502, error: `Upstox returned status ${response.status}.` };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return { ok: false, status: 502, error: "Upstox returned a response that was not valid JSON." };
  }

  const holdings = parseUpstoxHoldings(body);
  if (holdings === null) {
    return { ok: false, status: 502, error: "Upstox returned an unexpected holdings shape." };
  }
  return { ok: true, holdings };
}
