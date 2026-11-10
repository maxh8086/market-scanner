import Fastify, { type FastifyInstance } from "fastify";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MAX_BATCH_ROWS } from "./homeEventsBatch.js";
import { registerHomeEventsRoutes } from "./homeEventsRoute.js";

type Query = (text: string, values: unknown[]) => Promise<{ rowCount: number }>;

interface Deps {
  checkToken: (authorization: string | undefined, role: "home_events_ingest") => "ok" | 401 | 403;
  eventsTx: <T>(work: (query: Query) => Promise<T>) => Promise<T>;
}

const apps: FastifyInstance[] = [];

afterEach(async () => {
  await Promise.all(apps.splice(0).map((app) => app.close()));
});

function validRow(index = 0, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    dedupe_key: `nse:Financial_Results:${index}`,
    exchange: "NSE",
    feed_code: "nse:Financial_Results",
    source_id: String(index),
    source_url: "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
    isin: "INE000000001",
    symbol: "ABC",
    company: "ABC Ltd",
    event_type: "results",
    feed_tier: "high_priority",
    headline: "Quarterly results for the period",
    published_at: "2026-11-09T16:30:00+05:30",
    ...overrides,
  };
}

async function buildTestApp(deps: Deps): Promise<FastifyInstance> {
  const app = Fastify();
  registerHomeEventsRoutes(app, deps);
  await app.ready();
  apps.push(app);
  return app;
}

// One fake transaction: the spy records calls; deps is the same callable typed as Deps["eventsTx"].
function fakeEventsTx(query: Query) {
  const spy = vi.fn(async (work: (q: Query) => Promise<unknown>) => work(query));
  return { spy, deps: spy as Deps["eventsTx"] };
}

describe("POST /internal/events/batch", () => {
  it("missing_token_401", async () => {
    const checkToken = vi.fn<Deps["checkToken"]>((authorization) => (authorization === undefined ? 401 : "ok"));
    const tx = fakeEventsTx(vi.fn<Query>(async () => ({ rowCount: 1 })));
    const app = await buildTestApp({ checkToken, eventsTx: tx.deps });

    const response = await app.inject({
      method: "POST",
      url: "/internal/events/batch",
      payload: { rows: [validRow()] },
    });

    expect(response.statusCode).toBe(401);
    expect(checkToken).toHaveBeenCalledWith(undefined, "home_events_ingest");
    expect(tx.spy).not.toHaveBeenCalled();
  });

  it("wrong_role_403", async () => {
    const checkToken = vi.fn<Deps["checkToken"]>(() => 403);
    const tx = fakeEventsTx(vi.fn<Query>(async () => ({ rowCount: 1 })));
    const app = await buildTestApp({ checkToken, eventsTx: tx.deps });

    const response = await app.inject({
      method: "POST",
      url: "/internal/events/batch",
      headers: { authorization: "Bearer test-token" },
      payload: { rows: [validRow()] },
    });

    expect(response.statusCode).toBe(403);
    expect(tx.spy).not.toHaveBeenCalled();
  });

  it("valid_batch_returns_counts", async () => {
    const checkToken = vi.fn<Deps["checkToken"]>(() => "ok");
    const query = vi.fn<Query>(async () => ({ rowCount: 1 }));
    const tx = fakeEventsTx(query);
    const app = await buildTestApp({ checkToken, eventsTx: tx.deps });

    const response = await app.inject({
      method: "POST",
      url: "/internal/events/batch",
      headers: { authorization: "Bearer test-token" },
      payload: {
        rows: [validRow(1), validRow(2, { event_type: "not_a_real_event_type" })],
      },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({ inserted: 1, duplicates: 0, invalid: 1 });
    expect(checkToken).toHaveBeenCalledWith("Bearer test-token", "home_events_ingest");
    expect(tx.spy).toHaveBeenCalledTimes(1);
    expect(query).toHaveBeenCalledTimes(1);
  });

  it("oversize_413", async () => {
    const checkToken = vi.fn<Deps["checkToken"]>(() => "ok");
    const tx = fakeEventsTx(vi.fn<Query>(async () => ({ rowCount: 1 })));
    const app = await buildTestApp({ checkToken, eventsTx: tx.deps });

    const rows = Array.from({ length: MAX_BATCH_ROWS + 1 }, (_, index) => validRow(index));
    expect(rows).toHaveLength(501);

    const response = await app.inject({
      method: "POST",
      url: "/internal/events/batch",
      headers: { authorization: "Bearer test-token" },
      payload: { rows },
    });

    expect(response.statusCode).toBe(413);
    expect(checkToken).not.toHaveBeenCalled();
    expect(tx.spy).not.toHaveBeenCalled();
  });
});
