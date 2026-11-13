import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetCsrfTokenForTests, SESSION_URL } from "../api/session";
import { useLiveTicks } from "../live/useLiveTicks";
import { eodTicksFromResponse, WatchlistPanel } from "./WatchlistPanel";

const session = vi.hoisted(() => ({ status: "closed" as "open" | "closed" | "pre_open" }));

vi.mock("../lib/marketSession", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/marketSession")>();
  return {
    ...actual,
    getMarketSession: () => ({ status: session.status, lastCloseLabel: "Fri 6 Nov, 15:30 IST" }),
  };
});

vi.mock("../live/useLiveTicks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../live/useLiveTicks")>();
  return {
    ...actual,
    useLiveTicks: vi.fn(() => ({ ticks: new Map(), status: "idle" })),
  };
});

const EOD_BODY = {
  indices: [{ name: "NIFTY 50", date: "2026-11-06", close: 25100.5, prevClose: 25000 }],
};

/** Answers GET /api/session with a test token and sends every other URL to impl. */
function stubFetch(impl: () => Promise<unknown>) {
  const fetchMock = vi.fn(async (url: string) =>
    url === SESSION_URL ? { ok: true, json: async () => ({ csrfToken: "test-csrf" }) } : impl(),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function rowFor(name: string): HTMLElement {
  const table = screen.getByRole("table");
  const header = within(table)
    .getAllByRole("rowheader")
    .find((th) => th.textContent?.startsWith(name));
  if (!header) throw new Error(`no row for ${name}`);
  return header.closest("tr") as HTMLElement;
}

beforeEach(() => {
  resetCsrfTokenForTests();
  session.status = "closed";
  vi.mocked(useLiveTicks).mockClear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("WatchlistPanel end-of-day fallback", () => {
  it("shows the last stored close and change when the market is closed", async () => {
    const fetchMock = stubFetch(async () => ({ ok: true, json: async () => EOD_BODY }));
    render(<WatchlistPanel />);

    await waitFor(() => expect(rowFor("NIFTY 50")).toHaveTextContent("25,100.50"));
    const row = rowFor("NIFTY 50");
    expect(row).toHaveTextContent("+100.50");
    expect(row).toHaveTextContent("+0.40%");
    expect(fetchMock).toHaveBeenCalledWith("/api/index-eod", expect.objectContaining({ signal: expect.anything() }));
  });

  it("keeps the live feed off while the market is closed", async () => {
    stubFetch(async () => ({ ok: true, json: async () => EOD_BODY }));
    render(<WatchlistPanel />);

    const calls = vi.mocked(useLiveTicks).mock.calls;
    expect(calls[calls.length - 1]?.[0]).toMatchObject({ enabled: false, indices: true });
  });

  it("uses live ticks and skips the EOD values while the market is open", async () => {
    session.status = "open";
    stubFetch(async () => ({ ok: true, json: async () => EOD_BODY }));
    render(<WatchlistPanel />);

    const calls = vi.mocked(useLiveTicks).mock.calls;
    expect(calls[calls.length - 1]?.[0]).toMatchObject({ enabled: true, indices: true });
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(rowFor("NIFTY 50")).not.toHaveTextContent("25,100.50");
  });

  it("shows a dash and does not crash when the EOD request fails", async () => {
    stubFetch(async () => {
      throw new TypeError("network down");
    });
    render(<WatchlistPanel />);

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(rowFor("NIFTY 50")).toHaveTextContent("—");
    expect(screen.getByRole("heading", { name: "Market Watch" })).toBeInTheDocument();
  });
});

describe("eodTicksFromResponse", () => {
  it("maps close to ltp, previous close to cp, and open, high and low, and drops rows without a close", () => {
    const ticks = eodTicksFromResponse({
      indices: [
        { name: "NIFTY BANK", date: "2026-11-06", open: 56100, high: 56300, low: 55900, close: 56000, prevClose: null },
        { name: "SENSEX", date: "2026-11-06", open: null, high: null, low: null, close: null, prevClose: 81000 },
      ],
    });
    expect(ticks.get("NIFTY BANK")).toEqual({
      symbol: "NIFTY BANK", ltp: 56000, ltt: null, cp: null, open: 56100, high: 56300, low: 55900,
    });
    expect(ticks.has("SENSEX")).toBe(false);
  });

  it("returns an empty map for a body without indices", () => {
    expect(eodTicksFromResponse({}).size).toBe(0);
    expect(eodTicksFromResponse(null).size).toBe(0);
  });
});
