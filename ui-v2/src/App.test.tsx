import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const RUN = { runId: "run-42", runDate: "2026-11-09" };

const FILTER_OPTIONS = { bucket: ["A", "B"], stance: ["Buy"] };

const ROW = {
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
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** Routes the API calls the Home screen makes. */
function routeFetch(latest: Response | Error, filterOptions: Response | Error = jsonResponse(FILTER_OPTIONS)) {
  return vi.fn(async (url: string) => {
    if (url === "/api/runs/latest") {
      if (latest instanceof Error) {
        throw latest;
      }
      return latest;
    }
    if (url === "/api/runs/run-42/filter-options") {
      if (filterOptions instanceof Error) {
        throw filterOptions;
      }
      return filterOptions;
    }
    if (url.startsWith("/api/runs/run-42/results")) {
      return jsonResponse({ results: [ROW], total: 1, page: 1, perPage: 50 });
    }
    if (url === "/api/presets") {
      return jsonResponse({ presets: [] });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
}

beforeEach(() => {
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

describe("App Home screen", () => {
  it("shows a loading state while the latest run is requested", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    render(<App />);

    expect(screen.getByRole("status")).toHaveAttribute("data-state", "loading");
  });

  it("mounts the scan table for the latest run and shows its date", async () => {
    const fetchMock = routeFetch(jsonResponse(RUN));
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText("Run date: 2026-11-09")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "RELIANCE" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(
      expect.arrayContaining([
        "/api/runs/latest",
        expect.stringMatching(/^\/api\/runs\/run-42\/results/),
      ]),
    );
  });

  it("offers the bucket values from the filter options endpoint", async () => {
    const fetchMock = routeFetch(jsonResponse(RUN));
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    const bucket = await screen.findByRole("combobox", { name: "Bucket" });
    await waitFor(() => expect(within(bucket).getByRole("option", { name: "A" })).toBeInTheDocument());
    expect(within(bucket).getByRole("option", { name: "B" })).toBeInTheDocument();
    expect(within(bucket).getByRole("option", { name: "All" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.map((call) => call[0])).toContain("/api/runs/run-42/filter-options");
  });

  it("still renders the table with only All in the dropdowns when filter options fail", async () => {
    const fetchMock = routeFetch(jsonResponse(RUN), jsonResponse({ error: "boom" }, 500));
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByRole("button", { name: "RELIANCE" })).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock.mock.calls.map((call) => call[0])).toContain("/api/runs/run-42/filter-options"),
    );
    const bucket = screen.getByRole("combobox", { name: "Bucket" });
    await waitFor(() => expect(within(bucket).getAllByRole("option")).toHaveLength(1));
    expect(within(bucket).getByRole("option", { name: "All" })).toBeInTheDocument();
  });

  it("shows the empty state when there is no current run", async () => {
    vi.stubGlobal("fetch", routeFetch(jsonResponse({ error: "no run" }, 404)));

    render(<App />);

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveAttribute("data-state", "empty"),
    );
    expect(screen.getByText("No current run.")).toBeInTheDocument();
  });

  it("shows the error state when the latest run request fails", async () => {
    vi.stubGlobal("fetch", routeFetch(new TypeError("Failed to fetch")));

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveAttribute("data-state", "error");
    expect(screen.getByText("Could not reach the run service.")).toBeInTheDocument();
  });
});
