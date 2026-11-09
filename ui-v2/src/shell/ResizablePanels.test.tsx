import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResizablePanels } from "./ResizablePanels";

const STORAGE_KEY = "ms-watchlist-width";

function renderPanels() {
  return render(
    <ResizablePanels left={<p>Left panel</p>}>
      <p>Main area</p>
    </ResizablePanels>,
  );
}

function getSeparator() {
  return screen.getByRole("separator", { name: "Resize watchlist panel" });
}

function currentWidth() {
  return Number(getSeparator().getAttribute("aria-valuenow"));
}

describe("ResizablePanels", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a vertical separator with the default width and limits", () => {
    renderPanels();

    const separator = getSeparator();
    expect(separator).toHaveAttribute("aria-orientation", "vertical");
    expect(separator).toHaveAttribute("aria-valuenow", "240");
    expect(separator).toHaveAttribute("aria-valuemin", "200");
    expect(separator).toHaveAttribute("aria-valuemax", "480");
  });

  it("ArrowRight adds 16px and ArrowLeft removes 16px", () => {
    renderPanels();

    fireEvent.keyDown(getSeparator(), { key: "ArrowRight" });
    expect(currentWidth()).toBe(256);

    fireEvent.keyDown(getSeparator(), { key: "ArrowLeft" });
    fireEvent.keyDown(getSeparator(), { key: "ArrowLeft" });
    expect(currentWidth()).toBe(224);
  });

  it("never goes below 200 or above 480", () => {
    renderPanels();

    for (let i = 0; i < 10; i += 1) {
      fireEvent.keyDown(getSeparator(), { key: "ArrowLeft" });
    }
    expect(currentWidth()).toBe(200);

    for (let i = 0; i < 30; i += 1) {
      fireEvent.keyDown(getSeparator(), { key: "ArrowRight" });
    }
    expect(currentWidth()).toBe(480);
  });

  it("saves the width to localStorage on change", () => {
    renderPanels();

    fireEvent.keyDown(getSeparator(), { key: "ArrowRight" });
    expect(localStorage.getItem(STORAGE_KEY)).toBe("256");
  });

  it("uses a stored width on mount", () => {
    localStorage.setItem(STORAGE_KEY, "320");
    renderPanels();

    expect(currentWidth()).toBe(320);
  });

  it("falls back to the default when the stored width is out of range or not a number", () => {
    localStorage.setItem(STORAGE_KEY, "900");
    const { unmount } = renderPanels();
    expect(currentWidth()).toBe(240);
    unmount();

    localStorage.setItem(STORAGE_KEY, "wide");
    renderPanels();
    expect(currentWidth()).toBe(240);
  });

  it("still renders and resizes with the keyboard when localStorage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });

    renderPanels();
    expect(screen.getByText("Main area")).toBeInTheDocument();
    expect(currentWidth()).toBe(240);

    fireEvent.keyDown(getSeparator(), { key: "ArrowRight" });
    expect(currentWidth()).toBe(256);
  });
});
