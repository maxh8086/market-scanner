import { browserSession } from "../src/sessionTestHelper.js";
import type { AddressInfo } from "node:net";
import { describe, expect, it } from "vitest";
import { buildApp, type CreateFeedFn, type QueryFn } from "../src/app.js";
import {
  buildIsinLookupQuery,
  formatSseEvent,
  MAX_LIVE_SYMBOLS,
  nseEquityKey,
  parseLiveSymbols,
} from "../src/live/liveRoute.js";
import type { FeedListeners, FeedStatus, LiveFeed } from "../src/live/upstoxFeed.js";

const RUN_ID = "11111111-2222-3333-4444-555555555555";

/** Returns the queued row sets in call order, recording every SQL call. */
function queuedQuery(results: Array<Array<Record<string, unknown>>>) {
  const calls: Array<{ sql: string; values: unknown[] }> = [];
  let next = 0;
  const query: QueryFn = async (sql, values) => {
    calls.push({ sql, values });
    return { rows: results[next++] ?? [] };
  };
  return { query, calls };
}

function fakeFeed(onStart: (listeners: FeedListeners) => void) {
  let status: FeedStatus = "connecting";
  let stopped = false;
  const captured: { keys: string[]; mode?: string } = { keys: [] };
  const createFeed: CreateFeedFn = ({ instrumentKeys, listeners, mode }) => {
    captured.keys = instrumentKeys;
    captured.mode = mode;
    const feed: LiveFeed = {
      start: () => onStart(listeners),
      stop: () => {
        stopped = true;
        status = "stopped";
      },
      status: () => status,
    };
    return feed;
  };
  return { createFeed, captured, wasStopped: () => stopped };
}

async function waitUntil(predicate: () => boolean, timeoutMs = 2_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error("condition not met in time");
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

describe("parseLiveSymbols", () => {
  it("uppercases, trims, and removes duplicates", () => {
    expect(parseLiveSymbols(" tcs, infy ,TCS,")).toEqual({ ok: true, symbols: ["TCS", "INFY"] });
  });

  it("rejects a missing or blank list", () => {
    expect(parseLiveSymbols(undefined).ok).toBe(false);
    expect(parseLiveSymbols(" , ").ok).toBe(false);
  });

  it("rejects more than the symbol limit", () => {
    const many = Array.from({ length: MAX_LIVE_SYMBOLS + 1 }, (_, i) => `S${i}`).join(",");
    expect(parseLiveSymbols(many)).toEqual({ ok: false, error: `at most ${MAX_LIVE_SYMBOLS} symbols` });
  });

  it("rejects values that are not NSE-style tickers", () => {
    expect(parseLiveSymbols("TCS';DROP").ok).toBe(false);
    expect(parseLiveSymbols("tcs,a b").ok).toBe(false);
  });
});

describe("live helpers", () => {
  it("builds an NSE_EQ instrument key from an ISIN", () => {
    expect(nseEquityKey(" INE467B01029 ")).toBe("NSE_EQ|INE467B01029");
  });

  it("passes symbols as a bound array, not concatenated SQL", () => {
    const { sql, values } = buildIsinLookupQuery(RUN_ID, ["TCS", "INFY"]);
    expect(sql).toContain("symbol = ANY($2::text[])");
    expect(sql).not.toContain("TCS");
    expect(values).toEqual([RUN_ID, ["TCS", "INFY"]]);
  });

  it("formats one SSE event with single-line JSON data", () => {
    expect(formatSseEvent("tick", { symbol: "TCS", ltp: 3500 })).toBe(
      'event: tick\ndata: {"symbol":"TCS","ltp":3500}\n\n',
    );
  });
});

describe("GET /api/live/ticks validation", () => {
  it("returns 400 when symbols are missing", async () => {
    const app = buildApp({ query: queuedQuery([]).query });
    const res = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: `/api/live/ticks?runId=${RUN_ID}` });
    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: "symbols is required" });
  });

  it("returns 404 for an unknown run without querying instruments", async () => {
    const { query, calls } = queuedQuery([[]]);
    const app = buildApp({ query });
    const res = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: "/api/live/ticks?runId=not-a-run&symbols=TCS" });
    expect(res.statusCode).toBe(404);
    expect(calls).toHaveLength(0);
  });

  it("returns 404 when none of the symbols resolve to an ISIN in the run", async () => {
    const { query } = queuedQuery([[{ run_id: RUN_ID }], []]);
    const app = buildApp({ query });
    const res = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: `/api/live/ticks?runId=${RUN_ID}&symbols=ZZZZ` });
    expect(res.statusCode).toBe(404);
    expect(res.json()).toEqual({ error: "No instruments found for symbols" });
  });
});

