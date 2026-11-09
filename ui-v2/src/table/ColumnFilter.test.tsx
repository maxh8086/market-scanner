import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ColumnFilter } from "./ColumnFilter";

describe("ColumnFilter", () => {
  it("opens a popover from the funnel button and applies a range", () => {
    const onApply = vi.fn();
    render(<ColumnFilter label="LTP" kind="range" value={["", ""]} active={false} onApply={onApply} />);

    fireEvent.click(screen.getByRole("button", { name: "Filter LTP" }));
    fireEvent.change(screen.getByLabelText("Min"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(onApply).toHaveBeenCalledWith(["10", ""]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("clears a set filter with the Clear button", () => {
    const onApply = vi.fn();
    render(<ColumnFilter label="Sector" kind="text" value={["IT", ""]} active onApply={onApply} />);

    fireEvent.click(screen.getByRole("button", { name: "Filter Sector" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(onApply).toHaveBeenCalledWith(["", ""]);
  });

  it("closes on Escape without applying", () => {
    const onApply = vi.fn();
    render(<ColumnFilter label="Stance" kind="select" options={["mixed"]} value={["", ""]} active={false} onApply={onApply} />);

    fireEvent.click(screen.getByRole("button", { name: "Filter Stance" }));
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onApply).not.toHaveBeenCalled();
  });
});
