import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Sparkline, SPARKLINE_HEIGHT, SPARKLINE_WIDTH, sparklinePoints } from "./Sparkline";

describe("sparklinePoints", () => {
  it("maps the lowest close to the bottom and the highest to the top, left to right", () => {
    const { points, trend } = sparklinePoints([10, 20, 30]);
    expect(trend).toBe("up");
    const [first, middle, last] = points.split(" ");
    expect(first.split(",")[1]).toBe((SPARKLINE_HEIGHT - 2).toFixed(2));
    expect(middle.split(",")[1]).toBe((SPARKLINE_HEIGHT / 2).toFixed(2));
    expect(last.split(",")[1]).toBe("2.00");
    expect(Number(first.split(",")[0])).toBeLessThan(Number(last.split(",")[0]));
  });

  it("reports a falling trend when the last close is below the first", () => {
    expect(sparklinePoints([30, 20, 10]).trend).toBe("down");
  });

  it("reports flat when the first and last closes match and draws a flat series at the middle", () => {
    const { points, trend } = sparklinePoints([5, 5, 5]);
    expect(trend).toBe("flat");
    for (const point of points.split(" ")) {
      expect(point.split(",")[1]).toBe((SPARKLINE_HEIGHT / 2).toFixed(2));
    }
  });
});

describe("Sparkline", () => {
  it("draws one polyline point per close, in the gain colour for a rising series", () => {
    const { container } = render(<Sparkline closes={[100, 101, 103, 107]} />);
    const svg = screen.getByRole("img", { name: "Trend rising over the last 4 closes" });

    expect(svg.tagName.toLowerCase()).toBe("svg");
    expect(svg).toHaveAttribute("data-sparkline", "up");
    expect(svg).toHaveClass("text-gain");
    expect(svg).toHaveAttribute("width", String(SPARKLINE_WIDTH));
    expect(svg).toHaveAttribute("height", String(SPARKLINE_HEIGHT));
    expect(container.querySelector("polyline")?.getAttribute("points")?.split(" ")).toHaveLength(4);
  });

  it("uses the loss colour and says falling for a falling series", () => {
    render(<Sparkline closes={[9, 7, 4]} />);
    const svg = screen.getByRole("img", { name: "Trend falling over the last 3 closes" });
    expect(svg).toHaveAttribute("data-sparkline", "down");
    expect(svg).toHaveClass("text-loss");
  });

  it("shows a dash with a Not available tooltip when there are no closes", () => {
    render(<Sparkline closes={undefined} />);
    const dash = screen.getByRole("img", { name: "Not available" });
    expect(dash).toHaveAttribute("title", "Not available");
    expect(dash).toHaveAttribute("data-sparkline", "none");
    expect(dash).toHaveTextContent("—");
    expect(dash).toHaveStyle({ width: `${SPARKLINE_WIDTH}px` });
  });

  it("shows the same dash for a null series and for a single close, which cannot make a line", () => {
    const { rerender } = render(<Sparkline closes={null} />);
    expect(screen.getByTitle("Not available")).toBeInTheDocument();
    rerender(<Sparkline closes={[42]} />);
    expect(screen.getByTitle("Not available")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Trend/ })).not.toBeInTheDocument();
  });

  it("keeps the same fixed width whether or not there is data", () => {
    const { rerender } = render(<Sparkline closes={null} />);
    const dash = screen.getByTitle("Not available");
    const dashWidth = dash.style.width;
    rerender(<Sparkline closes={[1, 2]} />);
    expect(screen.getByRole("img", { name: /Trend/ }).style.width).toBe(dashWidth);
  });
});
