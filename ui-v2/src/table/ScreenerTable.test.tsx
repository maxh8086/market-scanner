import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Row } from "../api/results";
import { ScreenerTable } from "./ScreenerTable";

const RUN_ID = "2026-11-09";

const ROWS: Row[] = [
  {
    symbol: "RELIANCE",
    company: "Reliance Industries",
    industry: "Oil & Gas",
    ltp: 2950.5,
    distance_pct: -4.2,
    ath_date: "2026-08-01",
    one_year_return_pct: 12.3,
    order_pct_of_sales: null,
    stance: "Watch",
    bucket: "A",
    changed: false,
  },
  {
    symbol: "TCS",
    company: "Tata Consultancy Services",
    industry: "IT",
    ltp: 3800,
    distance_pct: 1.5,
    ath_date: "2026-07-15",
    one_year_return_pct: -0.87,
    order_pct_of_sales: null,
    stance: "Buy",
    bucket: "B",
    changed: true,
  },
];

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function pageBody(results: Row[]) {
  return { results, total: results.length, page: 1, perPage: 50 };
}

/** URLs of the results requests only. The sparkline closes requests are left out. */
function resultsUrls(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map((call) => call[0] as string).filter((url) => url.includes("/results"));
}

function lastUrl(fetchMock: ReturnType<typeof vi.fn>): string {
  const urls = resultsUrls(fetchMock);
  return urls[urls.length - 1];
}

