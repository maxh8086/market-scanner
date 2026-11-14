import type { FastifyInstance } from "fastify";
import type { QueryFn } from "./app.js";
import { isConnectionError, type ServicesFile } from "./collectorDue.js";
import { COLLECTOR_WATCHDOG_ROLE, type CollectorDueRouteDeps } from "./collectorDueRoute.js";

/**
 * POST /internal/due/finish: the collector watchdog reports that it stopped a collector container that ran
 * past its max runtime (slice S4). The server marks the newest running row of that source as failed.
 *   1. The bearer token is checked for the collector_watchdog role. Any failure answers 401.
 *   2. The body must be {"source": "<name>"}: a non-empty string of at most 100 characters matching /^[a-z0-9_]+$/.
 *   3. The services file is read (per request) and the source must be one of its keys.
 *   4. ONE parameterised UPDATE runs. The source is a bound parameter, never interpolated.
 * It does not touch the poll heartbeat (only GET /internal/due records the poll time).
 *
 * Error bodies are fixed text: no SQL, path or secret detail. Responses are no-store.
 */

export const SOURCE_MAX_LENGTH = 100;
const SOURCE_PATTERN = /^[a-z0-9_]+$/;

/** Marks the newest running run of one source as failed. Only a row still running is changed. */
export const FINISH_KILLED_SQL =
  "UPDATE collector_runs SET status = 'failed', finished_at = now(), message = 'killed' " +
  "WHERE id = (SELECT id FROM collector_runs WHERE source = $1 AND status = 'running' " +
  "ORDER BY started_at DESC LIMIT 1) AND status = 'running' RETURNING id";

export type CollectorFinishRouteDeps = Pick<CollectorDueRouteDeps, "checkToken" | "loadServices"> & {
  query: QueryFn;
};

/** The source name from the body, or null when the body is not valid. */
export function readFinishSource(body: unknown): string | null {
  if (typeof body !== "object" || body === null || Array.isArray(body)) return null;
  const source = (body as { source?: unknown }).source;
  if (typeof source !== "string" || source.length === 0 || source.length > SOURCE_MAX_LENGTH) return null;
  return SOURCE_PATTERN.test(source) ? source : null;
}

export function registerCollectorFinishRoute(app: FastifyInstance, deps: CollectorFinishRouteDeps): void {
  app.post<{ Body: unknown }>("/internal/due/finish", async (request, reply) => {
    reply.header("Cache-Control", "no-store");
    if (deps.checkToken(request.headers.authorization, COLLECTOR_WATCHDOG_ROLE) !== "ok") {
      return reply.code(401).send({ error: "unauthorized" });
    }

    const source = readFinishSource(request.body);
    if (source === null) {
      return reply.code(400).send({ error: "invalid_body" });
    }

    let services: ServicesFile;
    try {
      services = deps.loadServices();
    } catch {
      return reply.code(500).send({ error: "services_unavailable" });
    }
    if (!Object.prototype.hasOwnProperty.call(services.sources, source)) {
      return reply.code(400).send({ error: "unknown_source" });
    }

    try {
      const result = await deps.query(FINISH_KILLED_SQL, [source]);
      return reply.code(200).send({ finalised: result.rows.length });
    } catch (err) {
      if (isConnectionError(err)) {
        return reply.code(503).send({ error: "database_unavailable" });
      }
      return reply.code(500).send({ error: "finish_failed" });
    }
  });
}
