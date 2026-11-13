import type { Pool, PoolClient } from "pg";
import { describe, expect, it, vi } from "vitest";
import { makeEventsTx } from "./eventsTx.js";

// The work query returns workRowCount; BEGIN, COMMIT and ROLLBACK return rowCount undefined.
function fakeClient(workRowCount: number | null) {
  const query = vi.fn(async (text: string) => {
    if (text === "BEGIN" || text === "COMMIT" || text === "ROLLBACK") {
      return { rowCount: undefined };
    }
    return { rowCount: workRowCount };
  });
  const release = vi.fn();
  const client = { query, release } as unknown as PoolClient;
  return { client, query, release };
}

function fakePool(client: PoolClient) {
  const connect = vi.fn(async () => client);
  const pool = { connect } as unknown as Pool;
  return { pool, connect };
}

describe("makeEventsTx", () => {
  it("commits and returns the work result, then releases the client once", async () => {
    const { client, query, release } = fakeClient(1);
    const { pool } = fakePool(client);
    const tx = makeEventsTx(pool);

    const result = await tx(async (q) => {
      const res = await q("INSERT INTO home_events VALUES ($1)", [1]);
      return res.rowCount;
    });

    expect(result).toBe(1);
    expect(query.mock.calls.map((call) => call[0])).toEqual([
      "BEGIN",
      "INSERT INTO home_events VALUES ($1)",
      "COMMIT",
    ]);
    expect(release).toHaveBeenCalledTimes(1);
  });

  it("rolls back, rethrows the same error, never commits, and releases the client once", async () => {
    const { client, query, release } = fakeClient(1);
    const { pool } = fakePool(client);
    const tx = makeEventsTx(pool);
    const boom = new Error("insert failed");

    await expect(
      tx(async (q) => {
        await q("INSERT INTO home_events VALUES ($1)", [1]);
        throw boom;
      }),
    ).rejects.toBe(boom);

    const texts = query.mock.calls.map((call) => call[0]);
    expect(texts).toContain("ROLLBACK");
    expect(texts).not.toContain("COMMIT");
    expect(release).toHaveBeenCalledTimes(1);
  });

  it("maps a null rowCount from pg to 0 in the query wrapper given to work", async () => {
    const { client } = fakeClient(null);
    const { pool } = fakePool(client);
    const tx = makeEventsTx(pool);

    let seen: unknown;
    await tx(async (q) => {
      seen = await q("INSERT INTO home_events VALUES ($1)", [1]);
      return seen;
    });

    expect(seen).toEqual({ rowCount: 0 });
  });
});
