import { describe, expect, it } from "vitest";
import type { QueryFn } from "../app.js";
import type { Holding } from "../holdings/kiteHoldings.js";
import type { PortfolioQuery, PortfolioTx } from "../portfolioTx.js";
import {
  buildHoldingInsert,
  HOLDING_CHUNK_ROWS,
  loadLatestSnapshot,
  mergeDuplicateHoldings,
  saveOkSnapshot,
} from "./portfolioStore.js";

function holding(symbol: string, exchange = "NSE"): Holding {
  return {
    symbol,
    exchange,
    isin: "INE00000001",
    quantity: 10,
    averagePrice: 100,
    lastPrice: 110,
    pnl: 100,
    dayChange: 1.5,
    dayChangePct: 0.5,
  };
}

function recordingTx(failText?: string) {
  const statements: Array<{ text: string; values: unknown[] }> = [];
  const query: PortfolioQuery = async (text, values) => {
    statements.push({ text, values });
    if (failText && text.includes(failText)) throw new Error("db down");
    return { rowCount: 1 };
  };
  const tx: PortfolioTx = (work) => work(query);
  return { tx, statements };
}

describe("buildHoldingInsert", () => {
  it("builds one row of 13 placeholders per holding and stores the raw row as jsonb", () => {
    const built = buildHoldingInsert("s1", "default", "kite", [holding("ACE"), holding("BEE")]);

    expect(built.values).toHaveLength(26);
    expect(built.text).toContain("INSERT INTO portfolio_holding");
    expect(built.text).toContain("$13::jsonb");
    expect(built.text).toContain("$26::jsonb");
    expect(built.text).not.toContain("$27");
    expect(built.values[12]).toBe(JSON.stringify(holding("ACE")));
  });
});

describe("mergeDuplicateHoldings", () => {
  it("returns rows without duplicate (symbol, exchange) keys unchanged and in order", () => {
    const rows = [holding("ACE"), holding("ACE", "BSE"), holding("BEE")];
    expect(mergeDuplicateHoldings(rows)).toEqual(rows);
  });

  it("merges duplicate rows with summed quantity and pnl and a quantity-weighted average price", () => {
    const first: Holding = {
      ...holding("ACE"),
      quantity: 10,
      averagePrice: 100,
      lastPrice: 110,
      pnl: 100,
      dayChange: 1.5,
      dayChangePct: 0.5,
      isin: null,
    };
    const second: Holding = {
      ...holding("ACE"),
      quantity: 30,
      averagePrice: 200,
      lastPrice: 999,
      pnl: -50,
      dayChange: null,
      dayChangePct: null,
      isin: "INE00000002",
    };
    const other = holding("ACE", "BSE");

    const merged = mergeDuplicateHoldings([first, other, second]);

    expect(merged).toEqual([
      {
        symbol: "ACE",
        exchange: "NSE",
        isin: "INE00000002",
        quantity: 40,
        averagePrice: 175,
        lastPrice: 110,
        pnl: 50,
        dayChange: 1.5,
        dayChangePct: 0.5,
      },
      other,
    ]);
  });

  it("sums dayChange over the non-null values and keeps null when every value is null", () => {
    const a = { ...holding("ACE"), dayChange: 2, dayChangePct: null };
    const b = { ...holding("ACE"), dayChange: 3, dayChangePct: 1 };
    const c = { ...holding("BEE"), dayChange: null, dayChangePct: null };
    const d = { ...holding("BEE"), dayChange: null, dayChangePct: null };

    const merged = mergeDuplicateHoldings([a, b, c, d]);

    expect(merged[0].dayChange).toBe(5);
    expect(merged[0].dayChangePct).toBe(1);
    expect(merged[1].dayChange).toBeNull();
    expect(merged[1].dayChangePct).toBeNull();
  });

  it("keeps the first row's average price when the total quantity is 0", () => {
    const merged = mergeDuplicateHoldings([
      { ...holding("ACE"), quantity: 5, averagePrice: 100 },
      { ...holding("ACE"), quantity: -5, averagePrice: 300 },
    ]);

    expect(merged).toHaveLength(1);
    expect(merged[0].quantity).toBe(0);
    expect(merged[0].averagePrice).toBe(100);
  });
});

