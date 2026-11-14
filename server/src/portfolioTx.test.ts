import type { PoolClient } from "pg";
import { describe, expect, it, vi } from "vitest";
import { makePortfolioTx } from "./portfolioTx.js";

function fakeClient(opts: { failText?: string; rollbackFails?: boolean } = {}) {
  const statements: string[] = [];
  const release = vi.fn();
  const query = vi.fn(async (text: string) => {
    statements.push(text);
    if (text === "ROLLBACK" && opts.rollbackFails) throw new Error("rollback failed");
    if (opts.failText && text.includes(opts.failText)) throw new Error("insert failed");
    return { rowCount: 2 };
  });
  const client = { query, release } as unknown as PoolClient;
  const pool = { connect: vi.fn(async () => client) };
  return { pool, statements, release };
}

describe("makePortfolioTx", () => {
  it("runs BEGIN, the work and COMMIT, then releases the client and returns the work result", async () => {
    const { pool, statements, release } = fakeClient();
    const tx = makePortfolioTx(pool);

    const result = await tx(async (query) => {
      const res = await query("INSERT INTO portfolio_sync VALUES ($1)", ["s1"]);
      return res.rowCount;
    });

    expect(result).toBe(2);
    expect(statements).toEqual(["BEGIN", "INSERT INTO portfolio_sync VALUES ($1)", "COMMIT"]);
    expect(release).toHaveBeenCalledTimes(1);
  });

  it("rolls back, rethrows and releases the client when the work fails", async () => {
    const { pool, statements, release } = fakeClient({ failText: "portfolio_holding" });
    const tx = makePortfolioTx(pool);

    await expect(
      tx(async (query) => {
        await query("INSERT INTO portfolio_holding VALUES ($1)", ["x"]);
      }),
    ).rejects.toThrow("insert failed");

    expect(statements).toContain("ROLLBACK");
    expect(statements).not.toContain("COMMIT");
    expect(release).toHaveBeenCalledTimes(1);
  });

  it("still rethrows the original error and releases when ROLLBACK itself fails", async () => {
    const { pool, release } = fakeClient({ failText: "portfolio_holding", rollbackFails: true });
    const tx = makePortfolioTx(pool);

    await expect(
      tx(async (query) => {
        await query("INSERT INTO portfolio_holding VALUES ($1)", ["x"]);
      }),
    ).rejects.toThrow("insert failed");
    expect(release).toHaveBeenCalledTimes(1);
  });
});
