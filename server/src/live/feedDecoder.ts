/**
 * Decodes one binary frame from the Upstox market-data feed (protobuf) into last-traded-price ticks.
 *
 * Only the fields the live ticker needs are declared here. Protobuf skips any field number this
 * schema does not list, so the rest of the Upstox message is ignored safely.
 *
 * Field numbers follow Upstox's MarketDataFeedV3 message definitions. They were transcribed from
 * the public upstox-python SDK, not checked byte-for-byte against a live frame yet. Verify with a
 * captured frame before relying on the values (see the live-feed notes in the PR).
 */
import protobuf from "protobufjs";

const SCHEMA = {
  nested: {
    LTPC: {
      fields: {
        ltp: { type: "double", id: 1 },
        ltt: { type: "int64", id: 2 },
        ltq: { type: "int64", id: 3 },
        cp: { type: "double", id: 4 },
      },
    },
    OHLC: {
      fields: {
        interval: { type: "string", id: 1 },
        open: { type: "double", id: 2 },
        high: { type: "double", id: 3 },
        low: { type: "double", id: 4 },
        close: { type: "double", id: 5 },
        vol: { type: "int64", id: 6 },
        ts: { type: "int64", id: 7 },
      },
    },
    MarketOHLC: {
      fields: { ohlc: { rule: "repeated", type: "OHLC", id: 1 } },
    },
    MarketFullFeed: {
      fields: {
        ltpc: { type: "LTPC", id: 1 },
        marketOHLC: { type: "MarketOHLC", id: 4 },
      },
    },
    FullFeed: {
      fields: { marketFF: { type: "MarketFullFeed", id: 1 } },
    },
    FirstLevelWithGreeks: {
      fields: { ltpc: { type: "LTPC", id: 1 } },
    },
    Feed: {
      fields: {
        ltpc: { type: "LTPC", id: 1 },
        fullFeed: { type: "FullFeed", id: 2 },
        firstLevelWithGreeks: { type: "FirstLevelWithGreeks", id: 3 },
      },
    },
    FeedResponse: {
      fields: {
        feeds: { keyType: "string", type: "Feed", id: 2 },
        currentTs: { type: "int64", id: 3 },
      },
    },
  },
};

const root = protobuf.Root.fromJSON(SCHEMA);
const FeedResponse = root.lookupType("FeedResponse");

export interface DecodedTick {
  instrumentKey: string;
  ltp: number;
  /** Last traded time, epoch milliseconds, when the frame carries it. */
  ltt: number | null;
  /** Previous close, when the frame carries it. */
  cp: number | null;
  /** Today's open, high and low. Only full-mode frames carry them (the 1-day OHLC candle). */
  open?: number | null;
  high?: number | null;
  low?: number | null;
}

interface LtpcShape {
  ltp?: number;
  ltt?: number;
  cp?: number;
}

interface OhlcShape {
  interval?: string;
  open?: number;
  high?: number;
  low?: number;
}

interface FeedShape {
  ltpc?: LtpcShape;
  fullFeed?: { marketFF?: { ltpc?: LtpcShape; marketOHLC?: { ohlc?: OhlcShape[] } } };
  firstLevelWithGreeks?: { ltpc?: LtpcShape };
}

/** The day candle in a full-mode frame, or nulls when the frame has none. */
function dayCandle(feed: FeedShape): { open: number | null; high: number | null; low: number | null } {
  const candle = feed.fullFeed?.marketFF?.marketOHLC?.ohlc?.find((item) => item.interval === "1d");
  const positive = (value: number | undefined) => (typeof value === "number" && value > 0 ? value : null);
  return {
    open: positive(candle?.open),
    high: positive(candle?.high),
    low: positive(candle?.low),
  };
}

interface FeedResponseShape {
  feeds?: Record<string, FeedShape>;
}

/** Decode one frame. Returns one tick per instrument that carries a positive last traded price. */
export function decodeFeedFrame(bytes: Uint8Array): DecodedTick[] {
  const message = FeedResponse.decode(bytes);
  const body = FeedResponse.toObject(message, { longs: Number, defaults: false }) as FeedResponseShape;
  const ticks: DecodedTick[] = [];
  for (const [instrumentKey, feed] of Object.entries(body.feeds ?? {})) {
    const ltpc = feed.ltpc ?? feed.fullFeed?.marketFF?.ltpc ?? feed.firstLevelWithGreeks?.ltpc;
    if (!ltpc || typeof ltpc.ltp !== "number" || !(ltpc.ltp > 0)) {
      continue;
    }
    ticks.push({
      instrumentKey,
      ltp: ltpc.ltp,
      // Protobuf fills absent numeric fields with 0, so 0 means "not in the frame" for these two.
      ltt: typeof ltpc.ltt === "number" && ltpc.ltt > 0 ? ltpc.ltt : null,
      cp: typeof ltpc.cp === "number" && ltpc.cp > 0 ? ltpc.cp : null,
      ...dayCandle(feed),
    });
  }
  return ticks;
}

/** Test helper: encode a frame in the same shape, so tests can round-trip without a live feed. */
export function encodeFeedFrame(
  ticks: Array<{ instrumentKey: string; ltp: number; ltt?: number; cp?: number; open?: number; high?: number; low?: number }>,
): Uint8Array {
  const feeds: Record<string, unknown> = {};
  for (const tick of ticks) {
    const ltpc = { ltp: tick.ltp, ltt: tick.ltt ?? 0, cp: tick.cp ?? 0 };
    feeds[tick.instrumentKey] =
      tick.open === undefined
        ? { firstLevelWithGreeks: { ltpc } }
        : {
            fullFeed: {
              marketFF: {
                ltpc,
                marketOHLC: {
                  ohlc: [{ interval: "1d", open: tick.open, high: tick.high ?? 0, low: tick.low ?? 0 }],
                },
              },
            },
          };
  }
  const message = FeedResponse.fromObject({ feeds, currentTs: Date.now() });
  return FeedResponse.encode(message).finish();
}
