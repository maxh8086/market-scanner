import { Writable } from "node:stream";
import { describe, expect, it, vi } from "vitest";
import { buildApp, type QueryFn } from "./app.js";
import type { PortfolioQuery, PortfolioTx } from "./portfolioTx.js";
import type { UiClient, UiResponse } from "./uiClient.js";

const SECRET_RT = "SECRET_RT_123";
const SECRET_CODE = "SECRET_CODE_789";
const SECRET_STATE = "SECRET_STATE_456";

function collectingStream() {
  let text = "";
  const stream = new Writable({
    write(chunk, _encoding, callback) {
      text += chunk.toString();
      callback();
    },
  });
  return { stream, output: () => text };
}

function buildCallbackApp(stream: Writable) {
  const secrets = {
    get: vi.fn(async (_name: string): Promise<string | undefined> => undefined),
    invalidate: vi.fn((_name: string): void => undefined),
  };
  const uiRequest = vi.fn(async (): Promise<UiResponse> => ({ status: 0, body: null }));
  const uiClient: UiClient = { request: uiRequest };
  const query = (async () => ({ rows: [] })) as unknown as QueryFn;
  const portfolioTx = vi.fn(async (work: (q: PortfolioQuery) => Promise<unknown>) =>
    work((async () => ({ rowCount: 1 })) as PortfolioQuery),
  ) as unknown as PortfolioTx;
  return buildApp({
    query,
    portfolioTx,
    logger: { stream },
    broker: { secrets, uiClient, returnUrl: "http://127.0.0.1:5173/" },
  });
}

describe("broker callback request log", () => {
  it("never logs the callback query strings", async () => {
    const { stream, output } = collectingStream();
    const app = buildCallbackApp(stream);

    const kite = await app.inject({
      method: "GET",
      url: `/api/broker/kite/callback?request_token=${SECRET_RT}&state=${SECRET_STATE}&status=success`,
    });
    const upstox = await app.inject({
      method: "GET",
      url: `/api/broker/upstox/callback?code=${SECRET_CODE}&state=${SECRET_STATE}`,
    });
    // A failed login: the provider reports an error and no code.
    const failed = await app.inject({
      method: "GET",
      url: `/api/broker/upstox/callback?error=access_denied&state=${SECRET_STATE}`,
    });
    expect(kite.statusCode).toBeLessThan(500);
    expect(upstox.statusCode).toBeLessThan(500);
    expect(failed.statusCode).toBeLessThan(500);
    await app.close();

    const log = output();
    expect(log.length).toBeGreaterThan(0);
    expect(log).toContain("/api/broker/kite/callback");
    expect(log).toContain("/api/broker/upstox/callback");
    expect(log).not.toContain(SECRET_RT);
    expect(log).not.toContain(SECRET_CODE);
    expect(log).not.toContain(SECRET_STATE);
  });
});
