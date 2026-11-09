import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FilterBar } from "./FilterBar";

describe("FilterBar", () => {
  it("renders a visible label for every input", () => {
    render(<FilterBar value={{}} onChange={vi.fn()} />);

    for (const label of [
      "Bucket",
      "Stance",
      "Symbol or company",
      "Sector",
      "LTP min",
      "LTP max",
      "From ATH min (%)",
      "From ATH max (%)",
      "ATH date from",
      "ATH date to",
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
  });

  it("reports a text change under the search key", () => {
    const onChange = vi.fn();
    render(<FilterBar value={{}} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Symbol or company"), { target: { value: "REL" } });

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ search: "REL" }));
  });

  it("reports a number change as a number under the LTP key", () => {
    const onChange = vi.fn();
    render(<FilterBar value={{}} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("LTP min"), { target: { value: "150.5" } });

    expect(onChange).toHaveBeenCalledWith({ ltpMin: 150.5 });
  });

  it("removes the key when a field is emptied", () => {
    const onChange = vi.fn();
    render(<FilterBar value={{ industry: "IT" }} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Sector"), { target: { value: "" } });

    expect(onChange).toHaveBeenCalledWith({});
  });

  it("reports a date change under the ATH key", () => {
    const onChange = vi.fn();
    render(<FilterBar value={{}} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("ATH date to"), { target: { value: "2026-08-31" } });

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ athTo: "2026-08-31" }));
  });

  it("offers server values for bucket and stance when given", () => {
    const onChange = vi.fn();
    render(
      <FilterBar value={{}} onChange={onChange} bucketOptions={["A", "B"]} stanceOptions={["Buy"]} />,
    );

    fireEvent.change(screen.getByLabelText("Stance"), { target: { value: "Buy" } });

    expect(screen.getByRole("option", { name: "B" })).toBeInTheDocument();
    expect(onChange).toHaveBeenCalledWith({ stance: "Buy" });
  });

  it("clear filters calls onChange with an empty filter state", () => {
    const onChange = vi.fn();
    render(<FilterBar value={{ bucket: "A", search: "x" }} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(onChange).toHaveBeenCalledWith({});
  });
});
