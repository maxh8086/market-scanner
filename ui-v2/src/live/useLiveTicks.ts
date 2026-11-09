import { useEffect, useState } from "react";

/** Same cap as the server's MAX_LIVE_SYMBOLS. Symbols beyond it are not streamed. */
export const LIVE_SYMBOL_LIMIT = 50;

/** Ticks arriving within this window are applied in one React update. */
const FLUSH_MS = 250;

/** EventSource.CLOSED. Written as a literal so the hook does not depend on the global constant. */
const EVENT_SOURCE_CLOSED = 2;

export type LiveStatus = "idle" | "connecting" | "live" | "reconnecting" | "unavailable";

export interface LiveTick {
  symbol: string;
  ltp: number;
  ltt: number | null;
  cp: number | null;
}

export interface UseLiveTicksOptions {
  runId: string;
  symbols: readonly string[];
  /** False keeps the hook idle: no connection is opened. */
  enabled: boolean;
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
  return {
    symbol: body.symbol,
    ltp: body.ltp,
    ltt: typeof body.ltt === "number" ? body.ltt : null,
    cp: typeof body.cp === "number" ? body.cp : null,
  };
}

/**
 * Streams last-traded prices for the given symbols from GET /api/live/ticks. Ticks are batched
 * and applied at most every FLUSH_MS. Closing the hook (or changing the symbols) closes the stream.
 */
export function useLiveTicks({ runId, symbols, enabled }: UseLiveTicksOptions): LiveTicksState {
  const [ticks, setTicks] = useState<ReadonlyMap<string, LiveTick>>(NO_TICKS);
  const [status, setStatus] = useState<LiveStatus>("idle");
  const symbolKey = symbols.join(",");

  useEffect(() => {
    setTicks(NO_TICKS);
    if (!enabled || !runId || symbolKey === "" || typeof EventSource === "undefined") {
      setStatus("idle");
      return;
    }

    setStatus("connecting");
    const source = new EventSource(buildLiveTicksUrl(runId, symbolKey.split(",")));
    let pending = new Map<string, LiveTick>();
    let timer: ReturnType<typeof setTimeout> | null = null;

    const flush = () => {
      timer = null;
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

    source.addEventListener("status", (event) => {
      const body = parseJsonObject((event as MessageEvent).data);
      if (body && typeof body.status === "string") {
        setStatus(mapFeedStatus(body.status));
      }
    });

    source.addEventListener("tick", (event) => {
      const tick = parseTick((event as MessageEvent).data);
      if (!tick) {
        return;
      }
      pending.set(tick.symbol, tick);
      if (timer === null) {
        timer = setTimeout(flush, FLUSH_MS);
      }
    });

    // EventSource retries on its own. A closed source means the server refused the stream (for
    // example no instruments), so retrying would only repeat the failure.
    source.onerror = () => {
      setStatus(source.readyState === EVENT_SOURCE_CLOSED ? "unavailable" : "reconnecting");
    };

    return () => {
      source.close();
      if (timer !== null) {
        clearTimeout(timer);
      }
    };
  }, [enabled, runId, symbolKey]);

  return { ticks, status };
}
