import { useEffect, useState } from "react";

/** Same cap as the server's MAX_LIVE_SYMBOLS. Symbols beyond it are not streamed. */
export const LIVE_SYMBOL_LIMIT = 50;

/** Ticks arriving within this window are applied in one React update. */
const FLUSH_MS = 250;

/**
 * The server sends a heartbeat every 15 seconds. With no event for this long (two missed
 * heartbeats) the stream is treated as dead, even if the browser never reported an error.
 */
const HEARTBEAT_STALE_MS = 35_000;

/** Wait before opening a new stream after a silent one is dropped. */
const RECONNECT_MS = 3_000;

/** EventSource.CLOSED. Written as a literal so the hook does not depend on the global constant. */
const EVENT_SOURCE_CLOSED = 2;

export type LiveStatus = "idle" | "connecting" | "live" | "reconnecting" | "unavailable";

export interface LiveTick {
  symbol: string;
  ltp: number;
  ltt: number | null;
  /** Previous close. */
  cp: number | null;
  /** Day open, high and low. Only the index stream sends them. */
  open?: number | null;
  high?: number | null;
  low?: number | null;
}

export interface UseLiveTicksOptions {
  runId: string;
  symbols: readonly string[];
  /** False keeps the hook idle: no connection is opened. */
  enabled: boolean;
  /**
   * Streams the default watchlist indices from /api/live/indices instead of the run's stocks. The
   * server picks the index list, so runId and symbols are ignored.
   */
  indices?: boolean;
}

export interface LiveTicksState {
  ticks: ReadonlyMap<string, LiveTick>;
  status: LiveStatus;
}

const NO_TICKS: ReadonlyMap<string, LiveTick> = new Map();

export function buildLiveTicksUrl(runId: string, symbols: readonly string[]): string {
  const params = new URLSearchParams({ runId, symbols: symbols.join(",") });
  return `/api/live/ticks?${params.toString()}`;
}

export const INDICES_URL = "/api/live/indices";

/** Maps the server's feed status to the UI status. An unconfigured feed is shown as unavailable. */
export function mapFeedStatus(status: string): LiveStatus {
  switch (status) {
    case "live":
      return "live";
    case "connecting":
      return "connecting";
    case "reconnecting":
      return "reconnecting";
    case "unconfigured":
      return "unavailable";
    default:
      return "idle";
  }
}

function parseJsonObject(data: unknown): Record<string, unknown> | null {
  if (typeof data !== "string") {
    return null;
  }
  try {
    const body: unknown = JSON.parse(data);
    return typeof body === "object" && body !== null ? (body as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function parseTick(data: unknown): LiveTick | null {
  const body = parseJsonObject(data);
  if (!body || typeof body.symbol !== "string" || typeof body.ltp !== "number") {
    return null;
  }
  const price = (value: unknown) => (typeof value === "number" ? value : null);
  return {
    symbol: body.symbol,
    ltp: body.ltp,
    ltt: price(body.ltt),
    cp: price(body.cp),
    open: price(body.open),
    high: price(body.high),
    low: price(body.low),
  };
}

/**
 * Streams last-traded prices for the given symbols from GET /api/live/ticks. Ticks are batched
 * and applied at most every FLUSH_MS. Closing the hook (or changing the symbols) closes the stream.
 */
export function useLiveTicks(options: UseLiveTicksOptions): LiveTicksState {
  const { runId, symbols, enabled } = options;
  const [ticks, setTicks] = useState<ReadonlyMap<string, LiveTick>>(NO_TICKS);
  const [status, setStatus] = useState<LiveStatus>("idle");
  const symbolKey = symbols.join(",");
  const indices = options.indices === true;

  useEffect(() => {
    setTicks(NO_TICKS);
    const ready = indices || (runId !== "" && symbolKey !== "");
    if (!enabled || !ready || typeof EventSource === "undefined") {
      setStatus("idle");
      return;
    }

    setStatus("connecting");
    const url = indices ? INDICES_URL : buildLiveTicksUrl(runId, symbolKey.split(","));
    let source: EventSource | null = null;
    let stopped = false;
    let pending = new Map<string, LiveTick>();
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    let staleTimer: ReturnType<typeof setTimeout> | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const flush = () => {
      flushTimer = null;
      if (pending.size === 0) {
        return;
      }
      const batch = pending;
      pending = new Map();
      setTicks((previous) => {
        const next = new Map(previous);
        for (const [symbol, tick] of batch) {
          next.set(symbol, tick);
        }
        return next;
      });
    };

    const clearStale = () => {
      if (staleTimer !== null) {
        clearTimeout(staleTimer);
        staleTimer = null;
      }
    };

    // Any event (status, tick or heartbeat) proves the stream is alive. Silence drops it and reconnects.
    const armStale = () => {
      clearStale();
      staleTimer = setTimeout(() => {
        staleTimer = null;
        source?.close();
        source = null;
        setStatus("reconnecting");
        retryTimer = setTimeout(() => {
          retryTimer = null;
          connect();
        }, RECONNECT_MS);
      }, HEARTBEAT_STALE_MS);
    };

    function connect() {
      if (stopped) {
        return;
      }
      const next = new EventSource(url);
      source = next;
      armStale();

      next.addEventListener("status", (event) => {
        armStale();
        const body = parseJsonObject((event as MessageEvent).data);
        if (body && typeof body.status === "string") {
          setStatus(mapFeedStatus(body.status));
        }
      });

      next.addEventListener("heartbeat", () => armStale());

      next.addEventListener("tick", (event) => {
        armStale();
        const tick = parseTick((event as MessageEvent).data);
        if (!tick) {
          return;
        }
        pending.set(tick.symbol, tick);
        if (flushTimer === null) {
          flushTimer = setTimeout(flush, FLUSH_MS);
        }
      });

      // EventSource retries on its own. A closed source means the server refused the stream (for
      // example no instruments), so retrying would only repeat the failure.
      next.onerror = () => {
        if (next.readyState === EVENT_SOURCE_CLOSED) {
          clearStale();
          source = null;
          setStatus("unavailable");
          return;
        }
        setStatus("reconnecting");
      };
    }

    connect();

    return () => {
      stopped = true;
      source?.close();
      clearStale();
      if (retryTimer !== null) {
        clearTimeout(retryTimer);
        retryTimer = null;
      }
      if (flushTimer !== null) {
        clearTimeout(flushTimer);
        flushTimer = null;
      }
    };
  }, [enabled, runId, symbolKey, indices]);

  return { ticks, status };
}
