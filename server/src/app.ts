import Fastify, { type FastifyInstance, type FastifyReply } from "fastify";
import {
  buildCountQuery,
  buildLatestRunQuery,
  buildResultsQuery,
  buildRunLookupQuery,
  formatRunDate,
  isIsoDate,
  normalizePaging,
  type ResultsParams,
} from "./results.js";
import {
  buildFilterOptionsQuery,
  shapeFilterOptions,
} from "./filterOptions.js";
import {
  buildSectorSummaryQuery,
  shapeSectorSummary,
  validateSectorPeriod,
} from "./sectorSummary.js";
import {
  buildCandlesQuery,
  shapeCandles,
  validateCandlesRequest,
} from "./candles.js";
import {
  buildRecentClosesQuery,
  shapeRecentCloses,
  validateRecentClosesRequest,
} from "./recentCloses.js";
import {
  buildDeletePresetQuery,
  buildInsertPresetQuery,
  buildListPresetsQuery,
  validatePresetInput,
} from "./presets.js";
import { buildIndexEodQuery, shapeIndexEod } from "./indexEod.js";
import { registerCollectorRefreshRoute } from "./collectorRefresh.js";
import { createSessionStore, registerCsrfGate, registerSessionRoutes, type SessionStore } from "./session.js";
import { registerHomeEventsRoutes, type HomeEventsRouteDeps } from "./homeEventsRoute.js";
import { registerCollectorDueRoute, type CollectorDueRouteDeps } from "./collectorDueRoute.js";
import {
  buildIsinLookupQuery,
  createWsSocket,
  formatSseEvent,
  INDEX_INSTRUMENT_KEYS,
  nseEquityKey,
  parseIndexNames,
  parseLiveSymbols,
} from "./live/liveRoute.js";
import { createLiveFeed, type FeedListeners, type FeedMode, type FeedStatus, type LiveFeed } from "./live/upstoxFeed.js";
import { registerBrokerRoutes, type BrokerAppDeps } from "./broker/brokerRoutes.js";
import type { PortfolioTx } from "./portfolioTx.js";

export interface QueryResult {
  rows: Array<Record<string, unknown>>;
}

export type QueryFn = (sql: string, values: unknown[]) => Promise<QueryResult>;

export type CreateFeedFn = (options: {
  accessToken: string | undefined;
  instrumentKeys: string[];
  mode?: FeedMode;
  listeners: FeedListeners;
}) => LiveFeed;

export interface LiveDeps {
  /** Upstox access token. When absent the live route streams nothing and reports "unconfigured". */
  accessToken?: string;
  /** Preferred over accessToken: resolved once per live request. A rejection counts as unconfigured. */
  getAccessToken?: () => Promise<string | undefined>;
  /** Feed factory. Tests inject a fake; production uses the Upstox WebSocket client. */
  createFeed?: CreateFeedFn;
}

export interface AppDeps {
  query: QueryFn;
  logger?: boolean;
  live?: LiveDeps;
  /** Broker login and holdings routes. Off unless both broker and portfolioTx are set. */
  broker?: BrokerAppDeps;
  portfolioTx?: PortfolioTx;
  /** Home events ingest (POST /internal/events/batch). The route is registered only when both are set. */
  checkToken?: HomeEventsRouteDeps["checkToken"];
  eventsTx?: HomeEventsRouteDeps["eventsTx"];
  /** Collector watchdog poll (GET /internal/due). The route is registered only when set. */
  collectorDue?: Pick<CollectorDueRouteDeps, "checkToken" | "loadServices" | "now">;
  /** Session store for the browser write gate. A fresh in-memory store is created when omitted. */
  sessions?: SessionStore;
}

const defaultCreateFeed: CreateFeedFn = (options) =>
  createLiveFeed({
    ...options,
    deps: {
      fetch: (url, init) => fetch(url, init),
      createSocket: createWsSocket,
      setTimer: (fn, ms) => setTimeout(fn, ms),
      clearTimer: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
    },
  });

const HEARTBEAT_MS = 15_000;

type ResultsQueryString = Omit<ResultsParams, "runId">;

const resultsQuerySchema = {
  type: "object",
  properties: {
    page: { type: "integer", minimum: 1 },
    perPage: { type: "integer", minimum: 1, maximum: 100 },
    sort: { type: "string", maxLength: 64 },
    order: { type: "string", enum: ["asc", "desc"] },
    bucket: { type: "string", maxLength: 64 },
    stance: { type: "string", maxLength: 64 },
    search: { type: "string", maxLength: 128 },
    industry: { type: "string", maxLength: 128 },
    ltpMin: { type: "number" },
    ltpMax: { type: "number" },
    distanceMin: { type: "number" },
    distanceMax: { type: "number" },
    athFrom: { type: "string", maxLength: 10 },
    athTo: { type: "string", maxLength: 10 },
  },
} as const;

