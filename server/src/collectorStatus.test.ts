import { describe, expect, it } from "vitest";
import { buildCollectorStatus } from "./collectorStatus.js";

const NOW = new Date("2026-11-16T19:00:00+05:30");

function minusMs(ms: number): Date {
  return new Date(NOW.getTime() - ms);
}

describe("buildCollectorStatus", () => {
  it("is paused with since null when no poll has happened", () => {
    expect(buildCollectorStatus(null, NOW)).toEqual({ collector: { paused: true, since: null } });
  });

  it("is not paused with an IST since for a fresh poll", () => {
    const last = minusMs(30_000);
    expect(buildCollectorStatus(last, NOW)).toEqual({
      collector: { paused: false, since: "2026-11-16T18:59:30.000+05:30" },
    });
  });

  it("is not paused at 179_999 ms", () => {
    expect(buildCollectorStatus(minusMs(179_999), NOW).collector.paused).toBe(false);
  });

  it("is not paused at exactly 180_000 ms", () => {
    expect(buildCollectorStatus(minusMs(180_000), NOW).collector.paused).toBe(false);
  });

  it("is paused at 180_001 ms", () => {
    expect(buildCollectorStatus(minusMs(180_001), NOW).collector.paused).toBe(true);
  });
});
