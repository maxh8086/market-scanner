import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function lastUrl(fetchMock: ReturnType<typeof vi.fn>): string {
  return fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0] as string;
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
    expect(onOpenStock).toHaveBeenNthCalledWith(1, "RELIANCE");
    expect(onOpenStock).toHaveBeenNthCalledWith(2, "RELIANCE");
    expect(onOpenStock).toHaveBeenNthCalledWith(3, "RELIANCE");
  });

  it("removes a column when its visibility toggle is unchecked", async () => {
    render(<ScreenerTable runId={RUN_ID} />);
    await screen.findByRole("button", { name: "RELIANCE" });
    expect(screen.getByRole("columnheader", { name: "Company" })).toBeInTheDocument();

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

  it("shows the no-run message when runId is empty and does not fetch", () => {
    render(<ScreenerTable runId="" />);

    expect(screen.getByText("No run selected.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
