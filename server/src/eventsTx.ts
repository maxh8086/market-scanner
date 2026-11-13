import type { Pool, PoolClient } from "pg";
import type { HomeEventsRouteDeps } from "./homeEventsRoute.js";

/**
 * Runs the ingest work in one transaction on a pooled client. Rolls back and rethrows on error, and always releases the client.
 */
export function makeEventsTx(pool: Pick<Pool, "connect">): HomeEventsRouteDeps["eventsTx"] {
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