describe("GET /api/live/indices stream", () => {
  it("subscribes the index keys in full mode and streams OHL under the watchlist name", async () => {
    const fake = fakeFeed((listeners) => {
      listeners.onStatus("live");
      listeners.onTick({ instrumentKey: "NSE_INDEX|Nifty 50", ltp: 25008.5, ltt: null, cp: 24986.4, open: 25010, high: 25055.2, low: 24960.1 });
      listeners.onTick({ instrumentKey: "NSE_INDEX|UNKNOWN", ltp: 1, ltt: null, cp: null });
    });
    const app = buildApp({ query: queuedQuery([]).query, live: { accessToken: "token", createFeed: fake.createFeed } });
    await app.listen({ host: "127.0.0.1", port: 0 });
    const { port } = app.server.address() as AddressInfo;

    const controller = new AbortController();
    const res = await fetch(`http://127.0.0.1:${port}/api/live/indices`, {
      signal: controller.signal,
      headers: { cookie: (await browserSession(app)).cookie },
    });
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let text = "";
    while (!text.includes('event: tick\ndata: {"symbol":"NIFTY 50"')) {
      const { value, done } = await reader.read();
      if (done) break;
      text += decoder.decode(value);
    }

    expect(fake.captured.mode).toBe("full");
    expect(fake.captured.keys).toContain("NSE_INDEX|Nifty 50");
    expect(text).toContain(
      'event: tick\ndata: {"symbol":"NIFTY 50","ltp":25008.5,"ltt":null,"cp":24986.4,"open":25010,"high":25055.2,"low":24960.1}',
    );
    expect(text).not.toContain("UNKNOWN");

    controller.abort();
    await waitUntil(() => fake.wasStopped());
    await app.close();
  });

  it("subscribes only the requested watchlist names and drops names without a key", async () => {
    const fake = fakeFeed((listeners) => listeners.onStatus("live"));
    const app = buildApp({ query: queuedQuery([]).query, live: { accessToken: "token", createFeed: fake.createFeed } });
    await app.listen({ host: "127.0.0.1", port: 0 });
    const { port } = app.server.address() as AddressInfo;

    const controller = new AbortController();
    const res = await fetch(
      `http://127.0.0.1:${port}/api/live/indices?symbols=${encodeURIComponent("Nifty Bank,GIFT NIFTY,nifty 50")}`,
      { signal: controller.signal, headers: { cookie: (await browserSession(app)).cookie } },
    );
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let text = "";
    while (!text.includes("event: status")) {
      const { value, done } = await reader.read();
      if (done) break;
      text += decoder.decode(value);
    }

    expect(fake.captured.keys).toEqual(["NSE_INDEX|Nifty Bank", "NSE_INDEX|Nifty 50"]);

    controller.abort();
    await waitUntil(() => fake.wasStopped());
    await app.close();
  });

  it("returns 400 when no requested name has a live index key", async () => {
    const app = buildApp({ query: queuedQuery([]).query });
    const res = await app.inject({ headers: { cookie: (await browserSession(app)).cookie }, method: "GET", url: `/api/live/indices?symbols=${encodeURIComponent("GIFT NIFTY,NOT AN INDEX")}` });
    expect(res.statusCode).toBe(400);
    await app.close();
  });
});

