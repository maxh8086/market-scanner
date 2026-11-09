/** Helpers for the live ticks route: symbol validation, ISIN lookup, and server-sent event framing. */
import WebSocket from "ws";
import type { FeedSocket } from "./upstoxFeed.js";

export const MAX_LIVE_SYMBOLS = 50;
const SYMBOL_PATTERN = /^[A-Z0-9&-]{1,20}$/;

export type ParsedSymbols = { ok: true; symbols: string[] } | { ok: false; error: string };

/** Accepts a comma-separated list of NSE symbols. Rejects empty, malformed or oversized lists. */
export function parseLiveSymbols(raw: unknown): ParsedSymbols {
  if (typeof raw !== "string" || raw.trim() === "") {
    return { ok: false, error: "symbols is required" };
  }
  const symbols = [...new Set(raw.split(",").map((part) => part.trim().toUpperCase()).filter((part) => part !== ""))];
  if (symbols.length === 0) {
    return { ok: false, error: "symbols is required" };
  }
  if (symbols.length > MAX_LIVE_SYMBOLS) {
    return { ok: false, error: `at most ${MAX_LIVE_SYMBOLS} symbols` };
  }
  if (!symbols.every((symbol) => SYMBOL_PATTERN.test(symbol))) {
    return { ok: false, error: "symbols must be NSE tickers" };
  }
  return { ok: true, symbols };
}

/** Looks up ISINs for the symbols in one run. Parameterised: symbols are passed as an array, never concatenated. */
export function buildIsinLookupQuery(runId: string, symbols: readonly string[]): { sql: string; values: unknown[] } {
  return {
    sql: "SELECT symbol, isin FROM stock_snapshots WHERE run_id = $1 AND symbol = ANY($2::text[]) AND isin IS NOT NULL",
    values: [runId, [...symbols]],
  };
}

/**
 * Watchlist indices mapped to Upstox instrument keys. Keys are upper-cased watchlist names, which is
 * how the UI looks rows up. Entries match the NSE instrument master by name and are mirrored in
 * scanner/index_candles.py (INDEX_KEYS) for the EOD collector. SENSEX is not in that master and its
 * key is unchecked. Indices without a key show "—" in the watchlist. GIFT NIFTY has no key.
 * NIFTY SMLCAP 250, NIFTY500 MUL50:25:25 and NIFTY SERVICES use the keys given for them directly.
 */