describe("saveOkSnapshot", () => {
  it("merges duplicate holdings so the sync row count and the inserted rows match the merged list", async () => {
    const { tx, statements } = recordingTx();

    const saved = await saveOkSnapshot(tx, {
      syncId: "s1",
      profile: "default",
      broker: "kite",
      syncedAt: "t",
      holdings: [holding("ACE"), holding("ACE"), holding("BEE")],
    });

    expect(saved).toBe(2);
    expect(statements[0].values[5]).toBe(2);
    expect(statements[1].values).toHaveLength(2 * 13);
  });

  it("writes an ok sync row with the holding count, then the holdings", async () => {
    const { tx, statements } = recordingTx();

    await saveOkSnapshot(tx, {
      syncId: "s1",
      profile: "default",
      broker: "kite",
      syncedAt: "2026-11-14T09:00:00.000Z",
      holdings: [holding("ACE"), holding("BEE")],
    });

    expect(statements).toHaveLength(2);
    expect(statements[0].text).toContain("INSERT INTO portfolio_sync");
    expect(statements[0].values).toEqual(["s1", "default", "kite", "2026-11-14T09:00:00.000Z", "ok", 2]);
    expect(statements[1].text).toContain("INSERT INTO portfolio_holding");
  });

  it("splits large snapshots into chunks of HOLDING_CHUNK_ROWS", async () => {
    const { tx, statements } = recordingTx();
    const holdings = Array.from({ length: HOLDING_CHUNK_ROWS * 2 + 10 }, (_, i) => holding(`S${i}`));

    await saveOkSnapshot(tx, { syncId: "s1", profile: "default", broker: "kite", syncedAt: "t", holdings });

    expect(statements).toHaveLength(1 + 3);
    expect(statements[1].values).toHaveLength(HOLDING_CHUNK_ROWS * 13);
    expect(statements[3].values).toHaveLength(10 * 13);
  });

  it("rejects when a statement fails, so the caller can roll back", async () => {
    const { tx } = recordingTx("portfolio_holding");

    await expect(
      saveOkSnapshot(tx, { syncId: "s1", profile: "default", broker: "kite", syncedAt: "t", holdings: [holding("ACE")] }),
    ).rejects.toThrow("db down");
  });
});

describe("loadLatestSnapshot", () => {
  it("returns an empty view when no ok sync is stored", async () => {
    const query = (async () => ({ rows: [] })) as unknown as QueryFn;
    expect(await loadLatestSnapshot(query, "default", "kite")).toEqual({
      holdings: [],
      syncedAt: null,
      broker: null,
    });
  });

  it("maps the latest snapshot to the public shape without the exchange", async () => {
    const seen: Array<{ text: string; values: unknown[] }> = [];
    const query = (async (text: string, values: unknown[]) => {
      seen.push({ text, values });
      if (text.includes("FROM portfolio_sync")) {
        return { rows: [{ sync_id: "s1", synced_at: new Date("2026-11-13T10:00:00.000Z") }] };
      }
      return {
        rows: [
          {
            symbol: "ACE",
            isin: null,
            quantity: "100",
            average_price: 834.1,
            last_price: 1166,
            pnl: 33189.55,
            day_change: null,
            day_change_pct: 0.41,
          },
        ],
      };
    }) as unknown as QueryFn;

    const view = await loadLatestSnapshot(query, "default", "kite");

    expect(seen[0].values).toEqual(["default", "kite"]);
    expect(seen[1].values).toEqual(["s1"]);
    expect(view).toEqual({
      syncedAt: "2026-11-13T10:00:00.000Z",
      broker: "kite",
      holdings: [
        {
          symbol: "ACE",
          isin: null,
          quantity: 100,
          averagePrice: 834.1,
          lastPrice: 1166,
          pnl: 33189.55,
          dayChange: null,
          dayChangePct: 0.41,
        },
      ],
    });
    expect(JSON.stringify(view)).not.toContain("exchange");
  });
});