describe("live access token from getAccessToken", () => {
  function tokenRecorder() {
    const seen: Array<string | undefined> = [];
    let stopped = false;
    const createFeed: CreateFeedFn = ({ accessToken }) => {
      seen.push(accessToken);
      const feed: LiveFeed = {
        start: () => {},
        stop: () => {
          stopped = true;
        },
        status: () => "connecting",
      };
      return feed;
    };
    return { createFeed, seen, wasStopped: () => stopped };
  }

  it("passes the resolved token, not the static one, to createFeed on /api/live/indices", async () => {
    const rec = tokenRecorder();
    const app = buildApp({
      query: queuedQuery([]).query,
      live: { accessToken: "static-token", getAccessToken: async () => "resolved-token", createFeed: rec.createFeed },
    });
    await app.listen({ host: "127.0.0.1", port: 0 });
    const { port } = app.server.address() as AddressInfo;

    const controller = new AbortController();
    const res = await fetch(`http://127.0.0.1:${port}/api/live/indices`, {
      signal: controller.signal,
      headers: { cookie: (await browserSession(app)).cookie },
    });
    expect(res.status).toBe(200);
    expect(rec.seen).toEqual(["resolved-token"]);

    controller.abort();
    await waitUntil(() => rec.wasStopped());
    await app.close();
  });

  it("passes the resolved token to createFeed on /api/live/ticks", async () => {
    const { query } = queuedQuery([[{ run_id: RUN_ID }], [{ symbol: "TCS", isin: "INE467B01029" }]]);
    const rec = tokenRecorder();
    const app = buildApp({
      query,
      live: { getAccessToken: async () => "resolved-token", createFeed: rec.createFeed },
    });
    await app.listen({ host: "127.0.0.1", port: 0 });
    const { port } = app.server.address() as AddressInfo;

    const controller = new AbortController();
    const res = await fetch(`http://127.0.0.1:${port}/api/live/ticks?runId=${RUN_ID}&symbols=tcs`, {
      signal: controller.signal,
      headers: { cookie: (await browserSession(app)).cookie },
    });
    expect(res.status).toBe(200);
    expect(rec.seen).toEqual(["resolved-token"]);

    controller.abort();
    await waitUntil(() => rec.wasStopped());
    await app.close();
  });

  it("falls back to the unconfigured path (undefined token) when getAccessToken rejects", async () => {
    const rec = tokenRecorder();
    const app = buildApp({
      query: queuedQuery([]).query,
      live: {
        accessToken: "static-token",
        getAccessToken: async () => {
          throw new Error("secrets unavailable");
        },
        createFeed: rec.createFeed,
      },
    });
    await app.listen({ host: "127.0.0.1", port: 0 });
    const { port } = app.server.address() as AddressInfo;

    const controller = new AbortController();
    const res = await fetch(`http://127.0.0.1:${port}/api/live/indices`, {
      signal: controller.signal,
      headers: { cookie: (await browserSession(app)).cookie },
    });
    expect(res.status).toBe(200);
    expect(rec.seen).toEqual([undefined]);

    controller.abort();
    await waitUntil(() => rec.wasStopped());
    await app.close();
  });

  it("passes undefined when getAccessToken resolves to nothing", async () => {
    const rec = tokenRecorder();
    const app = buildApp({
      query: queuedQuery([]).query,
      live: { getAccessToken: async () => undefined, createFeed: rec.createFeed },
    });
    await app.listen({ host: "127.0.0.1", port: 0 });
    const { port } = app.server.address() as AddressInfo;

    const controller = new AbortController();
    const res = await fetch(`http://127.0.0.1:${port}/api/live/indices`, {
      signal: controller.signal,
      headers: { cookie: (await browserSession(app)).cookie },
    });
    expect(res.status).toBe(200);
    expect(rec.seen).toEqual([undefined]);

    controller.abort();
    await waitUntil(() => rec.wasStopped());
    await app.close();
  });
});

