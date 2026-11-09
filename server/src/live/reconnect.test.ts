import { describe, expect, it } from "vitest";
import { backoffDelayMs, BACKOFF_STEPS_MS } from "./reconnect.js";

describe("backoffDelayMs", () => {
  it("grows through the steps and caps at the last one", () => {
    expect(backoffDelayMs(0)).toBe(1_000);
    expect(backoffDelayMs(1)).toBe(2_000);
    expect(backoffDelayMs(5)).toBe(30_000);
    expect(backoffDelayMs(50)).toBe(BACKOFF_STEPS_MS[BACKOFF_STEPS_MS.length - 1]);
  });

  it("treats negative or fractional attempts as the first step", () => {
    expect(backoffDelayMs(-3)).toBe(1_000);
    expect(backoffDelayMs(1.9)).toBe(2_000);
  });
});
