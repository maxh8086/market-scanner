import { describe, expect, it } from "vitest";
import type { SectorSummaryRow } from "../api/sectorSummary";
import { advDecRatio, breadthShares, sortSectors, stockCountLabel, toneOf, topAndBottom } from "./sectorView";

function row(sector: string, avgChangePct: number, count = 10, advancers = 5, decliners = 5): SectorSummaryRow {
  return { sector, count, avgChangePct, advancers, decliners };
}

describe("toneOf", () => {
  it("is flat within 0.005 percent of zero", () => {
    expect(toneOf(0)).toBe("flat");
    expect(toneOf(0.004)).toBe("flat");
    expect(toneOf(-0.004)).toBe("flat");
  });

  it("uses light tones below 1 percent and strong tones at or beyond 1 percent", () => {
    expect(toneOf(0.5)).toBe("light_gain");
    expect(toneOf(1)).toBe("strong_gain");
    expect(toneOf(-0.5)).toBe("light_loss");
    expect(toneOf(-1)).toBe("strong_loss");
  });
});

describe("advDecRatio", () => {
  it("divides advancers by decliners", () => {
    expect(advDecRatio(row("A", 1, 10, 6, 4))).toBe(1.5);
  });

  it("is infinite when there are advancers and no decliners, and 0 when neither", () => {
    expect(advDecRatio(row("A", 1, 3, 3, 0))).toBe(Number.POSITIVE_INFINITY);
    expect(advDecRatio(row("A", 0, 3, 0, 0))).toBe(0);
  });
});

describe("breadthShares", () => {
  it("returns advancing and declining shares of the stock count", () => {
    expect(breadthShares(row("A", 1, 10, 6, 2))).toEqual({ up: 60, down: 20 });
  });

  it("returns zero shares for a sector with no stocks", () => {
    expect(breadthShares(row("A", 0, 0, 0, 0))).toEqual({ up: 0, down: 0 });
  });
});

describe("sortSectors", () => {
  const rows = [row("Banks", -0.5, 5), row("IT", 1.2, 10), row("Power", 0.3, 20)];

  it("sorts by change descending", () => {
    expect(sortSectors(rows, { key: "avgChangePct", dir: "desc" }).map((r) => r.sector)).toEqual([
      "IT",
      "Power",
      "Banks",
    ]);
  });

  it("sorts by sector name ascending", () => {
    expect(sortSectors(rows, { key: "sector", dir: "asc" }).map((r) => r.sector)).toEqual(["Banks", "IT", "Power"]);
  });

  it("sorts by stock count descending", () => {
    expect(sortSectors(rows, { key: "count", dir: "desc" }).map((r) => r.sector)).toEqual(["Power", "IT", "Banks"]);
  });

  it("does not mutate the input", () => {
    sortSectors(rows, { key: "avgChangePct", dir: "asc" });
    expect(rows.map((r) => r.sector)).toEqual(["Banks", "IT", "Power"]);
  });

  it("breaks ties by sector name", () => {
    const tied = [row("Zinc", 1), row("Aluminium", 1)];
    expect(sortSectors(tied, { key: "avgChangePct", dir: "desc" }).map((r) => r.sector)).toEqual(["Aluminium", "Zinc"]);
  });
});

describe("topAndBottom", () => {
  it("returns the best and worst n sectors, best first in each list", () => {
    const rows = [row("A", 3), row("B", 2), row("C", 1), row("D", -1), row("E", -2), row("F", -3)];
    const { top, bottom } = topAndBottom(rows, 2);
    expect(top.map((r) => r.sector)).toEqual(["A", "B"]);
    expect(bottom.map((r) => r.sector)).toEqual(["F", "E"]);
  });

  it("does not repeat a sector in both lists when there are fewer than 2n sectors", () => {
    const rows = [row("A", 3), row("B", 2), row("C", 1)];
    const { top, bottom } = topAndBottom(rows, 3);
    expect(top.map((r) => r.sector)).toEqual(["A", "B", "C"]);
    expect(bottom).toEqual([]);
  });
});

describe("stockCountLabel", () => {
  it("uses the singular only for exactly one stock", () => {
    expect(stockCountLabel(0)).toBe("0 stocks");
    expect(stockCountLabel(1)).toBe("1 stock");
    expect(stockCountLabel(12)).toBe("12 stocks");
  });
});
