import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// index.ts starts the server and opens the database pool when imported, so its wiring is checked as source text.
const indexSource = readFileSync(new URL("./index.ts", import.meta.url), "utf-8");

describe("index.ts events pool wiring", () => {
  it("passes the events pool, not the main pool, to the events transaction", () => {
    expect(indexSource).toContain("makeEventsTx(eventsPool)");
    expect(indexSource).not.toContain("makeEventsTx(pool)");
  });

  it("builds the events pool from eventsPoolConfig and pings it for /api/health", () => {
    expect(indexSource).toContain("new Pool(eventsPoolConfig())");
    expect(indexSource).toContain('eventsPing: () => eventsPool.query("SELECT 1")');
  });
});

describe("index.ts secrets wiring", () => {
  it("never asks the secrets API for the Kite access token", () => {
    expect(indexSource).not.toContain('secrets.get("kite_access_token")');
  });

  it("never names an API secret, so the server cannot request one", () => {
    expect(indexSource).not.toContain("api_secret");
  });

  it("builds broker secret names in broker/ code, not in index.ts", () => {
    expect(indexSource).not.toContain("kite_api_key");
    expect(indexSource).not.toContain("broker_");
  });

  it("fetches only the Upstox analytics token through the secrets client", () => {
    expect(indexSource).toContain('secrets.get("upstox_analytics_token")');
    const requested = [...indexSource.matchAll(/secrets\.get\("([^"]+)"\)/g)].map((m) => m[1]);
    expect(requested.sort()).toEqual(["upstox_analytics_token"]);
  });
});