export const INDEX_INSTRUMENT_KEYS: Readonly<Record<string, string>> = {
  SENSEX: "BSE_INDEX|SENSEX",
  "INDIA VIX": "NSE_INDEX|India VIX",
  "NIFTY 50": "NSE_INDEX|Nifty 50",
  "NIFTY NEXT 50": "NSE_INDEX|Nifty Next 50",
  "NIFTY 100": "NSE_INDEX|Nifty 100",
  "NIFTY 200": "NSE_INDEX|Nifty 200",
  "NIFTY 500": "NSE_INDEX|Nifty 500",
  "NIFTY BANK": "NSE_INDEX|Nifty Bank",
  "NIFTY MIDCAP 150": "NSE_INDEX|NIFTY MIDCAP 150",
  "NIFTY SMLCAP 250": "NSE_INDEX|NIFTY_SMLCAP_250",
  "NIFTY500 MUL50:25:25": "NSE_INDEX|NIFTY500 MULTICAP",
  "NIFTY SERVICES": "NSE_INDEX|Nifty Serv Sector",
  "NIFTY MICROCAP 250": "NSE_INDEX|NIFTY MICROCAP250",
  "NIFTY MIDCAP 100": "NSE_INDEX|NIFTY MIDCAP 100",
  "NIFTY MIDCAP 50": "NSE_INDEX|Nifty Midcap 50",
  "NIFTY SMALLCAP 100": "NSE_INDEX|NIFTY SMLCAP 100",
  "NIFTY SMLCAP 50": "NSE_INDEX|NIFTY SMLCAP 50",
  "NIFTY 750 TOTAL MKT": "NSE_INDEX|NIFTY TOTAL MKT",
  "NIFTY AUTO": "NSE_INDEX|Nifty Auto",
  "NIFTY IT": "NSE_INDEX|Nifty IT",
  "NIFTY PSU BANK": "NSE_INDEX|Nifty PSU Bank",
  "NIFTY FIN SERVICE": "NSE_INDEX|Nifty Fin Service",
  "NIFTY PHARMA": "NSE_INDEX|Nifty Pharma",
  "NIFTY FMCG": "NSE_INDEX|Nifty FMCG",
  "NIFTY METAL": "NSE_INDEX|Nifty Metal",
  "NIFTY REALTY": "NSE_INDEX|Nifty Realty",
  "NIFTY MEDIA": "NSE_INDEX|Nifty Media",
  "NIFTY ENERGY": "NSE_INDEX|Nifty Energy",
  "NIFTY PVT BANK": "NSE_INDEX|Nifty Pvt Bank",
  "NIFTY INFRA": "NSE_INDEX|Nifty Infra",
  "NIFTY COMMODITIES": "NSE_INDEX|Nifty Commodities",
  "NIFTY CONSUMPTION": "NSE_INDEX|Nifty Consumption",
  "NIFTY PSE": "NSE_INDEX|Nifty PSE",
  "NIFTY FINSRV25/50": "NSE_INDEX|Nifty FinSrv25 50",
  "NIFTY CONS DURBL": "NSE_INDEX|NIFTY CONSR DURBL",
  "NIFTY HEALTHCARE": "NSE_INDEX|NIFTY HEALTHCARE",
  "NIFTY OIL & GAS": "NSE_INDEX|NIFTY OIL AND GAS",
  "NIFTY INDIA MFG": "NSE_INDEX|NIFTY INDIA MFG",
  "NIFTY INDIA DEFENCE": "NSE_INDEX|Nifty Ind Defence",
  "NIFTY MIDSML 400": "NSE_INDEX|NIFTY MIDSML 400",
  "NIFTY MNC": "NSE_INDEX|Nifty MNC",
  "NIFTY ALPHALOWVOL 30": "NSE_INDEX|NIFTY AlphaLowVol",
  "NIFTY200 MOMENTUM 30": "NSE_INDEX|Nifty200Momentm30",
  "NIFTY LARGEMID250": "NSE_INDEX|NIFTY LARGEMID250",
  "NIFTY CPSE": "NSE_INDEX|Nifty CPSE",
  "NIFTY MID SELECT": "NSE_INDEX|NIFTY MID SELECT",
  "NIFTY IND DIGITAL": "NSE_INDEX|NIFTY IND DIGITAL",
  "NIFTY M150 QLTY50": "NSE_INDEX|NIFTY M150 QLTY50",
  "NIFTY CAPITAL MARKET": "NSE_INDEX|Nifty Capital Mkt",
  "NIFTY INDIA FPI 150": "NSE_INDEX|Nifty FPI 150",
};

/** Most index names one live stream may carry. Every watchlist index fits, with room to spare. */
export const MAX_LIVE_INDEX_NAMES = 50;

export type ParsedIndexNames = { ok: true; names: string[] } | { ok: false; error: string };

/**
 * Parses the comma-separated watchlist index names for /api/live/indices. Names without an
 * instrument key (for example GIFT NIFTY) are dropped, since the watchlist shows them as "—". The
 * request fails only when no name has a key, or when the list is oversized.
 */
export function parseIndexNames(raw: unknown): ParsedIndexNames {
  if (typeof raw !== "string" || raw.trim() === "") {
    return { ok: false, error: "symbols is required" };
  }
  const requested = [...new Set(raw.split(",").map((part) => part.trim().toUpperCase()).filter((part) => part !== ""))];
  if (requested.length === 0) {
    return { ok: false, error: "symbols is required" };
  }
  if (requested.length > MAX_LIVE_INDEX_NAMES) {
    return { ok: false, error: `at most ${MAX_LIVE_INDEX_NAMES} symbols` };
  }
  const names = requested.filter((name) => Object.hasOwn(INDEX_INSTRUMENT_KEYS, name));
  if (names.length === 0) {
    return { ok: false, error: "no symbols have a live index key" };
  }
  return { ok: true, names };
}

/** Upstox instrument key for an NSE equity: NSE_EQ|<ISIN>. */
export function nseEquityKey(isin: string): string {
  return `NSE_EQ|${isin.trim()}`;
}

/** One server-sent event frame. JSON data is always single-line, so one `data:` line is enough. */
export function formatSseEvent(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** Production socket factory: the `ws` package, adapted to the FeedSocket interface. */
export function createWsSocket(url: string): FeedSocket {
  const ws = new WebSocket(url);
  ws.binaryType = "nodebuffer";
  const socket: FeedSocket = {
    send: (data) => ws.send(data),
    close: () => ws.close(),
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
  };
  ws.on("open", () => socket.onopen?.());
  ws.on("message", (data: Buffer, isBinary: boolean) => {
    if (isBinary) {
      socket.onmessage?.({ data: new Uint8Array(data) });
    }
  });
  ws.on("close", () => socket.onclose?.());
  ws.on("error", () => socket.onerror?.());
  return socket;
}
