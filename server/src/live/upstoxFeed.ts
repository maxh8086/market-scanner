/**
 * Upstox market-data feed client. Runs in the server only: the browser never talks to Upstox.
 *
 * Flow: GET the authorize endpoint with the access token to get a WebSocket URL, connect, send a
 * subscribe message for the instrument keys, then decode each binary frame into ticks. On close or
 * error it reconnects with backoff and reports `reconnecting` until a socket is live again.
 *
 * The authorize response field (`data.authorized_redirect_uri`) and the subscribe message shape
 * follow Upstox's V3 docs as transcribed, not yet confirmed against a live response.
 */
import { backoffDelayMs } from "./reconnect.js";
import { decodeFeedFrame, type DecodedTick } from "./feedDecoder.js";

export const AUTHORIZE_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize";

export type FeedStatus = "unconfigured" | "connecting" | "live" | "reconnecting" | "stopped";

/** The subset of a WebSocket the client uses. The `ws` package satisfies it in production. */
export interface FeedSocket {
  send(data: string): void;
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
}

export interface FeedDeps {
  fetch: (url: string, init: { headers: Record<string, string> }) => Promise<{ ok: boolean; status: number; json: () => Promise<unknown> }>;
  createSocket: (url: string) => FeedSocket;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
}

export interface FeedListeners {
  onTick: (tick: DecodedTick) => void;
  onStatus: (status: FeedStatus) => void;
}

export interface LiveFeed {
  start(): void;
  stop(): void;
  status(): FeedStatus;
}

function extractRedirectUri(body: unknown): string | null {
  if (typeof body !== "object" || body === null) {
    return null;
  }
  const data = (body as { data?: unknown }).data;
  if (typeof data !== "object" || data === null) {
    return null;
  }
  const uri = (data as { authorized_redirect_uri?: unknown }).authorized_redirect_uri;
  return typeof uri === "string" && uri.length > 0 ? uri : null;
}

export function createLiveFeed(options: {
  accessToken: string | undefined;
  instrumentKeys: readonly string[];
  deps: FeedDeps;
  listeners: FeedListeners;
}): LiveFeed {
  const { accessToken, instrumentKeys, deps, listeners } = options;
  let status: FeedStatus = accessToken ? "stopped" : "unconfigured";
  let socket: FeedSocket | null = null;
  let retryTimer: unknown = null;
  let attempt = 0;
  let running = false;

  const setStatus = (next: FeedStatus) => {
    status = next;
    listeners.onStatus(next);
  };

  const scheduleReconnect = () => {
    if (!running) {
      return;
    }
    setStatus("reconnecting");
    const delay = backoffDelayMs(attempt);
    attempt += 1;
    retryTimer = deps.setTimer(() => {
      retryTimer = null;
      void connect();
    }, delay);
  };

  const connect = async () => {
    if (!running || !accessToken) {
      return;
    }
    setStatus(attempt === 0 ? "connecting" : "reconnecting");
    let wsUrl: string | null = null;
    try {
      const response = await deps.fetch(AUTHORIZE_URL, {
        headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` },
      });
      if (response.ok) {
        wsUrl = extractRedirectUri(await response.json());
      }
    } catch {
      wsUrl = null;
    }
    if (!running) {
      return;
    }
    if (!wsUrl) {
      scheduleReconnect();
      return;
    }

    const ws = deps.createSocket(wsUrl);
    socket = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ guid: "market-scanner-live", method: "sub", data: { mode: "ltpc", instrumentKeys } }));
      attempt = 0;
      setStatus("live");
    };
    ws.onmessage = (event) => {
      if (!(event.data instanceof Uint8Array) && !(event.data instanceof ArrayBuffer)) {
        return;
      }
      const bytes = event.data instanceof ArrayBuffer ? new Uint8Array(event.data) : event.data;
      try {
        for (const tick of decodeFeedFrame(bytes)) {
          listeners.onTick(tick);
        }
      } catch {
        // A frame that fails to decode is dropped; the next frame still updates prices.
      }
    };
    const onDown = () => {
      if (socket !== ws) {
        return;
      }
      socket = null;
      scheduleReconnect();
    };
    ws.onclose = onDown;
    ws.onerror = onDown;
  };

  return {
    start() {
      if (!accessToken || running) {
        return;
      }
      running = true;
      attempt = 0;
      void connect();
    },
    stop() {
      running = false;
      if (retryTimer !== null) {
        deps.clearTimer(retryTimer);
        retryTimer = null;
      }
      const current = socket;
      socket = null;
      current?.close();
      setStatus(accessToken ? "stopped" : "unconfigured");
    },
    status() {
      return status;
    },
  };
}
