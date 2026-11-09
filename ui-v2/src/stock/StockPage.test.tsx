import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StockPage } from "./StockPage";

const chart = {
  addSeries: vi.fn(() => ({ setData: vi.fn() })),
  applyOptions: vi.fn(),
  timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
  remove: vi.fn(),
};

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: { type: "Candlestick" },
  ColorType: { Solid: "solid" },
  createChart: vi.fn(() => chart),
}));

const CANDLES = {
  symbol: "RELIANCE",
  candles: [
    { date: "2026-11-05", open: 100, high: 103, low: 99, close: 100, volume: 900 },
    { date: "2026-11-06", open: 100, high: 105, low: 99, close: 102, volume: 1000 },
    { date: "2026-11-09", open: 102, high: 106, low: 101, close: 104, volume: 1100 },
  ],
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 800 });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("StockPage", () => {
  it("renders the symbol, company, latest close and change arrow from the candles", async () => {
    const fetchMock = vi.fn(async (_url: string) => jsonResponse(CANDLES));
    vi.stubGlobal("fetch", fetchMock);

    render(<StockPage symbol="RELIANCE" company="Reliance Industries" />);

    expect(screen.getByRole("heading", { name: "RELIANCE" })).toBeInTheDocument();
    expect(screen.getByText("Reliance Industries")).toBeInTheDocument();
    expect(await screen.findByText("₹104.00")).toBeInTheDocument();
    expect(screen.getByText("▲ +1.96%")).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/stocks/RELIANCE/candles?limit=500");
  });

  it("creates the chart with a candlestick series and feeds it the candles", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(CANDLES)));

    render(<StockPage symbol="RELIANCE" company="Reliance Industries" />);

    await screen.findByText("₹104.00");
    expect(chart.addSeries).toHaveBeenCalledWith({ type: "Candlestick" }, expect.any(Object));
    const series = chart.addSeries.mock.results[0].value as { setData: ReturnType<typeof vi.fn> };
    expect(series.setData).toHaveBeenCalledWith(
      expect.arrayContaining([expect.objectContaining({ time: "2026-11-09", close: 104 })]),
    );
  });

  it("shows the error message when the candles request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "Candles are unavailable." }, 500)));

    render(<StockPage symbol="RELIANCE" company="Reliance Industries" />);

    expect(await screen.findByRole("alert")).toHaveAttribute("data-state", "error");
    expect(screen.getByText("Candles are unavailable.")).toBeInTheDocument();
  });

  it("renders the placeholder sections as not available", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(CANDLES)));

    render(<StockPage symbol="RELIANCE" company="Reliance Industries" />);

    await screen.findByText("₹104.00");
    for (const title of ["Announcements", "Fundamentals", "Concall summaries", "Order book", "Guidelines"]) {
      expect(screen.getByRole("region", { name: title })).toBeInTheDocument();
    }
    expect(screen.getAllByText("Not available yet")).toHaveLength(5);
  });
});
