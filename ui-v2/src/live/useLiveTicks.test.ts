import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetCsrfTokenForTests } from "../api/session";
import { buildIndicesUrl, buildLiveTicksUrl, mapFeedStatus, useLiveTicks } from "./useLiveTicks";

type Listener = (event: { data: string }) => void;

/** Mirrors RECONNECT_MS and MAX_CLOSED_RETRIES in useLiveTicks.ts. */
const RECONNECT_MS = 3_000;
const MAX_CLOSED_RETRIES = 3;

/** Minimal EventSource stand-in. Tests drive it with emit() and fail(). */
class FakeEventSource {
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];
  readyState = 0;
  closed = false;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Listener[]>();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  emit(type: string, body: unknown) {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data: JSON.stringify(body) });
    }
  }

  fail(closed: boolean) {
    this.readyState = closed ? FakeEventSource.CLOSED : 0;
    this.onerror?.();
  }
}

/** The hook waits for a session before opening the stream. Only microtasks run, so fake timers stay untouched. */
async function settleSession() {
  await act(async () => {
    for (let i = 0; i < 20; i++) {
      await Promise.resolve();
    }
  });
}

/** Waits until the hook has opened its stream after the session call, then returns it. */
async function firstSource(): Promise<FakeEventSource> {
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
  return FakeEventSource.instances[0];
}

/** A successful /api/session response. */
function okSessionResponse(csrfToken = "test-token"): Response {
  return { ok: true, json: async () => ({ csrfToken }) } as unknown as Response;
}

/** How many fetch calls so far went to /api/session. */
function sessionFetchCount(): number {
  return vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/api/session")).length;
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  resetCsrfTokenForTests();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({ csrfToken: "test-token" }) })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildLiveTicksUrl", () => {
  it("encodes the run id and comma-joins the symbols", () => {
    expect(buildLiveTicksUrl("run 1", ["TCS", "INFY"])).toBe("/api/live/ticks?runId=run+1&symbols=TCS%2CINFY");
  });
});

describe("buildIndicesUrl", () => {
  it("sends the visible watchlist names as the symbols parameter", () => {
    expect(buildIndicesUrl(["NIFTY 50", "Nifty Bank"])).toBe("/api/live/indices?symbols=NIFTY+50%2CNifty+Bank");
  });
});

describe("mapFeedStatus", () => {
  it("maps server feed states to UI states, and unconfigured to unavailable", () => {
    expect(mapFeedStatus("live")).toBe("live");
    expect(mapFeedStatus("connecting")).toBe("connecting");
    expect(mapFeedStatus("reconnecting")).toBe("reconnecting");
    expect(mapFeedStatus("unconfigured")).toBe("unavailable");
    expect(mapFeedStatus("stopped")).toBe("idle");
    expect(mapFeedStatus("something-new")).toBe("idle");
  });
});