/** Table row that holds the given symbol's button. */
function rowFor(symbol: string): HTMLElement {
  const row = screen.getByRole("button", { name: symbol }).closest("tr");
  if (!row) {
    throw new Error(`No row for ${symbol}`);
  }
  return row;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue(jsonResponse(pageBody(ROWS)));
  vi.stubGlobal("fetch", fetchMock);
  // jsdom has no layout. Give elements a height so the row virtualizer renders rows.
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    bottom: 600,
    right: 800,
    width: 800,
    height: 600,
    toJSON: () => ({}),
  } as DOMRect);
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 600 });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 800 });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ScreenerTable", () => {
  it("renders rows from the results API", async () => {
    render(<ScreenerTable runId={RUN_ID} />);

    expect(await screen.findByRole("button", { name: "RELIANCE" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "TCS" })).toBeInTheDocument();
    expect(lastUrl(fetchMock)).toBe(`/api/runs/${RUN_ID}/results?page=1&perPage=50`);
    expect(screen.getByText("Showing 2 of 2")).toBeInTheDocument();
  });

  it("sends the sort column and order to the API when a header is clicked", async () => {
    render(<ScreenerTable runId={RUN_ID} />);
    await screen.findByRole("button", { name: "RELIANCE" });

    fireEvent.click(screen.getByRole("button", { name: "1Y return" }));
    await waitFor(() =>
      expect(lastUrl(fetchMock)).toBe(
        `/api/runs/${RUN_ID}/results?page=1&perPage=50&sort=one_year_return_pct&order=asc`,
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "1Y return" }));
    await waitFor(() =>
      expect(lastUrl(fetchMock)).toBe(
        `/api/runs/${RUN_ID}/results?page=1&perPage=50&sort=one_year_return_pct&order=desc`,
      ),
    );
    expect(screen.getByRole("columnheader", { name: /1Y return/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  it("does not offer sorting on the sector column", async () => {
    render(<ScreenerTable runId={RUN_ID} />);
    await screen.findByRole("button", { name: "RELIANCE" });

    expect(screen.queryByRole("button", { name: "Sector" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Sector" })).not.toHaveAttribute("aria-sort");
  });

  it("calls onOpenStock on Enter and Space from the symbol control", async () => {
    const onOpenStock = vi.fn();
    render(<ScreenerTable runId={RUN_ID} onOpenStock={onOpenStock} />);
    const symbol = await screen.findByRole("button", { name: "RELIANCE" });

    fireEvent.keyDown(symbol, { key: "Enter" });
    fireEvent.keyDown(symbol, { key: " " });
    fireEvent.click(symbol);

    expect(onOpenStock).toHaveBeenCalledTimes(3);
    expect(onOpenStock).toHaveBeenNthCalledWith(1, "RELIANCE", "Reliance Industries");
    expect(onOpenStock).toHaveBeenNthCalledWith(2, "RELIANCE", "Reliance Industries");
    expect(onOpenStock).toHaveBeenNthCalledWith(3, "RELIANCE", "Reliance Industries");
  });

  it("opens the stock when a focused row gets Enter or Space, and ignores other keys", async () => {
    const onOpenStock = vi.fn();
    render(<ScreenerTable runId={RUN_ID} onOpenStock={onOpenStock} />);
    await screen.findByRole("button", { name: "RELIANCE" });
    const row = rowFor("RELIANCE");
    expect(row).toHaveAttribute("tabindex", "0");

    fireEvent.keyDown(row, { key: "a" });
    expect(onOpenStock).not.toHaveBeenCalled();

    fireEvent.keyDown(row, { key: "Enter" });
    fireEvent.keyDown(row, { key: " " });

    expect(onOpenStock).toHaveBeenCalledTimes(2);
    expect(onOpenStock).toHaveBeenNthCalledWith(1, "RELIANCE", "Reliance Industries");
    expect(onOpenStock).toHaveBeenNthCalledWith(2, "RELIANCE", "Reliance Industries");
  });

  it("does not open the stock twice when Enter is pressed on the symbol inside the row", async () => {
    const onOpenStock = vi.fn();
    render(<ScreenerTable runId={RUN_ID} onOpenStock={onOpenStock} />);
    const symbol = await screen.findByRole("button", { name: "TCS" });

    fireEvent.keyDown(symbol, { key: "Enter" });

    expect(onOpenStock).toHaveBeenCalledTimes(1);
    expect(onOpenStock).toHaveBeenCalledWith("TCS", "Tata Consultancy Services");
  });

  it("draws a sparkline per row from one recent-closes request, and a dash with Not available when there are no closes", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url.startsWith("/api/recent-closes")
        ? jsonResponse({ closes: { RELIANCE: [2800, 2900, 2950.5] } })
        : jsonResponse(pageBody(ROWS)),
    );
    render(<ScreenerTable runId={RUN_ID} />);
    await screen.findByRole("button", { name: "RELIANCE" });

    const closesCalls = fetchMock.mock.calls
      .map((call) => call[0] as string)
      .filter((url) => url.startsWith("/api/recent-closes"));
    expect(closesCalls).toEqual(["/api/recent-closes?symbols=RELIANCE%2CTCS&limit=30"]);

    const reliance = await within(rowFor("RELIANCE")).findByRole("img", {
      name: "Trend rising over the last 3 closes",
    });
    expect(reliance.tagName.toLowerCase()).toBe("svg");
    expect(reliance).toHaveAttribute("data-sparkline", "up");

    const tcsDash = within(rowFor("TCS")).getByTitle("Not available");
    expect(tcsDash).toHaveTextContent("—");
  });

  it("keeps the table usable when the recent-closes request fails", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url.startsWith("/api/recent-closes") ? jsonResponse({ error: "down" }, 500) : jsonResponse(pageBody(ROWS)),
    );
    render(<ScreenerTable runId={RUN_ID} />);

    expect(await screen.findByRole("button", { name: "RELIANCE" })).toBeInTheDocument();
    expect(within(rowFor("RELIANCE")).getAllByTitle("Not available")).not.toHaveLength(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("removes a column when its visibility toggle is unchecked", async () => {
    render(<ScreenerTable runId={RUN_ID} />);
    await screen.findByRole("button", { name: "RELIANCE" });
    expect(screen.getByRole("columnheader", { name: "Company" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add or remove columns" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Company" }));

    expect(screen.queryByRole("columnheader", { name: "Company" })).not.toBeInTheDocument();
    expect(screen.queryByText("Reliance Industries")).not.toBeInTheDocument();
  });

  it("shows a sign and arrow for negative and positive returns", async () => {
    render(<ScreenerTable runId={RUN_ID} />);
    await screen.findByRole("button", { name: "RELIANCE" });

    expect(screen.getByText("▲ +12.30%")).toBeInTheDocument();
    expect(screen.getByText("▼ −0.87%")).toBeInTheDocument();
    expect(screen.getByText("▼ −4.20%")).toBeInTheDocument();
    expect(screen.getByText("▲ +1.50%")).toBeInTheDocument();
  });

  it("shows the empty state when the run has no rows", async () => {
    fetchMock.mockResolvedValue(jsonResponse(pageBody([])));
    render(<ScreenerTable runId={RUN_ID} />);

    expect(await screen.findByText("No results for this run.")).toBeInTheDocument();
  });

  it("shows the API error message when the request fails", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "Run not found" }, 404));
    render(<ScreenerTable runId={RUN_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Run not found");
  });

  it("offers Clear filters in the no-results state and calls the handler", async () => {
    fetchMock.mockResolvedValue(jsonResponse(pageBody([])));
    const onClearFilters = vi.fn();
    render(<ScreenerTable runId={RUN_ID} filters={{ bucket: "A" }} onClearFilters={onClearFilters} />);

    expect(await screen.findByText("No results match these filters.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(onClearFilters).toHaveBeenCalledTimes(1);
  });

  it("retries the results request when Retry is clicked after an error", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "Database offline" }, 500));
    render(<ScreenerTable runId={RUN_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Database offline");
    expect(resultsUrls(fetchMock)).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("button", { name: "RELIANCE" })).toBeInTheDocument();
    expect(resultsUrls(fetchMock)).toHaveLength(2);
    expect(lastUrl(fetchMock)).toBe(`/api/runs/${RUN_ID}/results?page=1&perPage=50`);
  });

  it("shows the no-run message when runId is empty and does not fetch", () => {
    render(<ScreenerTable runId="" />);

    expect(screen.getByText("No run selected.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  describe("live prices", () => {
    type Listener = (event: { data: unknown }) => void;

    class FakeEventSource {
      static CLOSED = 2;
      static instances: FakeEventSource[] = [];

      readyState = 0;
      onerror: (() => void) | null = null;
      readonly url: string;
      private listeners = new Map<string, Listener[]>();

      constructor(url: string) {
        this.url = url;
        FakeEventSource.instances.push(this);
      }

      addEventListener(type: string, listener: Listener): void {
        const existing = this.listeners.get(type) ?? [];
        this.listeners.set(type, [...existing, listener]);
      }

      close(): void {
        this.readyState = FakeEventSource.CLOSED;
      }

      emit(type: string, body: unknown): void {
        for (const listener of this.listeners.get(type) ?? []) {
          listener({ data: JSON.stringify(body) });
        }
      }
    }

    function latestSource(): FakeEventSource {
      const source = FakeEventSource.instances[FakeEventSource.instances.length - 1];
      if (!source) {
        throw new Error("No EventSource was created.");
      }
      return source;
    }

    /** Answers matchMedia for the reduced-motion query only. */
    function stubReducedMotion(reduce: boolean): void {
      Object.defineProperty(window, "matchMedia", {
        configurable: true,
        writable: true,
        value: (query: string) => ({
          matches: reduce && query === "(prefers-reduced-motion: reduce)",
          media: query,
          onchange: null,
          addEventListener: () => {},
          removeEventListener: () => {},
          addListener: () => {},
          removeListener: () => {},
          dispatchEvent: () => false,
        }),
      });
    }

    beforeEach(() => {
      FakeEventSource.instances = [];
      vi.stubGlobal("EventSource", FakeEventSource);
    });

    afterEach(() => {
      FakeEventSource.instances = [];
      vi.unstubAllGlobals();
      Reflect.deleteProperty(window, "matchMedia");
    });

    it("does not open a live stream when the live prop is off", async () => {
      render(<ScreenerTable runId={RUN_ID} />);
      await screen.findByRole("button", { name: "RELIANCE" });

      expect(FakeEventSource.instances).toHaveLength(0);
      expect(screen.queryByText(/Live prices/)).not.toBeInTheDocument();
    });

    it("opens the live stream for the loaded rows and shows Live prices after a live status", async () => {
      render(<ScreenerTable runId={RUN_ID} live />);
      await screen.findByRole("button", { name: "RELIANCE" });

      expect(FakeEventSource.instances).toHaveLength(1);
      expect(latestSource().url.startsWith("/api/live/ticks?runId=")).toBe(true);

      act(() => latestSource().emit("status", { status: "live" }));

      expect(screen.getByText(/Live prices/)).toBeInTheDocument();
      expect(screen.queryByText(/unavailable/)).not.toBeInTheDocument();
    });

    it("updates the LTP for a row when a tick arrives and flashes the changed price", async () => {
      render(<ScreenerTable runId={RUN_ID} live />);
      await screen.findByRole("button", { name: "RELIANCE" });
      expect(screen.getByText("₹2,950.50")).toBeInTheDocument();

      act(() =>
        latestSource().emit("tick", { symbol: "RELIANCE", ltp: 2960.25, ltt: null, cp: null }),
      );

      const priceCell = await waitFor(() => {
        const cell = screen.getByText("₹2,960.25");
        expect(cell).toHaveAttribute("data-flash", "up");
        return cell;
      });
      expect(priceCell.tagName).toBe("SPAN");
      expect(screen.queryByText("₹2,950.50")).not.toBeInTheDocument();
    });

    it("keeps the tint and draws no bar when motion is allowed", async () => {
      stubReducedMotion(false);
      render(<ScreenerTable runId={RUN_ID} live />);
      await screen.findByRole("button", { name: "RELIANCE" });

      act(() =>
        latestSource().emit("tick", { symbol: "RELIANCE", ltp: 2960.25, ltt: null, cp: null }),
      );

      const priceCell = await waitFor(() => {
        const cell = screen.getByText("₹2,960.25");
        expect(cell).toHaveAttribute("data-flash", "up");
        return cell;
      });
      expect(priceCell).toHaveClass("bg-gain/15");
      expect(priceCell).not.toHaveAttribute("data-motion");
      expect(priceCell.querySelector("[data-change-bar]")).toBeNull();
    });

    it("replaces the flash with a static 2px bar in the gain colour under reduced motion", async () => {
      stubReducedMotion(true);
      render(<ScreenerTable runId={RUN_ID} live />);
      await screen.findByRole("button", { name: "RELIANCE" });

      act(() =>
        latestSource().emit("tick", { symbol: "RELIANCE", ltp: 2960.25, ltt: null, cp: null }),
      );

      const priceCell = await waitFor(() => {
        const cell = screen.getByText("₹2,960.25");
        expect(cell).toHaveAttribute("data-flash", "up");
        return cell;
      });
      expect(priceCell).toHaveAttribute("data-motion", "reduced");
      expect(priceCell).not.toHaveClass("bg-gain/15");
      const bar = priceCell.querySelector("[data-change-bar='up']");
      expect(bar).toHaveClass("absolute", "left-0", "w-[2px]", "bg-gain");
      expect(bar).toHaveAttribute("aria-hidden", "true");
    });

    it("uses the loss colour for the reduced-motion bar on a falling price", async () => {
      stubReducedMotion(true);
      render(<ScreenerTable runId={RUN_ID} live />);
      await screen.findByRole("button", { name: "RELIANCE" });

      act(() =>
        latestSource().emit("tick", { symbol: "RELIANCE", ltp: 2900, ltt: null, cp: null }),
      );

      const priceCell = await waitFor(() => {
        const cell = screen.getByText("₹2,900.00");
        expect(cell).toHaveAttribute("data-flash", "down");
        return cell;
      });
      expect(priceCell.querySelector("[data-change-bar='down']")).toHaveClass("bg-loss");
    });

    it("shows the day change from the live tick's previous close", async () => {
      render(<ScreenerTable runId={RUN_ID} live />);
      await screen.findByRole("button", { name: "RELIANCE" });
      expect(screen.getByRole("columnheader", { name: "Chg %" })).toBeInTheDocument();
      expect(screen.getByRole("columnheader", { name: "Chg" })).toBeInTheDocument();
      expect(screen.getAllByText("—").length).toBeGreaterThan(0);

      act(() =>
        latestSource().emit("tick", { symbol: "RELIANCE", ltp: 2950.5, ltt: null, cp: 2800 }),
      );

      // (2950.5 - 2800) / 2800 = 5.375%
      expect(await screen.findByText("▲ +5.38%")).toBeInTheDocument();
      expect(screen.getByText("▲ +150.50")).toBeInTheDocument();
    });

    it("shows the reconnecting state with the last saved prices message", async () => {
      render(<ScreenerTable runId={RUN_ID} live />);
      await screen.findByRole("button", { name: "RELIANCE" });

      act(() => latestSource().emit("status", { status: "reconnecting" }));

      const status = await screen.findByRole("status");
      expect(status).toHaveAttribute("data-state", "reconnecting");
      expect(status).toHaveTextContent("Live prices reconnecting. Showing the last saved prices.");
    });

    it("says Live prices unavailable when the feed is not configured", async () => {
      render(<ScreenerTable runId={RUN_ID} live />);
      await screen.findByRole("button", { name: "RELIANCE" });

      act(() => latestSource().emit("status", { status: "unconfigured" }));

      expect(await screen.findByText(/Live prices unavailable/)).toBeInTheDocument();
    });
  });
});
