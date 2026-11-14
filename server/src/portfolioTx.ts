import type { Pool, PoolClient } from "pg";

/** One statement inside a portfolio transaction. The result carries the affected row count. */
export type PortfolioQuery = (text: string, values: unknown[]) => Promise<{ rowCount: number }>;

export type PortfolioTx = <T>(work: (query: PortfolioQuery) => Promise<T>) => Promise<T>;

/**
 * Runs the portfolio snapshot writes in one transaction on a pooled client. Rolls back and rethrows on error,
 * and always releases the client. Same shape as makeEventsTx.
 */
export function makePortfolioTx(pool: Pick<Pool, "connect">): PortfolioTx {
  return async (work) => {
    const client: PoolClient = await pool.connect();
    try {
      await client.query("BEGIN");
      const result = await work((text, values) =>
        client.query(text, values).then((res) => ({ rowCount: res.rowCount ?? 0 })),
      );
      await client.query("COMMIT");
      return result;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  };
}
