import type { FastifyInstance } from "fastify";
import type { QueryFn } from "./app.js";
import {
  buildDueQueries,
  computeDue,
  isConnectionError,
  mapDueRows,
  toIstIso,
  type DueRawRows,
  type ServicesFile,
} from "./collectorDue.js";

/**
 * GET /internal/due: the collector watchdog's poll (slice S5a). Order inside the handler is fixed:
 *   1. The bearer token is checked for the collector_watchdog role. Any failure answers 401.
 *   2. The poll time is recorded in memory (the poll is the heartbeat; no DB write).
 *   3. The services file is read (per request), then the five parameter-free queries run.
 *   4. computeDue decides the sources. Errors: 503 for a connection-class DB error, else 500.
 *
 * Error bodies are fixed text: no SQL, path or secret detail. Responses are no-store.
 */

export const COLLECTOR_WATCHDOG_ROLE = "collector_watchdog";

export type CollectorDueAuthResult = "ok" | 401 | 403;

export interface CollectorDueRouteDeps {
  query: QueryFn;
  checkToken: (authorization: string | undefined, role: typeof COLLECTOR_WATCHDOG_ROLE) => CollectorDueAuthResult;
  loadServices: () => ServicesFile;
  now?: () => Date;
}

export interface CollectorDueRoute {
  /** Time of the last authenticated poll, or null before the first one. For the S5b heartbeat. */
  getLastDuePollAt(): Date | null;
}

export function registerCollectorDueRoute(app: FastifyInstance, deps: CollectorDueRouteDeps): CollectorDueRoute {
  const now = deps.now ?? (() => new Date());
  let lastDuePollAt: Date | null = null;

  app.get("/internal/due", async (request, reply) => {
    reply.header("Cache-Control", "no-store");
    if (deps.checkToken(request.headers.authorization, COLLECTOR_WATCHDOG_ROLE) !== "ok") {
      return reply.code(401).send({ error: "unauthorized" });
    }

    const pollAt = now();
    lastDuePollAt = pollAt;

    let services: ServicesFile;
    try {
      services = deps.loadServices();
    } catch {
      return reply.code(500).send({ error: "services_unavailable" });
    }

    try {
      const queries = buildDueQueries();
      const [settings, lastOk, lastAttempt, requests, cooldowns] = await Promise.all([
        deps.query(queries.settings, []),
        deps.query(queries.lastOk, []),
        deps.query(queries.lastAttempt, []),
        deps.query(queries.requests, []),
        deps.query(queries.cooldowns, []),
      ]);
      const raw: DueRawRows = {
        settings: settings.rows,
        lastOk: lastOk.rows,
        lastAttempt: lastAttempt.rows,
        requests: requests.rows,
        cooldowns: cooldowns.rows,
      };
      const result = computeDue({ now: pollAt, services, ...mapDueRows(raw) });
      if (result.skipped.length > 0) {
        request.log.warn({ skipped: result.skipped.length }, "collector due: sources skipped for an invalid cron");
      }
      return reply.code(200).send({ generated_at: toIstIso(pollAt), sources: result.sources });
    } catch (err) {
      if (isConnectionError(err)) {
        return reply.code(503).send({ error: "database_unavailable" });
      }
      return reply.code(500).send({ error: "due_failed" });
    }
  });

  return {
    getLastDuePollAt: () => lastDuePollAt,
  };
}