describe("useLiveTicks", () => {
  it("opens no stream when disabled", () => {
    const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: false }));

    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current.status).toBe("idle");
  });

  it("opens no stream when there are no symbols", () => {
    renderHook(() => useLiveTicks({ runId: "r1", symbols: [], enabled: true }));

    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("opens a stream for the run and symbols, then reports live from the status event", async () => {
    const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS", "INFY"], enabled: true }));

    await firstSource();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/live/ticks?runId=r1&symbols=TCS%2CINFY");
    expect(result.current.status).toBe("connecting");

    act(() => FakeEventSource.instances[0].emit("status", { status: "live" }));
    expect(result.current.status).toBe("live");
  });

  it("applies ticks by symbol after the batching window", async () => {
    const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
    const source = await firstSource();

    act(() => source.emit("tick", { symbol: "TCS", ltp: 3500, ltt: null, cp: 3480 }));

    await waitFor(() => expect(result.current.ticks.get("TCS")?.ltp).toBe(3500));
  });

  it("ignores malformed tick data", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();
      const source = FakeEventSource.instances[0];
      act(() => {
        source.emit("tick", { symbol: "TCS", ltp: 3500, ltt: null, cp: 3480 });
        source.emit("tick", { symbol: 42, ltp: "x" });
        source.emit("tick", { symbol: "INFY" });
        source.emit("status", { status: "live" });
      });
      act(() => vi.advanceTimersByTime(250));
      expect([...result.current.ticks.keys()]).toEqual(["TCS"]);
      expect(result.current.ticks.get("TCS")?.ltp).toBe(3500);
      expect(result.current.status).toBe("live");
    } finally {
      vi.useRealTimers();
    }
  });

  it("reports reconnecting while the source retries, and unavailable once the server keeps closing it", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();

      // EventSource's own retry (not closed): reconnecting, no hook-side retry.
      act(() => FakeEventSource.instances[0].fail(false));
      expect(result.current.status).toBe("reconnecting");

      // CLOSED errors 1 to MAX_CLOSED_RETRIES: each one schedules a retry, so the status is reconnecting.
      for (let i = 0; i < MAX_CLOSED_RETRIES; i++) {
        act(() => FakeEventSource.instances[i].fail(true));
        expect(result.current.status).toBe("reconnecting");
        act(() => vi.advanceTimersByTime(RECONNECT_MS));
        await settleSession();
      }

      // One more CLOSED with no event in between: the hook gives up.
      act(() => FakeEventSource.instances[MAX_CLOSED_RETRIES].fail(true));
      expect(result.current.status).toBe("unavailable");
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes the stream on unmount", async () => {
    const { unmount } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
    const source = await firstSource();

    unmount();

    expect(source.closed).toBe(true);
  });

  it("drops a silent stream after the stale window and opens a new one", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();
      act(() => FakeEventSource.instances[0].emit("status", { status: "live" }));
      expect(result.current.status).toBe("live");

      act(() => vi.advanceTimersByTime(35_000));
      expect(result.current.status).toBe("reconnecting");
      expect(FakeEventSource.instances[0].closed).toBe(true);

      act(() => vi.advanceTimersByTime(3_000));
      await settleSession();
      expect(FakeEventSource.instances).toHaveLength(2);
      expect(sessionFetchCount()).toBe(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the stream live while heartbeats arrive", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();
      const source = FakeEventSource.instances[0];
      act(() => source.emit("status", { status: "live" }));

      act(() => vi.advanceTimersByTime(20_000));
      act(() => source.emit("heartbeat", { ts: 1 }));
      act(() => vi.advanceTimersByTime(20_000));

      expect(result.current.status).toBe("live");
      expect(FakeEventSource.instances).toHaveLength(1);
      expect(source.closed).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("retries the session after a rejected fetch and opens the stream on the next try", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.mocked(fetch);
      fetchMock.mockRejectedValueOnce(new Error("network down"));
      const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();

      expect(result.current.status).toBe("reconnecting");
      expect(FakeEventSource.instances).toHaveLength(0);

      act(() => vi.advanceTimersByTime(RECONNECT_MS));
      await settleSession();

      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(FakeEventSource.instances).toHaveLength(1);
      expect(FakeEventSource.instances[0].url).toBe("/api/live/ticks?runId=r1&symbols=TCS");
    } finally {
      vi.useRealTimers();
    }
  });

  it("retries the session when it answers not ok, and opens the stream on the next try", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.mocked(fetch);
      fetchMock.mockResolvedValueOnce({ ok: false } as Response);
      const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();

      expect(result.current.status).toBe("reconnecting");
      expect(FakeEventSource.instances).toHaveLength(0);

      act(() => vi.advanceTimersByTime(RECONNECT_MS));
      await settleSession();

      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(FakeEventSource.instances).toHaveLength(1);
      expect(FakeEventSource.instances[0].url).toBe("/api/live/ticks?runId=r1&symbols=TCS");
    } finally {
      vi.useRealTimers();
    }
  });

  it("drops a session that resolves after unmount, and makes no further requests", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.mocked(fetch);
      let resolveSession!: (response: Response) => void;
      fetchMock.mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveSession = resolve;
          }),
      );
      const { unmount } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      expect(fetchMock).toHaveBeenCalledTimes(1);

      unmount();
      resolveSession(okSessionResponse());
      await settleSession();
      expect(FakeEventSource.instances).toHaveLength(0);

      act(() => vi.advanceTimersByTime(RECONNECT_MS));
      await settleSession();

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(FakeEventSource.instances).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not reconnect when unmounted during the reconnect delay", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.mocked(fetch);
      const { unmount } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();
      act(() => FakeEventSource.instances[0].fail(true));

      unmount();
      expect(vi.getTimerCount()).toBe(0);
      act(() => vi.advanceTimersByTime(RECONNECT_MS));
      await settleSession();

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(FakeEventSource.instances).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("ignores an error that arrives after unmount", async () => {
    vi.useFakeTimers();
    try {
      const { unmount } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();
      const source = FakeEventSource.instances[0];
      unmount();
      act(() => source.fail(true));
      expect(vi.getTimerCount()).toBe(0);
      act(() => vi.advanceTimersByTime(RECONNECT_MS));
      await settleSession();
      expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
      expect(FakeEventSource.instances).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("opens the stream for the new symbols when they change while the session is pending", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.mocked(fetch);
      let resolveSession!: (response: Response) => void;
      fetchMock.mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveSession = resolve;
          }),
      );
      const { rerender } = renderHook(
        ({ symbols }: { symbols: string[] }) => useLiveTicks({ runId: "r1", symbols, enabled: true }),
        { initialProps: { symbols: ["TCS"] } },
      );

      rerender({ symbols: ["INFY"] });
      resolveSession(okSessionResponse());
      await settleSession();

      expect(FakeEventSource.instances).toHaveLength(1);
      expect(FakeEventSource.instances[0].url).toContain("symbols=INFY");
      expect(FakeEventSource.instances[0].url).not.toContain("TCS");
    } finally {
      vi.useRealTimers();
    }
  });

  it("refreshes the session when the server closes the stream, then reconnects", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();

      act(() => FakeEventSource.instances[0].fail(true));
      expect(result.current.status).toBe("reconnecting");

      act(() => vi.advanceTimersByTime(RECONNECT_MS));
      await settleSession();

      expect(sessionFetchCount()).toBe(2);
      expect(FakeEventSource.instances).toHaveLength(2);

      act(() => FakeEventSource.instances[1].emit("status", { status: "live" }));
      expect(result.current.status).toBe("live");
    } finally {
      vi.useRealTimers();
    }
  });

  it("resets the closed count on any event, so recovered closes never reach unavailable", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();

      // First CLOSED, then recovery.
      act(() => FakeEventSource.instances[0].fail(true));
      act(() => vi.advanceTimersByTime(RECONNECT_MS));
      await settleSession();
      act(() => FakeEventSource.instances[1].emit("status", { status: "live" }));
      expect(result.current.status).toBe("live");

      // An event between closes resets the count.
      act(() => FakeEventSource.instances[1].emit("heartbeat", { ts: 1 }));

      // MAX_CLOSED_RETRIES more closes in a row, each followed by recovery. None of them is "unavailable".
      for (let i = 0; i < MAX_CLOSED_RETRIES; i++) {
        const current = FakeEventSource.instances[FakeEventSource.instances.length - 1];
        act(() => current.fail(true));
        expect(result.current.status).toBe("reconnecting");
        act(() => vi.advanceTimersByTime(RECONNECT_MS));
        await settleSession();
        expect(result.current.status).toBe("connecting");
      }
      expect(result.current.status).not.toBe("unavailable");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps retrying a rejected session until one succeeds, and opens exactly one stream", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.mocked(fetch);
      fetchMock.mockRejectedValueOnce(new Error("first")).mockRejectedValueOnce(new Error("second"));
      renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();

      act(() => vi.advanceTimersByTime(RECONNECT_MS));
      await settleSession();
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(FakeEventSource.instances).toHaveLength(0);

      act(() => vi.advanceTimersByTime(RECONNECT_MS));
      await settleSession();
      expect(fetchMock).toHaveBeenCalledTimes(3);
      expect(FakeEventSource.instances).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("retries when creating the EventSource throws once, and does not let the error escape", async () => {
    vi.useFakeTimers();
    try {
      let constructorCalls = 0;
      vi.stubGlobal("EventSource", function (url: string) {
        constructorCalls += 1;
        if (constructorCalls === 1) {
          throw new Error("EventSource unavailable");
        }
        return new FakeEventSource(url);
      });
      const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
      await settleSession();

      expect(result.current.status).toBe("reconnecting");
      expect(FakeEventSource.instances).toHaveLength(0);

      act(() => vi.advanceTimersByTime(RECONNECT_MS));
      await settleSession();

      expect(constructorCalls).toBe(2);
      expect(FakeEventSource.instances).toHaveLength(1);
      expect(FakeEventSource.instances[0].url).toBe("/api/live/ticks?runId=r1&symbols=TCS");
    } finally {
      vi.useRealTimers();
    }
  });
});
