import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildLiveTicksUrl, mapFeedStatus, useLiveTicks } from "./useLiveTicks";

type Listener = (event: { data: string }) => void;

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

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildLiveTicksUrl", () => {
  it("encodes the run id and comma-joins the symbols", () => {
    expect(buildLiveTicksUrl("run 1", ["TCS", "INFY"])).toBe("/api/live/ticks?runId=run+1&symbols=TCS%2CINFY");
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

  it("opens a stream for the run and symbols, then reports live from the status event", () => {
    const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS", "INFY"], enabled: true }));

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/live/ticks?runId=r1&symbols=TCS%2CINFY");
    expect(result.current.status).toBe("connecting");

    act(() => FakeEventSource.instances[0].emit("status", { status: "live" }));
    expect(result.current.status).toBe("live");
  });

  it("applies ticks by symbol after the batching window", async () => {
    const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
    const source = FakeEventSource.instances[0];

    act(() => source.emit("tick", { symbol: "TCS", ltp: 3500, ltt: null, cp: 3480 }));

    await waitFor(() => expect(result.current.ticks.get("TCS")?.ltp).toBe(3500));
  });

  it("ignores malformed tick data", async () => {
    const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
    const source = FakeEventSource.instances[0];

    act(() => {
      source.emit("tick", { symbol: 42, ltp: "x" });
      source.emit("status", { status: "live" });
    });

    expect(result.current.ticks.size).toBe(0);
    expect(result.current.status).toBe("live");
  });

  it("reports reconnecting while the source retries, and unavailable once the server closes it", () => {
    const { result } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
    const source = FakeEventSource.instances[0];

    act(() => source.fail(false));
    expect(result.current.status).toBe("reconnecting");

    act(() => source.fail(true));
    expect(result.current.status).toBe("unavailable");
  });

  it("closes the stream on unmount", () => {
    const { unmount } = renderHook(() => useLiveTicks({ runId: "r1", symbols: ["TCS"], enabled: true }));
    const source = FakeEventSource.instances[0];

    unmount();

    expect(source.closed).toBe(true);
  });
});
