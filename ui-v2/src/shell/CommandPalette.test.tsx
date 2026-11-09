import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CommandPalette, openCommandPalette } from "./CommandPalette";

const results = vi.hoisted(() => ({ fetchResults: vi.fn() }));

vi.mock("../api/results", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/results")>();
  return { ...actual, fetchResults: results.fetchResults };
});

const ROWS = [
  { symbol: "RELIANCE", company: "Reliance Industries Ltd" },
  { symbol: "RELAXO", company: "Relaxo Footwears Ltd" },
  { symbol: "RELIGARE", company: "Religare Enterprises Ltd" },
];

function page(rows: { symbol: string; company: string | null }[]) {
  return Promise.resolve({ results: rows, total: rows.length, page: 1, perPage: 8 });
}

function renderPalette(runId: string | null = "run-1", onOpenStock = vi.fn()) {
  render(
    <>
      <button type="button">Elsewhere</button>
      <CommandPalette runId={runId} onOpenStock={onOpenStock} />
    </>,
  );
  return { onOpenStock };
}

function pressCtrlK() {
  fireEvent.keyDown(window, { key: "k", ctrlKey: true });
}

function getInput() {
  return screen.getByRole("combobox", { name: "Symbol or company" });
}

describe("CommandPalette", () => {
  beforeEach(() => {
    results.fetchResults.mockReset();
    results.fetchResults.mockImplementation((_runId: string, query: { search?: string }) => {
      const needle = (query.search ?? "").toUpperCase();
      return page(ROWS.filter((row) => row.symbol.includes(needle) || (row.company ?? "").toUpperCase().includes(needle)));
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("is closed by default", () => {
    renderPalette();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens on Ctrl+K and moves focus into the input", () => {
    renderPalette();
    pressCtrlK();
    expect(screen.getByRole("dialog", { name: "Search symbols" })).toBeInTheDocument();
    expect(getInput()).toHaveFocus();
  });

  it("opens on Cmd+K (metaKey) and toggles closed on a second press", () => {
    renderPalette();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("ignores plain k and Ctrl+Shift+K", () => {
    renderPalette();
    fireEvent.keyDown(window, { key: "k" });
    fireEvent.keyDown(window, { key: "K", ctrlKey: true, shiftKey: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes on Escape and returns focus to the element focused before opening", () => {
    renderPalette();
    const elsewhere = screen.getByRole("button", { name: "Elsewhere" });
    elsewhere.focus();
    pressCtrlK();
    expect(getInput()).toHaveFocus();
    fireEvent.keyDown(getInput(), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(elsewhere).toHaveFocus();
  });

  it("opens from openCommandPalette and returns focus to the given trigger", () => {
    render(
      <>
        <button type="button">Trigger</button>
        <CommandPalette runId="run-1" onOpenStock={vi.fn()} />
      </>,
    );
    const trigger = screen.getByRole("button", { name: "Trigger" });
    trigger.focus();
    act(() => openCommandPalette({ returnFocusTo: trigger }));
    expect(getInput()).toHaveFocus();
    fireEvent.keyDown(getInput(), { key: "Escape" });
    expect(trigger).toHaveFocus();
  });

  it("filters the current run's symbols after typing (debounced)", async () => {
    renderPalette("run-42");
    pressCtrlK();
    fireEvent.change(getInput(), { target: { value: "rel" } });

    expect(await screen.findByRole("option", { name: /RELIANCE/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /RELAXO/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /RELIGARE/ })).toBeInTheDocument();
    expect(results.fetchResults).toHaveBeenLastCalledWith(
      "run-42",
      { search: "rel", perPage: 8 },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("matches company names as well as symbols", async () => {
    renderPalette();
    pressCtrlK();
    fireEvent.change(getInput(), { target: { value: "footwear" } });
    expect(await screen.findByRole("option", { name: /RELAXO/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /RELIANCE/ })).not.toBeInTheDocument();
  });

  it("shows a hint for an empty query without searching", () => {
    renderPalette();
    pressCtrlK();
    expect(screen.getByText("Type a symbol or company name.")).toBeInTheDocument();
    expect(results.fetchResults).not.toHaveBeenCalled();
  });

  it("shows an empty-result message when nothing matches", async () => {
    renderPalette();
    pressCtrlK();
    fireEvent.change(getInput(), { target: { value: "zzzz" } });
    expect(await screen.findByText("No symbols match “zzzz”.")).toBeInTheDocument();
  });

  it("explains when no run is loaded and does not search", () => {
    renderPalette(null);
    pressCtrlK();
    fireEvent.change(getInput(), { target: { value: "rel" } });
    expect(screen.getByText("No current run to search.")).toBeInTheDocument();
    expect(results.fetchResults).not.toHaveBeenCalled();
  });

  it("shows the error message when the search request fails", async () => {
    results.fetchResults.mockRejectedValueOnce(new Error("Could not reach the results service."));
    renderPalette();
    pressCtrlK();
    fireEvent.change(getInput(), { target: { value: "rel" } });
    expect(await screen.findByText("Could not reach the results service.")).toBeInTheDocument();
  });

  it("moves the highlight with arrow keys, wrapping at both ends", async () => {
    renderPalette();
    pressCtrlK();
    fireEvent.change(getInput(), { target: { value: "rel" } });
    await screen.findByRole("option", { name: /RELIANCE/ });

    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(getInput(), { key: "ArrowDown" });
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    expect(getInput()).toHaveAttribute("aria-activedescendant", options[1].id);

    fireEvent.keyDown(getInput(), { key: "ArrowDown" });
    fireEvent.keyDown(getInput(), { key: "ArrowDown" });
    expect(options[0]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(getInput(), { key: "ArrowUp" });
    expect(options[2]).toHaveAttribute("aria-selected", "true");
  });

  it("opens the highlighted symbol on Enter with its company and closes the palette", async () => {
    const onOpenStock = vi.fn();
    renderPalette("run-1", onOpenStock);
    pressCtrlK();
    fireEvent.change(getInput(), { target: { value: "rel" } });
    await screen.findByRole("option", { name: /RELIANCE/ });

    fireEvent.keyDown(getInput(), { key: "ArrowDown" });
    fireEvent.keyDown(getInput(), { key: "Enter" });

    expect(onOpenStock).toHaveBeenCalledTimes(1);
    expect(onOpenStock).toHaveBeenCalledWith("RELAXO", "Relaxo Footwears Ltd");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens a symbol on click", async () => {
    const onOpenStock = vi.fn();
    renderPalette("run-1", onOpenStock);
    pressCtrlK();
    fireEvent.change(getInput(), { target: { value: "rel" } });
    fireEvent.click(await screen.findByRole("option", { name: /RELIGARE/ }));
    expect(onOpenStock).toHaveBeenCalledWith("RELIGARE", "Religare Enterprises Ltd");
  });

  it("does nothing on Enter when there are no results", () => {
    const onOpenStock = vi.fn();
    renderPalette("run-1", onOpenStock);
    pressCtrlK();
    fireEvent.keyDown(getInput(), { key: "Enter" });
    expect(onOpenStock).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("keeps Tab inside the dialog on the input", () => {
    renderPalette();
    pressCtrlK();
    const event = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    getInput().dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(getInput()).toHaveFocus();
  });

  it("clears the query when reopened", async () => {
    vi.useRealTimers();
    renderPalette();
    pressCtrlK();
    fireEvent.change(getInput(), { target: { value: "rel" } });
    await waitFor(() => expect(results.fetchResults).toHaveBeenCalled());
    fireEvent.keyDown(getInput(), { key: "Escape" });
    pressCtrlK();
    expect(getInput()).toHaveValue("");
  });
});
