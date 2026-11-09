import { describe, expect, it } from "vitest";
import { formatChange, formatCrore, formatInr, formatPercent } from "./format";

describe("formatInr", () => {
  it("groups in lakh and crore style", () => {
    expect(formatInr(12345678.9)).toBe("₹1,23,45,678.90");
  });

  it("formats values under a thousand with two decimals", () => {
    expect(formatInr(999)).toBe("₹999.00");
  });

  it("uses the U+2212 minus sign for negatives", () => {
    expect(formatInr(-1234)).toBe("−₹1,234.00");
  });

  it("returns an em dash for null, undefined and NaN", () => {
    expect(formatInr(null)).toBe("—");
    expect(formatInr(undefined)).toBe("—");
    expect(formatInr(Number.NaN)).toBe("—");
  });
});

describe("formatPercent", () => {
  it("adds a plus sign for positive values", () => {
    expect(formatPercent(1.2345)).toBe("+1.23%");
  });

  it("uses the U+2212 minus sign for negative values", () => {
    expect(formatPercent(-0.87)).toBe("−0.87%");
  });

  it("shows zero without a sign", () => {
    expect(formatPercent(0)).toBe("0.00%");
  });

  it("returns an em dash for null", () => {
    expect(formatPercent(null)).toBe("—");
  });
});

describe("formatChange", () => {
  it("formats a gain with an up arrow", () => {
    expect(formatChange(12.3, 1.24)).toBe("▲ +12.30 (+1.24%)");
  });

  it("formats a loss with a down arrow and U+2212 minus", () => {
    expect(formatChange(-12.3, -1.24)).toBe("▼ −12.30 (−1.24%)");
  });

  it("shows a neutral marker when both values are zero", () => {
    expect(formatChange(0, 0)).toBe("● 0.00%");
  });

  it("returns an em dash when either value is null", () => {
    expect(formatChange(null, 1.2)).toBe("—");
    expect(formatChange(1.2, null)).toBe("—");
  });
});

describe("formatCrore", () => {
  it("formats crore values with Indian grouping and no decimals", () => {
    expect(formatCrore(4512)).toBe("₹4,512 Cr");
  });

  it("formats large crore values with lakh-style grouping", () => {
    expect(formatCrore(123456)).toBe("₹1,23,456 Cr");
  });

  it("returns an em dash for null", () => {
    expect(formatCrore(null)).toBe("—");
  });
});
