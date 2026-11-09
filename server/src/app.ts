import Fastify, { type FastifyInstance } from "fastify";
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
  buildDeletePresetQuery,
  buildInsertPresetQuery,
  buildListPresetsQuery,
  validatePresetInput,
} from "./presets.js";
import {
  buildIsinLookupQuery,
  createWsSocket,
  formatSseEvent,
  nseEquityKey,
  parseLiveSymbols,
} from "./live/liveRoute.js";
import { createLiveFeed, type FeedListeners, type LiveFeed } from "./live/upstoxFeed.js";

export interface QueryResult {
  rows: Array<Record<string, unknown>>;
}

export type QueryFn = (sql: string, values: unknown[]) => Promise<QueryResult>;

export type CreateFeedFn = (options: {
  accessToken: string | undefined;
  instrumentKeys: string[];
  listeners: FeedListeners;
}) => LiveFeed;

export interface LiveDeps {
  /** Upstox access token. When absent the live route streams nothing and reports "unconfigured". */
  accessToken?: string;
  /** Feed factory. Tests inject a fake; production uses the Upstox WebSocket client. */
  createFeed?: CreateFeedFn;
}

export interface AppDeps {
  query: QueryFn;
  logger?: boolean;
  live?: LiveDeps;
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
      const createFeed = deps.live?.createFeed ?? defaultCreateFeed;
      const feed = createFeed({
        accessToken: deps.live?.accessToken,
        instrumentKeys: [...symbolByKey.keys()],
        listeners: {
          onTick: (tick) => {
            const symbol = symbolByKey.get(tick.instrumentKey);
            if (symbol) {
              write(formatSseEvent("tick", { symbol, ltp: tick.ltp, ltt: tick.ltt, cp: tick.cp }));
            }
          },
          onStatus: (status) => write(formatSseEvent("status", { status })),
        },
      });

      const heartbeat = setInterval(() => write(": ping\n\n"), HEARTBEAT_MS);
      // ServerResponse 'close' fires when the browser disconnects; request 'close' can fire early for GET.
      reply.raw.on("close", () => {
        closed = true;
        clearInterval(heartbeat);
        feed.stop();
      });

      write(formatSseEvent("status", { status: feed.status() }));
      feed.start();
      return reply;
    },
  );

  return app;
}
