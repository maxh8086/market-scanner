import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WatchlistPanel } from "./WatchlistPanel";

const EMPTY_TEXT = "No symbols on the watchlist yet.";

describe("WatchlistPanel", () => {
  it("shows the heading and the empty state when there are no symbols", () => {
    render(<WatchlistPanel />);

    expect(screen.getByRole("heading", { name: "Watchlist" })).toBeInTheDocument();
    expect(screen.getByText(EMPTY_TEXT)).toBeInTheDocument();
  });

  it("lists each symbol and hides the empty state when symbols are passed", () => {
    render(<WatchlistPanel symbols={["RELIANCE", "TCS"]} />);

    const items = screen.getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(["RELIANCE", "TCS"]);
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
  });
});
