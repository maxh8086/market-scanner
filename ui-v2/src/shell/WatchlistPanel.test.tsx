import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { indexChange, WatchlistPanel } from "./WatchlistPanel";
import { addCustomSymbol, DEFAULT_INDICES, normalizeSymbol } from "./watchlistStore";

const STORAGE_KEY = "marketScanner.customWatchlist";

beforeEach(() => window.localStorage.clear());
afterEach(() => window.localStorage.clear());

function addSymbol(text: string) {
  const input = screen.getByLabelText("Add a stock or index");
  fireEvent.change(input, { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
}

describe("WatchlistPanel", () => {
  it("shows the default index table with LTP, change points and change percent columns", () => {
    render(<WatchlistPanel />);

    expect(screen.getByRole("heading", { name: "Market Watch" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Price" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Chg" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Chg %" })).toBeInTheDocument();
    const rowNames = within(table).getAllByRole("rowheader").map((th) => th.textContent?.split("O ")[0]);
    expect(rowNames).toEqual(DEFAULT_INDICES);
    expect(screen.getByText("No custom symbols yet.")).toBeInTheDocument();
  });

  it("switches the table rows when another index segment is chosen", () => {
    render(<WatchlistPanel />);
    const select = screen.getByLabelText("Index segment");

    fireEvent.change(select, { target: { value: "Sectoral Indices" } });
    const table = screen.getByRole("table");
    let names = within(table).getAllByRole("rowheader").map((th) => th.textContent?.split("O ")[0]);
    expect(names).toContain("NIFTY BANK");
    expect(names).not.toContain("SENSEX");

    fireEvent.change(select, { target: { value: "All Indices" } });
    names = within(screen.getByRole("table")).getAllByRole("rowheader").map((th) => th.textContent?.split("O ")[0]);
    expect(names).toContain("SENSEX");
    expect(names).toContain("NIFTY BANK");
    expect(new Set(names).size).toBe(names.length);
  });

  it("computes change points and percent from the last price and previous close", () => {
    const change = indexChange(25008.5, 24986.4);
    expect(change.points).toBeCloseTo(22.1, 6);
    expect(change.percent).toBeCloseTo(0.0884, 3);
    expect(indexChange(null, 100)).toEqual({ points: null, percent: null });
    expect(indexChange(100, 0)).toEqual({ points: null, percent: null });
  });

  it("adds a custom symbol, upper-cases it and saves it locally", () => {
    render(<WatchlistPanel />);

    addSymbol("  reliance ");

    expect(screen.getByRole("button", { name: "Remove RELIANCE" })).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]")).toEqual(["RELIANCE"]);
  });

  it("removes a custom symbol", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(["TCS"]));
    render(<WatchlistPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Remove TCS" }));

    expect(screen.queryByRole("button", { name: "Remove TCS" })).not.toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]")).toEqual([]);
  });

  it("shows an error and adds nothing for an invalid or duplicate symbol", () => {
    render(<WatchlistPanel />);

    addSymbol("<script>");
    expect(screen.getByText(/Use letters, digits/)).toBeInTheDocument();

    addSymbol("sensex");
    expect(screen.getByText("SENSEX is already in the index list.")).toBeInTheDocument();
    expect(screen.getByText("No custom symbols yet.")).toBeInTheDocument();
  });

  it("ignores a stored list that is not valid JSON", () => {
    window.localStorage.setItem(STORAGE_KEY, "{not json");
    render(<WatchlistPanel />);

    expect(screen.getByText("No custom symbols yet.")).toBeInTheDocument();
  });
});

describe("watchlistStore", () => {
  it("normalizes symbols and rejects unsafe text", () => {
    expect(normalizeSymbol("  nifty  bank ")).toBe("NIFTY BANK");
    expect(normalizeSymbol("a/b")).toBeNull();
    expect(normalizeSymbol("")).toBeNull();
  });

  it("refuses a duplicate of a custom symbol", () => {
    const first = addCustomSymbol([], "TCS");
    const second = addCustomSymbol(first.symbols, "tcs");
    expect(second.error).toBe("TCS is already on your watchlist.");
    expect(second.symbols).toEqual(["TCS"]);
  });
});
