import { describe, expect, it, vi } from "vitest";
import { encodeFeedFrame } from "./feedDecoder.js";
import { AUTHORIZE_URL, createLiveFeed, type FeedSocket, type FeedStatus } from "./upstoxFeed.js";

class FakeSocket implements FeedSocket {
  sent: Array<string | Uint8Array> = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
  }
}

function authorizeResponse(uri: string) {
  return { ok: true, status: 200, json: async () => ({ status: "success", data: { authorized_redirect_uri: uri } }) };
}

async function flush() {
  for (let i = 0; i < 5; i++) {
    await Promise.resolve();
  }
}

function setupWithoutToken() {
  return setupWith(undefined);
}

function setup() {
  return setupWith("test-token");
}

function setupWith(accessToken: string | undefined) {
  const sockets: FakeSocket[] = [];
  const timers: Array<{ fn: () => void; ms: number }> = [];
  const statuses: FeedStatus[] = [];
  const ticks: unknown[] = [];
  const fetch = vi.fn(async () => authorizeResponse("wss://feed.example/socket"));
  const feed = createLiveFeed({
    accessToken,
    instrumentKeys: ["NSE_EQ|INE002A01018"],
    deps: {
      fetch,
      createSocket: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      setTimer: (fn, ms) => {
        timers.push({ fn, ms });
        return timers.length;
      },
      clearTimer: vi.fn(),
    },
    listeners: {
      onTick: (tick) => ticks.push(tick),
      onStatus: (status) => statuses.push(status),
    },
  });
  return { feed, fetch, sockets, timers, statuses, ticks };
}

describe("createLiveFeed", () => {
  it("is unconfigured and never connects without an access token", () => {
    const { feed, fetch, statuses } = setupWithoutToken();

    feed.start();

    expect(feed.status()).toBe("unconfigured");
    expect(fetch).not.toHaveBeenCalled();
    expect(statuses).toEqual([]);
  });

  it("authorizes with the token, subscribes on open, and passes decoded ticks through", async () => {
    const { feed, fetch, sockets, statuses, ticks } = setup();

    feed.start();
    await flush();
    expect(fetch).toHaveBeenCalledWith(AUTHORIZE_URL, {
      headers: { Accept: "application/json", Authorization: "Bearer test-token" },
    });
    expect(sockets).toHaveLength(1);

    sockets[0].onopen?.();
    expect(JSON.parse(new TextDecoder().decode(sockets[0].sent[0] as Uint8Array))).toEqual({
      guid: "market-scanner-live",
      method: "sub",
      data: { mode: "ltpc", instrumentKeys: ["NSE_EQ|INE002A01018"] },
    });
    expect(feed.status()).toBe("live");

    const frame = encodeFeedFrame([{ instrumentKey: "NSE_EQ|INE002A01018", ltp: 100 }]);
    sockets[0].onmessage?.({ data: frame });
    expect(ticks).toEqual([
      { instrumentKey: "NSE_EQ|INE002A01018", ltp: 100, ltt: null, cp: null, open: null, high: null, low: null },
    ]);
    expect(statuses).toEqual(["connecting", "live"]);
  });

  it("reports reconnecting after a drop and reconnects after the first backoff step", async () => {
    const { feed, sockets, timers, statuses } = setup();
    feed.start();
    await flush();
    sockets[0].onopen?.();

    sockets[0].onclose?.();
    expect(feed.status()).toBe("reconnecting");
    expect(timers).toHaveLength(1);
    expect(timers[0].ms).toBe(1_000);

    timers[0].fn();
    await flush();
    expect(sockets).toHaveLength(2);
    expect(statuses.at(-1)).toBe("reconnecting");
  });

  it("stops reconnecting once stopped and closes the open socket", async () => {
    const { feed, sockets, timers } = setup();
    feed.start();
    await flush();
    sockets[0].onopen?.();

    feed.stop();
    expect(sockets[0].closed).toBe(true);
    expect(feed.status()).toBe("stopped");

    sockets[0].onclose?.();
    expect(timers).toHaveLength(0);
  });

  it("sends the subscribe request as a binary Uint8Array frame", async () => {
    const { feed, sockets } = setup();
    feed.start();
    await flush();

    sockets[0].onopen?.();

    const payload = sockets[0].sent[0];
    expect(payload).toBeInstanceOf(Uint8Array);
    const decoded = JSON.parse(new TextDecoder().decode(payload as Uint8Array));
    expect(decoded.method).toBe("sub");
    expect(decoded.data.instrumentKeys).toEqual(["NSE_EQ|INE002A01018"]);
  });
});
