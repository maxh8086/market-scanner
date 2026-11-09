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
