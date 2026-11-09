import { describe, expect, it } from "vitest";
import { getMarketSession, isRunStale, runAgeDays } from "./marketSession";

// IST is UTC+05:30 with no daylight saving. 2026-11-09 is a Monday.
const MON_0905_IST = new Date("2026-11-09T03:35:00Z");
const MON_1000_IST = new Date("2026-11-09T04:30:00Z");
const MON_1600_IST = new Date("2026-11-09T10:30:00Z");
const MON_0900_IST = new Date("2026-11-09T03:30:00Z");
const MON_0914_IST = new Date("2026-11-09T03:44:00Z");
const MON_0915_IST = new Date("2026-11-09T03:45:00Z");
const MON_1529_IST = new Date("2026-11-09T09:59:00Z");
const MON_1530_IST = new Date("2026-11-09T10:00:00Z");
const SAT_1000_IST = new Date("2026-11-14T04:30:00Z");

describe("getMarketSession", () => {
  it("is pre_open at 09:05 IST on a weekday", () => {
    expect(getMarketSession(MON_0905_IST).status).toBe("pre_open");
  });

  it("is pre_open from 09:00 up to 09:14:59 IST and open from 09:15 IST", () => {
    expect(getMarketSession(MON_0900_IST).status).toBe("pre_open");
    expect(getMarketSession(MON_0914_IST).status).toBe("pre_open");
    expect(getMarketSession(MON_0915_IST).status).toBe("open");
  });

  it("is open at 10:00 IST on a weekday", () => {
    expect(getMarketSession(MON_1000_IST).status).toBe("open");
  });

  it("is open up to 15:29:59 IST and closed from 15:30 IST", () => {
    expect(getMarketSession(MON_1529_IST).status).toBe("open");
    expect(getMarketSession(MON_1530_IST).status).toBe("closed");
  });

  it("is closed at 16:00 IST on a weekday and names that day's close as the last close", () => {
    const session = getMarketSession(MON_1600_IST);
    expect(session.status).toBe("closed");
    expect(session.lastCloseLabel).toBe("Mon 9 Nov, 15:30 IST");
  });

  it("is closed on a Saturday and names Friday's close as the last close", () => {
    const session = getMarketSession(SAT_1000_IST);
    expect(session.status).toBe("closed");
    expect(session.lastCloseLabel).toBe("Fri 13 Nov, 15:30 IST");
  });

  it("names the previous weekday's close before 15:30 IST on a Monday", () => {
    expect(getMarketSession(MON_1000_IST).lastCloseLabel).toBe("Fri 6 Nov, 15:30 IST");
  });
});

describe("isRunStale and runAgeDays", () => {
  it("treats a Friday run as current on Monday before 09:15 IST, because Monday's run is not due yet", () => {
    expect(isRunStale("2026-11-06", MON_0905_IST)).toBe(false);
    expect(runAgeDays("2026-11-06", MON_0905_IST)).toBe(0);
  });

  it("treats a Friday run as current on Monday while the market is open", () => {
    expect(isRunStale("2026-11-06", MON_1000_IST)).toBe(false);
  });

  it("treats a Thursday run as one trading day old on Monday while the market is open", () => {
    expect(isRunStale("2026-11-05", MON_1000_IST)).toBe(true);
    expect(runAgeDays("2026-11-05", MON_1000_IST)).toBe(1);
  });

  it("treats a Friday run as one trading day old once Monday's close has passed", () => {
    expect(isRunStale("2026-11-06", MON_1600_IST)).toBe(true);
    expect(runAgeDays("2026-11-06", MON_1600_IST)).toBe(1);
  });

  it("is not stale for the most recent weekday's run, and its age is 0", () => {
    expect(isRunStale("2026-11-09", MON_1600_IST)).toBe(false);
    expect(runAgeDays("2026-11-09", MON_1600_IST)).toBe(0);
  });

  it("does not treat a run dated after the expected run as stale", () => {
    expect(isRunStale("2026-11-09", MON_1000_IST)).toBe(false);
  });

  it("is not stale for a Friday run seen on a Saturday", () => {
    expect(isRunStale("2026-11-13", SAT_1000_IST)).toBe(false);
  });
});

// 2026-11-10 (Tuesday) is in EXCHANGE_HOLIDAYS_2026 (Diwali Balipratipada).
const TUE_HOL_1000_IST = new Date("2026-11-10T04:30:00Z");
const WED_1000_IST = new Date("2026-11-11T04:30:00Z");
const WED_1600_IST = new Date("2026-11-11T10:30:00Z");

describe("exchange holidays", () => {
  it("is closed at 10:00 IST on a listed weekday holiday", () => {
    expect(getMarketSession(TUE_HOL_1000_IST).status).toBe("closed");
  });

  it("skips a holiday when naming the last close", () => {
    // Wednesday before 15:30: the previous trading day is Monday, because Tuesday is a holiday.
    expect(getMarketSession(WED_1000_IST).lastCloseLabel).toBe("Mon 9 Nov, 15:30 IST");
  });

  it("does not count a holiday as a trading day of run age", () => {
    // Expected run date is Wednesday 11 Nov after its close. Monday and Wednesday count; Tuesday does not.
    expect(runAgeDays("2026-11-06", WED_1600_IST)).toBe(2);
    expect(isRunStale("2026-11-09", WED_1000_IST)).toBe(false);
  });
});
