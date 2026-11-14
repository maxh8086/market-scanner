import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CollectorStatusError, fetchCollectorStatus } from "../api/collectorStatus";
import { COLLECTOR_STATUS_POLL_MS, useCollectorStatus } from "./useCollectorStatus";

vi.mock("../api/collectorStatus", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/collectorStatus")>();
  return { ...actual, fetchCollectorStatus: vi.fn() };
});

const fetchMock = vi.mocked(fetchCollectorStatus);

const PAUSED = { paused: true, since: null };
const RUNNING = { paused: false, since: "2026-11-16T19:00:00.000+05:30" };

/** Lets the pending poll promise settle, then runs the timers that became due. */
async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function tick() {
  await act(async () => {
    vi.advanceTimersByTime(COLLECTOR_STATUS_POLL_MS);
  });
  await flush();
}

beforeEach(() => {
  vi.useFakeTimers();
  fetchMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useCollectorStatus", () => {
  it("starts with paused false before the first answer", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useCollectorStatus());
    expect(result.current.paused).toBe(false);
  });

  it("takes paused from the response", async () => {
    fetchMock.mockResolvedValue(PAUSED);
    const { result } = renderHook(() => useCollectorStatus());
    await flush();
    expect(result.current.paused).toBe(true);
  });

  it("sets paused after 3 consecutive failures, but not after 2", async () => {
    fetchMock.mockRejectedValue(new CollectorStatusError("down", null));
    const { result } = renderHook(() => useCollectorStatus());
    await flush();
    await tick();
    expect(result.current.paused).toBe(false);
    await tick();
    expect(result.current.paused).toBe(true);
  });

  it("counts 5xx responses as failures", async () => {
    fetchMock.mockRejectedValue(new CollectorStatusError("server error", 500));
    const { result } = renderHook(() => useCollectorStatus());
    await flush();
    await tick();
    await tick();
    expect(result.current.paused).toBe(true);
  });

  it("resets the failure count on a success", async () => {
    fetchMock
      .mockRejectedValueOnce(new CollectorStatusError("down", null))
      .mockRejectedValueOnce(new CollectorStatusError("down", null))
      .mockResolvedValueOnce(RUNNING)
      .mockRejectedValueOnce(new CollectorStatusError("down", null))
      .mockRejectedValueOnce(new CollectorStatusError("down", null));
    const { result } = renderHook(() => useCollectorStatus());
    await flush();
    await tick();
    await tick();
    expect(result.current.paused).toBe(false);
    await tick();
    await tick();
    expect(result.current.paused).toBe(false);
  });

  it("keeps the last value on a 4xx other than 404", async () => {
    fetchMock.mockResolvedValueOnce(PAUSED).mockRejectedValue(new CollectorStatusError("unauthorized", 401));
    const { result } = renderHook(() => useCollectorStatus());
    await flush();
    expect(result.current.paused).toBe(true);
    await tick();
    await tick();
    await tick();
    expect(result.current.paused).toBe(true);
  });

  it("stops polling on 404 and keeps paused false", async () => {
    fetchMock.mockRejectedValue(new CollectorStatusError("not found", 404));
    const { result } = renderHook(() => useCollectorStatus());
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await tick();
    await tick();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.paused).toBe(false);
  });

  it("aborts the in-flight request on unmount and polls no more", async () => {
    let captured: AbortSignal | undefined;
    fetchMock.mockImplementation(
      (options) =>
        new Promise((_resolve, reject) => {
          captured = options?.signal ?? undefined;
          captured?.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
        }),
    );
    const { unmount } = renderHook(() => useCollectorStatus());
    expect(captured?.aborted).toBe(false);
    unmount();
    expect(captured?.aborted).toBe(true);
    await tick();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
