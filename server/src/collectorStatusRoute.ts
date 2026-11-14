import type { FastifyInstance } from "fastify";
import { buildCollectorStatus } from "./collectorStatus.js";

/**
 * GET /api/collector/status (slice S5b): the collector heartbeat as the UI reads it. Behind the
 * session gate like the other /api reads. Registered only when the watchdog wiring exists (app.ts).
 * Responses are no-store.
 */

export interface CollectorStatusRouteDeps {
  getLastDuePollAt: () => Date | null;
  now?: () => Date;
}

export function registerCollectorStatusRoute(app: FastifyInstance, deps: CollectorStatusRouteDeps): void {
  const now = deps.now ?? (() => new Date());

  app.get("/api/collector/status", async (_request, reply) => {
    reply.header("Cache-Control", "no-store");
    return reply.code(200).send(buildCollectorStatus(deps.getLastDuePollAt(), now()));
  });
}
