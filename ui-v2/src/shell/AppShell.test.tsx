import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../theme/ThemeProvider";
import { AppShell } from "./AppShell";
import { DataAgeStamp } from "./DataAgeStamp";

function renderWithTheme(ui: ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

function renderShell() {
  return renderWithTheme(
    <AppShell
      tabs={[{ id: "home", label: "Home" }]}
      activeTabId="home"
      onSelectTab={() => undefined}
    >
      <p>Body</p>
    </AppShell>,
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders the brand text and selects the Home tab", () => {
    renderShell();

    expect(screen.getByText("Market Scanner")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Home" })).toHaveAttribute("aria-selected", "true");
  });

  it("toggles the theme attribute on the document element", () => {
    renderShell();

    fireEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");

    fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("shows an em dash when DataAgeStamp has no props", () => {
    render(<DataAgeStamp />);

    expect(screen.getByText(/—/)).toBeInTheDocument();
    expect(screen.getByTitle("Not available")).toBeInTheDocument();
  });
});
