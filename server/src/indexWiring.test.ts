import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// index.ts starts the server and opens the database pool when imported, so its wiring is checked as source text.
const indexSource = readFileSync(new URL("./index.ts", import.meta.url), "utf-8");

describe("index.ts secrets wiring", () => {
  it("never asks the secrets API for the Kite access token", () => {
    expect(indexSource).not.toContain('secrets.get("kite_access_token")');
  });

  it("fetches only the Kite API key and the Upstox analytics token through the secrets client", () => {
    expect(indexSource).toContain('secrets.get("kite_api_key")');
    const requested = [...indexSource.matchAll(/secrets\.get\("([^"]+)"\)/g)].map((m) => m[1]);
    expect(requested.sort()).toEqual(["kite_api_key", "upstox_analytics_token"]);
  });
});
