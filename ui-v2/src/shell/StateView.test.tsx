import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StateView, type StateKind } from "./StateView";

describe("StateView", () => {
  it.each<StateKind>(["idle", "loading", "empty", "error", "market_closed", "pre_open", "stale"])(
    "renders the %s kind with its data-state",
    (kind) => {
      const { container, unmount } = render(<StateView kind={kind} message="Message text" />);

      expect(container.querySelector(`[data-state="${kind}"]`)).not.toBeNull();
      expect(screen.getByText("Message text")).toBeInTheDocument();
      unmount();
    },
  );

  it("uses the alert role for errors and the status role for the other kinds", () => {
    const { unmount } = render(<StateView kind="error" message="Broken" />);
    expect(screen.getByRole("alert")).toHaveAttribute("data-state", "error");
    unmount();

    render(<StateView kind="stale" message="Old data" />);
    expect(screen.getByRole("status")).toHaveAttribute("data-state", "stale");
  });

  it("calls the action handler when the action button is clicked", () => {
    const onClick = vi.fn();
    render(<StateView kind="error" message="Broken" action={{ label: "Retry", onClick }} />);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders three skeleton rows and aria-busy while loading", () => {
    const { container } = render(<StateView kind="loading" message="Loading" />);

    expect(container.querySelector('[data-state="loading"]')).toHaveAttribute("aria-busy", "true");
    expect(container.querySelectorAll("[data-skeleton-row]")).toHaveLength(3);
  });
});
