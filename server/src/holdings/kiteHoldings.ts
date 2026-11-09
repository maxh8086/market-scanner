/**
 * Zerodha Kite holdings. Used only for the holdings list (quantity, average cost, broker LTP and P&L).
 * Live prices come from Upstox, not from here. The API key and access token stay on the server.
 */

export const KITE_HOLDINGS_URL = "https://api.kite.trade/portfolio/holdings";

export interface Holding {
  symbol: string;
  isin: string | null;
  quantity: number;
  averagePrice: number;
  lastPrice: number;
  pnl: number;
  /** Today's change per share in rupees, from Kite. */
  dayChange: number | null;
  /** Today's change in percent, from Kite. */
  dayChangePct: number | null;
}

export type KiteFetchResponse = { ok: boolean; status: number; json: () => Promise<unknown> };
export type KiteFetch = (url: string, init: { headers: Record<string, string> }) => Promise<KiteFetchResponse>;

export type KiteHoldingsResult =
  | { ok: true; holdings: Holding[] }
  | { ok: false; status: number; error: string };

export interface KiteHoldingsOptions {
  apiKey: string | undefined;
  accessToken: string | undefined;
  fetch: KiteFetch;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Keeps only rows that have a symbol and a quantity. Unknown fields are dropped. */
export function parseKiteHoldings(body: unknown): Holding[] | null {
  if (typeof body !== "object" || body === null) return null;
  const data = (body as { data?: unknown }).data;
  if (!Array.isArray(data)) return null;

  const holdings: Holding[] = [];
  for (const raw of data) {
    if (typeof raw !== "object" || raw === null) continue;
    const row = raw as Record<string, unknown>;
    const symbol = typeof row.tradingsymbol === "string" ? row.tradingsymbol : "";
    const quantity = num(row.quantity);
    if (!symbol || quantity === null) continue;
    holdings.push({
      symbol,
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

export async function fetchKiteHoldings(options: KiteHoldingsOptions): Promise<KiteHoldingsResult> {
  if (!options.apiKey || !options.accessToken) {
    return { ok: false, status: 503, error: "Kite is not configured. Set KITE_API_KEY and KITE_ACCESS_TOKEN." };
  }

  let response: KiteFetchResponse;
  try {
    response = await options.fetch(KITE_HOLDINGS_URL, {
      headers: {
        "X-Kite-Version": "3",
        Authorization: `token ${options.apiKey}:${options.accessToken}`,
      },
    });
  } catch {
    return { ok: false, status: 502, error: "Could not reach Kite." };
  }

  if (response.status === 403) {
    return { ok: false, status: 401, error: "Kite session expired. Update KITE_ACCESS_TOKEN." };
  }
  if (!response.ok) {
    return { ok: false, status: 502, error: `Kite returned status ${response.status}.` };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return { ok: false, status: 502, error: "Kite returned a response that was not valid JSON." };
  }

  const holdings = parseKiteHoldings(body);
  if (holdings === null) {
    return { ok: false, status: 502, error: "Kite returned an unexpected holdings shape." };
  }
  return { ok: true, holdings };
}
