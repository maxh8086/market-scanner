import type { FastifyInstance } from "fastify";
import { buildInsert, MAX_BATCH_ROWS, validateBatch } from "./homeEventsBatch.js";

/**
 * POST /internal/events/batch: ingest of home_events rows from the scanner's home_filings collector
 * (spec 4.6). The order inside the handler is fixed:
 *   1. An oversize batch is refused with 413 before auth, so checkToken is not called for it.
 *   2. The bearer token is checked for the home_events_ingest role (401 or 403 on failure).
 *   3. Invalid rows are counted and skipped; they do not fail the batch.
 *   4. The valid rows go in one parameterised INSERT inside eventsTx. ON CONFLICT DO NOTHING means
 *      rows already stored count as duplicates.
 *
 * Row contents are never logged.
 */

export type HomeEventsQuery = (text: string, values: unknown[]) => Promise<{ rowCount: number }>;

export interface HomeEventsRouteDeps {
  checkToken: (authorization: string | undefined, role: "home_events_ingest") => "ok" | 401 | 403;
  eventsTx: <T>(work: (query: HomeEventsQuery) => Promise<T>) => Promise<T>;
}

export function registerHomeEventsRoutes(app: FastifyInstance, deps: HomeEventsRouteDeps): void {
  app.post<{ Body: unknown }>("/internal/events/batch", async (request, reply) => {
    const body = request.body;
    const declaredRows =
      typeof body === "object" && body !== null ? (body as { rows?: unknown }).rows : undefined;
    if (Array.isArray(declaredRows) && declaredRows.length > MAX_BATCH_ROWS) {
      return reply.code(413).send({ error: "batch_too_large" });
    }

    const auth = deps.checkToken(request.headers.authorization, "home_events_ingest");
    if (auth === 401) {
      return reply.code(401).send({ error: "unauthorized" });
    }
    if (auth === 403) {
      return reply.code(403).send({ error: "forbidden" });
    }

    const { rows, invalid } = validateBatch(body);
    let inserted = 0;
    if (rows.length > 0) {
      const built = buildInsert(rows);
      try {
        inserted = await deps.eventsTx(async (query) => {
          const result = await query(built.text, built.values);
          return result.rowCount;
        });
      } catch {
        return reply.code(500).send({ error: "ingest_failed" });
      }
    }

    return reply.code(200).send({ inserted, duplicates: rows.length - inserted, invalid });
  });
}
