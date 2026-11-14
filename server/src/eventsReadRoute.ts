import type { FastifyInstance } from "fastify";
import { isConnectionError, toIstIso } from "./collectorDue.js";
import {
  buildEventsSql,
  buildLatestFetchedSql,
  mapEventRow,
  parseEventsQuery,
  toIsoOrNull,
} from "./eventsRead.js";

export interface EventsQueryResult {
  rows: Array<Record<string, unknown>>;
}

/** Read-only query against the events database (the same shape as the app's QueryFn). */
export type EventsQueryFn = (sql: string, values: unknown[]) => Promise<EventsQueryResult>;

export interface EventsReadRouteDeps {
  eventsQuery: EventsQueryFn;
}

/**
 * GET /api/events. No fastify querystring schema: the querystring is parsed by parseEventsQuery so
 * an invalid value gets the fixed invalid_query body. Every response is no-store and every error body is fixed.
 */
export function registerEventsReadRoute(app: FastifyInstance, deps: EventsReadRouteDeps): void {
  app.get("/api/events", async (request, reply) => {
    reply.header("Cache-Control", "no-store");
    const parsed = parseEventsQuery(request.query as Record<string, unknown>);
    if (!parsed.ok) {
      return reply.code(400).send({ error: "invalid_query" });
    }
    const query = parsed.value;
    try {
      const events = buildEventsSql(query);
      const eventRows = await deps.eventsQuery(events.sql, events.values);
      const latest = buildLatestFetchedSql(query.days);
      const latestRows = await deps.eventsQuery(latest.sql, latest.values);
      return reply.send({
        generated_at: toIstIso(new Date()),
        latest_fetched_at: toIsoOrNull(latestRows.rows[0]?.latest),
        window_days: query.days,
        events: eventRows.rows.map(mapEventRow),
      });
    } catch (err) {
      if (isConnectionError(err)) {
        request.log.warn("events read: events database unavailable");
        return reply.code(503).send({ error: "events_database_unavailable" });
      }
      request.log.error("events read failed");
      return reply.code(500).send({ error: "internal_error" });
    }
  });
}