export function buildApp(deps: AppDeps): FastifyInstance {
  const app = Fastify({ logger: deps.logger ?? false });
  const sessions = deps.sessions ?? createSessionStore();
  registerSessionRoutes(app, sessions);
  registerCsrfGate(app, sessions);

  app.get("/api/health", async () => ({ ok: true }));

  // Registered before any /api/runs/:runId route so "latest" is not read as an id.
  app.get("/api/runs/latest", async (_request, reply) => {
    const latest = buildLatestRunQuery();
    const found = await deps.query(latest.sql, latest.values);
    const row = found.rows[0];
    if (!row) {
      return reply.code(404).send({ error: "No current run" });
    }
    const runDate = formatRunDate(row.run_date);
    return { runId: String(row.run_id), runDate };
  });

  app.get<{ Params: { runId: string }; Querystring: ResultsQueryString }>(
    "/api/runs/:runId/results",
    { schema: { querystring: resultsQuerySchema } },
    async (request, reply) => {
      const lookup = buildRunLookupQuery(request.params.runId);
      if (!lookup) {
        return reply.code(404).send({ error: "Run not found" });
      }

      for (const field of ["athFrom", "athTo"] as const) {
        const value = request.query[field];
        if (value && !isIsoDate(value)) {
          return reply.code(400).send({ error: `Invalid ${field}` });
        }
      }

      const found = await deps.query(lookup.sql, lookup.values);
      const resolvedRunId = found.rows[0]?.run_id;
      if (resolvedRunId === undefined || resolvedRunId === null) {
        return reply.code(404).send({ error: "Run not found" });
      }

      const params: ResultsParams = { ...request.query, runId: String(resolvedRunId) };
      const { page, perPage } = normalizePaging(request.query.page, request.query.perPage);
      const rowsQuery = buildResultsQuery(params);
      const countQuery = buildCountQuery(params);

      const [rowsResult, countResult] = await Promise.all([
        deps.query(rowsQuery.sql, rowsQuery.values),
        deps.query(countQuery.sql, countQuery.values),
      ]);

      return {
        results: rowsResult.rows,
        total: Number(countResult.rows[0]?.total ?? 0),
        page,
        perPage,
      };
    },
  );

  // Distinct bucket and stance values for a run. An unknown or malformed run id
  // returns empty lists (no 404), so the UI can show empty dropdowns.
  app.get<{ Params: { runId: string } }>(
    "/api/runs/:runId/filter-options",
    async (request) => {
      const empty = { bucket: [], stance: [] };
      const lookup = buildRunLookupQuery(request.params.runId);
      if (!lookup) return empty;

      const found = await deps.query(lookup.sql, lookup.values);
      const resolvedRunId = found.rows[0]?.run_id;
      if (resolvedRunId === undefined || resolvedRunId === null) return empty;

      const options = buildFilterOptionsQuery(String(resolvedRunId));
      const result = await deps.query(options.sql, options.values);
      return shapeFilterOptions(result.rows);
    },
  );

  // Per-sector average price change over a period (default "1d"). An invalid
  // period returns 400 before any SQL runs. An unknown or malformed run id
  // returns an empty sector list (no 404), like filter-options.
  app.get<{ Params: { runId: string }; Querystring: { period?: unknown } }>(
    "/api/runs/:runId/sector-summary",
    async (request, reply) => {
      const checked = validateSectorPeriod(request.query.period);
      if (!checked.ok) {
        return reply.code(400).send({ error: checked.error });
      }
      const period = checked.value;
      const empty = { period, sectors: [] };
      const lookup = buildRunLookupQuery(request.params.runId);
      if (!lookup) return empty;

      const found = await deps.query(lookup.sql, lookup.values);
      const resolvedRunId = found.rows[0]?.run_id;
      if (resolvedRunId === undefined || resolvedRunId === null) return empty;

      const summary = buildSectorSummaryQuery(String(resolvedRunId), period);
      const result = await deps.query(summary.sql, summary.values);
      return shapeSectorSummary(result.rows, period);
    },
  );

  // Daily candles for one symbol. Unknown symbols return an empty list, not 404.
  app.get<{
    Params: { symbol: string };
    Querystring: { from?: unknown; to?: unknown; limit?: unknown };
  }>("/api/stocks/:symbol/candles", async (request, reply) => {
    const checked = validateCandlesRequest({ symbol: request.params.symbol, ...request.query });
    if (!checked.ok) {
      return reply.code(400).send({ error: checked.error });
    }
    const query = buildCandlesQuery(checked.value);
    const found = await deps.query(query.sql, query.values);
    return shapeCandles(checked.value.symbol, found.rows);
  });

  // Last N daily closes for many symbols in one call, for the scan table sparklines.
  // Symbols with no stored candles are missing from the map, not 404.
  app.get<{ Querystring: { symbols?: unknown; limit?: unknown } }>(
    "/api/recent-closes",
    async (request, reply) => {
      const checked = validateRecentClosesRequest(request.query);
      if (!checked.ok) {
        return reply.code(400).send({ error: checked.error });
      }
      const query = buildRecentClosesQuery(checked.value);
      const found = await deps.query(query.sql, query.values);
      return shapeRecentCloses(found.rows);
    },
  );

  // Saved scan presets. The write path validates every field before any SQL runs.
  app.get("/api/presets", async () => {
    const listing = buildListPresetsQuery();
    const found = await deps.query(listing.sql, listing.values);
    return { presets: found.rows };
  });

  app.post<{ Body: unknown }>("/api/presets", async (request, reply) => {
    const checked = validatePresetInput(request.body);
    if (!checked.ok) {
      return reply.code(400).send({ error: checked.error });
    }
    const insert = buildInsertPresetQuery(checked.value);
    const created = await deps.query(insert.sql, insert.values);
    return reply.code(201).send(created.rows[0]);
  });

  app.delete<{ Params: { presetId: string } }>(
    "/api/presets/:presetId",
    async (request, reply) => {
      const checked = buildDeletePresetQuery(request.params.presetId);
      if (!checked.ok) {
        return reply.code(400).send({ error: checked.error });
      }
      const removed = await deps.query(checked.value.sql, checked.value.values);
      if (removed.rows.length === 0) {
        return reply.code(404).send({ error: "Preset not found" });
      }
      return reply.code(204).send();
    },
  );

  // Last two stored end-of-day closes per benchmark index, for Market Watch outside market hours.
  app.get("/api/index-eod", async () => {
    const query = buildIndexEodQuery();
    const found = await deps.query(query.sql, query.values);
    return shapeIndexEod(found.rows);
  });

  // Manual EOD refresh for the index_eod collector (refused on trading days before 15:30 IST).
  registerCollectorRefreshRoute(app, deps.query);

  // Home events ingest from the scanner's home_filings collector. Off unless the caller wires a token check and a transaction.
  if (deps.checkToken && deps.eventsTx) {
    registerHomeEventsRoutes(app, { checkToken: deps.checkToken, eventsTx: deps.eventsTx });
  }

  // Collector watchdog poll (S5a). Off unless the caller wires a token check and a services loader.
  if (deps.collectorDue) {
    registerCollectorDueRoute(app, { query: deps.query, ...deps.collectorDue });
  }

  // Broker login (ui-mediated) and stored holdings: GET /api/holdings reads the last ok snapshot, and
  // POST /api/holdings/sync is the only route that calls Kite. Live prices are NOT taken from here (Upstox).
  if (deps.broker && deps.portfolioTx) {
    registerBrokerRoutes(app, { ...deps.broker, query: deps.query, portfolioTx: deps.portfolioTx });
  }

  // Server-sent index quotes: LTP, previous close, and the day's open, high and low (full feed mode).
  // `symbols` (comma-separated watchlist names) limits the subscription to the rows on screen; without
  // it every mapped index is subscribed. Events match /api/live/ticks: `status`, `tick`, `heartbeat`.
  app.get<{ Querystring: { symbols?: unknown } }>("/api/live/indices", async (request, reply) => {
    let names: string[] = Object.keys(INDEX_INSTRUMENT_KEYS);
    if (request.query.symbols !== undefined) {
      const parsed = parseIndexNames(request.query.symbols);
      if (!parsed.ok) {
        return reply.code(400).send({ error: parsed.error });
      }
      names = parsed.names;
    }
    const symbolByKey = new Map(names.map((name) => [INDEX_INSTRUMENT_KEYS[name] as string, name]));
    const createFeed = deps.live?.createFeed ?? defaultCreateFeed;
    const accessToken = await resolveLiveToken(deps.live);
    if (clientGone(reply)) return reply;
    streamLiveFeed(reply, (listeners) =>
      createFeed({
        accessToken,
        instrumentKeys: [...symbolByKey.keys()],
        mode: "full",
        listeners: {
          onTick: (tick) => {
            const symbol = symbolByKey.get(tick.instrumentKey);
            if (symbol) {
              listeners.onTick({ symbol, ltp: tick.ltp, ltt: tick.ltt, cp: tick.cp, open: tick.open ?? null, high: tick.high ?? null, low: tick.low ?? null });
            }
          },
          onStatus: listeners.onStatus,
        },
      }),
    );
    return reply;
  });

  // Server-sent live last-traded prices for a bounded symbol list in one run. Symbols map to Upstox
  // instrument keys through stock_snapshots.isin. Events: `status` (feed state), `tick` (one price).
  // The browser never sees the Upstox token or talks to Upstox directly.
  app.get<{ Querystring: { runId?: unknown; symbols?: unknown } }>(
    "/api/live/ticks",
    async (request, reply) => {
      const parsed = parseLiveSymbols(request.query.symbols);
      if (!parsed.ok) {
        return reply.code(400).send({ error: parsed.error });
      }
      const runId = typeof request.query.runId === "string" ? request.query.runId : "";
      const lookup = buildRunLookupQuery(runId);
      if (!lookup) {
        return reply.code(404).send({ error: "Run not found" });
      }
      const found = await deps.query(lookup.sql, lookup.values);
      const resolvedRunId = found.rows[0]?.run_id;
      if (resolvedRunId === undefined || resolvedRunId === null) {
        return reply.code(404).send({ error: "Run not found" });
      }

      const isins = buildIsinLookupQuery(String(resolvedRunId), parsed.symbols);
      const isinRows = await deps.query(isins.sql, isins.values);
      const symbolByKey = new Map<string, string>();
      for (const row of isinRows.rows) {
        if (row.symbol && row.isin) {
          symbolByKey.set(nseEquityKey(String(row.isin)), String(row.symbol));
        }
      }
      if (symbolByKey.size === 0) {
        return reply.code(404).send({ error: "No instruments found for symbols" });
      }

      const createFeed = deps.live?.createFeed ?? defaultCreateFeed;
      const accessToken = await resolveLiveToken(deps.live);
      if (clientGone(reply)) return reply;
      streamLiveFeed(reply, (listeners) =>
        createFeed({
          accessToken,
          instrumentKeys: [...symbolByKey.keys()],
          listeners: {
            onTick: (tick) => {
              const symbol = symbolByKey.get(tick.instrumentKey);
              if (symbol) {
                listeners.onTick({ symbol, ltp: tick.ltp, ltt: tick.ltt, cp: tick.cp });
              }
            },
            onStatus: listeners.onStatus,
          },
        }),
      );
      return reply;
    },
  );

  return app;
}