describe("GET /api/live/ticks stream", () => {
  it("streams status and tick events for resolved symbols, then stops the feed on disconnect", async () => {
    const { query, calls } = queuedQuery([[{ run_id: RUN_ID }], [{ symbol: "TCS", isin: "INE467B01029" }]]);
    const fake = fakeFeed((listeners) => {
      listeners.onStatus("live");
      listeners.onTick({ instrumentKey: "NSE_EQ|INE467B01029", ltp: 3500, ltt: null, cp: 3480 });
      listeners.onTick({ instrumentKey: "NSE_EQ|UNKNOWN", ltp: 1, ltt: null, cp: null });
    });
    const app = buildApp({ query, live: { accessToken: "token", createFeed: fake.createFeed } });
    await app.listen({ host: "127.0.0.1", port: 0 });
    const { port } = app.server.address() as AddressInfo;

    const controller = new AbortController();
    const res = await fetch(`http://127.0.0.1:${port}/api/live/ticks?runId=${RUN_ID}&symbols=tcs`, {
      signal: controller.signal,
      headers: { cookie: (await browserSession(app)).cookie },
    });
    expect(res.headers.get("content-type")).toContain("text/event-stream");

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let text = "";
    while (!text.includes('event: tick\ndata: {"symbol":"TCS"')) {
      const { value, done } = await reader.read();
      if (done) break;
      text += decoder.decode(value);
    }

    expect(text).toContain('event: status\ndata: {"status":"connecting"}');
    expect(text).toContain('event: status\ndata: {"status":"live"}');
    expect(text).toContain('event: tick\ndata: {"symbol":"TCS","ltp":3500,"ltt":null,"cp":3480}');
    expect(text).not.toContain("UNKNOWN");
    expect(fake.captured.keys).toEqual(["NSE_EQ|INE467B01029"]);
    expect(calls[1].values).toEqual([RUN_ID, ["TCS"]]);

    controller.abort();
    await waitUntil(() => fake.wasStopped());
    await app.close();
  });
});

describe("client leaves during the live token fetch", () => {
  function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((done) => {
      resolve = done;
    });
    return { promise, resolve };
  }

  const pause = (ms: number) => new Promise((done) => setTimeout(done, ms));

  function countingFeed() {
    const created: Array<string | undefined> = [];
    const createFeed: CreateFeedFn = ({ accessToken }) => {
      created.push(accessToken);
      const feed: LiveFeed = { start: () => {}, stop: () => {}, status: () => "connecting" };
      return feed;
    };
    return { createFeed, created };
  }

  it("does not create a feed on /api/live/indices when the browser aborts before the token resolves", async () => {
    const token = deferred<string>();
    let tokenRequests = 0;
    const feed = countingFeed();
    const app = buildApp({
      query: queuedQuery([]).query,
      live: {
        getAccessToken: () => {
          tokenRequests++;
          return token.promise;
        },
        createFeed: feed.createFeed,
      },
    });
    await app.listen({ host: "127.0.0.1", port: 0 });
    const { port } = app.server.address() as AddressInfo;
    const cookie = (await browserSession(app)).cookie;

    const controller = new AbortController();
    const request = fetch(`http://127.0.0.1:${port}/api/live/indices`, {
      signal: controller.signal,
      headers: { cookie },
    }).catch(() => undefined);
    await waitUntil(() => tokenRequests === 1);
    controller.abort();
    await request;
    await pause(50);
    token.resolve("resolved-token");
    await pause(50);

    expect(feed.created).toHaveLength(0);
    await app.close();
  });

  it("does not create a feed on /api/live/ticks when the browser aborts before the token resolves", async () => {
    const { query } = queuedQuery([[{ run_id: RUN_ID }], [{ symbol: "TCS", isin: "INE467B01029" }]]);
    const token = deferred<string>();
    let tokenRequests = 0;
    const feed = countingFeed();
    const app = buildApp({
      query,
      live: {
        getAccessToken: () => {
          tokenRequests++;
          return token.promise;
        },
        createFeed: feed.createFeed,
      },
    });
    await app.listen({ host: "127.0.0.1", port: 0 });
    const { port } = app.server.address() as AddressInfo;
    const cookie = (await browserSession(app)).cookie;

    const controller = new AbortController();
    const request = fetch(`http://127.0.0.1:${port}/api/live/ticks?runId=${RUN_ID}&symbols=tcs`, {
      signal: controller.signal,
      headers: { cookie },
    }).catch(() => undefined);
    await waitUntil(() => tokenRequests === 1);
    controller.abort();
    await request;
    await pause(50);
    token.resolve("resolved-token");
    await pause(50);

    expect(feed.created).toHaveLength(0);
    await app.close();
  });
});
