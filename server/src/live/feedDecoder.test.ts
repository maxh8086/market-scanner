import { describe, expect, it } from "vitest";
import { decodeFeedFrame, encodeFeedFrame } from "./feedDecoder.js";

describe("decodeFeedFrame", () => {
  it("returns the last traded price for each instrument in the frame", () => {
    const frame = encodeFeedFrame([
      { instrumentKey: "NSE_EQ|INE002A01018", ltp: 2847.5, ltt: 1794150000000, cp: 2830 },
      { instrumentKey: "NSE_EQ|INE040A01034", ltp: 1612.25 },
    ]);

    const ticks = decodeFeedFrame(frame);

    expect(ticks).toEqual(
      expect.arrayContaining([
        { instrumentKey: "NSE_EQ|INE002A01018", ltp: 2847.5, ltt: 1794150000000, cp: 2830, open: null, high: null, low: null },
        { instrumentKey: "NSE_EQ|INE040A01034", ltp: 1612.25, ltt: null, cp: null, open: null, high: null, low: null },
      ]),
    );
    expect(ticks).toHaveLength(2);
  });

  it("returns the day's open, high and low when the frame carries the 1-day candle", () => {
    const frame = encodeFeedFrame([
      { instrumentKey: "NSE_INDEX|Nifty 50", ltp: 25008.5, cp: 24986.4, open: 25010, high: 25055.2, low: 24960.1 },
    ]);

    expect(decodeFeedFrame(frame)).toEqual([
      {
        instrumentKey: "NSE_INDEX|Nifty 50",
        ltp: 25008.5,
        ltt: null,
        cp: 24986.4,
        open: 25010,
        high: 25055.2,
        low: 24960.1,
      },
    ]);
  });

  it("skips instruments whose last traded price is zero", () => {
    const frame = encodeFeedFrame([
      { instrumentKey: "NSE_EQ|INE002A01018", ltp: 0 },
      { instrumentKey: "NSE_EQ|INE040A01034", ltp: 10 },
    ]);

    expect(decodeFeedFrame(frame).map((tick) => tick.instrumentKey)).toEqual(["NSE_EQ|INE040A01034"]);
  });

  it("throws on bytes that are not a valid protobuf message", () => {
    expect(() => decodeFeedFrame(new Uint8Array([0xff, 0xff, 0xff]))).toThrow();
  });
});