/** Token for one live request: getAccessToken wins when set; a rejection means unconfigured. */
async function resolveLiveToken(live: LiveDeps | undefined): Promise<string | undefined> {
  if (live?.getAccessToken) {
    try {
      return (await live.getAccessToken()) || undefined;
    } catch {
      return undefined;
    }
  }
  return live?.accessToken;
}

/** True when the browser left while an async step ran, so no stream should start. */
function clientGone(reply: FastifyReply): boolean {
  return reply.raw.destroyed || (reply.raw.socket?.destroyed ?? false);
}

interface SseListeners {
  onTick: (payload: object) => void;
  onStatus: (status: FeedStatus) => void;
}

/** Opens a server-sent event stream, starts the feed it builds, and closes the feed when the browser leaves. */
function streamLiveFeed(reply: FastifyReply, makeFeed: (listeners: SseListeners) => LiveFeed): void {
  reply.hijack();
  reply.raw.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });

  let closed = false;
  const write = (chunk: string) => {
    if (!closed) reply.raw.write(chunk);
  };
  const feed = makeFeed({
    onTick: (payload) => write(formatSseEvent("tick", payload)),
    onStatus: (status) => write(formatSseEvent("status", { status })),
  });

  // A named event, not a comment: the browser EventSource API does not expose comment lines,
  // so the client needs an event it can watch for silence.
  const heartbeat = setInterval(() => write(formatSseEvent("heartbeat", { ts: Date.now() })), HEARTBEAT_MS);
  // ServerResponse 'close' fires when the browser disconnects; request 'close' can fire early for GET.
  reply.raw.on("close", () => {
    closed = true;
    clearInterval(heartbeat);
    feed.stop();
  });

  write(formatSseEvent("status", { status: feed.status() }));
  feed.start();
}
