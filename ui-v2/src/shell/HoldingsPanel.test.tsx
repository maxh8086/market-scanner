import { describe, expect, it } from "vitest";
import {
  formatInr,
  formatSignedPct,
  toHoldingRow,
  totalHoldings,
} from "./HoldingsPanel";

describe("formatting", () => {
  it("groups digits in the Indian style with two decimals", () => {
    expect(formatInr(116600)).toBe("1,16,600.00");
    expect(formatInr(3306958.8)).toBe("33,06,958.80");
  });

  it("signs percentages and shows a dash when there is no value", () => {
    expect(formatSignedPct(39.79)).toBe("+39.79%");
    expect(formatSignedPct(-1.49)).toBe("-1.49%");
    expect(formatSignedPct(null)).toBe("—");
  });
});

describe("holding rows and totals", () => {
  const ace = toHoldingRow({
    symbol: "ACE",
    isin: null,
    quantity: 100,
    averagePrice: 834.1,
    lastPrice: 1166,
    pnl: 33190,
    dayChange: 4.9,
    dayChangePct: 0.41,
  });

  it("derives invested value, current value and net change from quantity and prices", () => {
    expect(ace.invested).toBeCloseTo(83410);
    expect(ace.curVal).toBeCloseTo(116600);
    expect(ace.netChgPct).toBeCloseTo((33190 / 83410) * 100);
    expect(ace.dayChg).toBeCloseTo(490);
  });

  it("totals invested, current value, P&L and the rupee day change", () => {
    const second = toHoldingRow({
      symbol: "BEL",
      isin: null,
      quantity: 100,
      averagePrice: 430,
      lastPrice: 394,
      pnl: -3600,
      dayChange: -3.5,
      dayChangePct: -0.89,
    });
    const total = totalHoldings([ace, second]);

    expect(total.invested).toBeCloseTo(83410 + 43000);
    expect(total.curVal).toBeCloseTo(116600 + 39400);
    expect(total.pnl).toBeCloseTo(33190 - 3600);
    expect(total.dayChg).toBeCloseTo(490 - 350);
  });

  it("leaves the net change empty when invested value is zero", () => {
    const free = toHoldingRow({
      symbol: "X",
      isin: null,
      quantity: 1,
      averagePrice: 0,
      lastPrice: 10,
      pnl: 10,
      dayChange: null,
      dayChangePct: null,
    });
    expect(free.netChgPct).toBeNull();
  });
});
