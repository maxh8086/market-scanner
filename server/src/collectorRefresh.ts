import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import type { QueryFn } from "./app.js";

/**
 * Manual "Refresh EOD" request for the index_eod collector source. Inserts one unclaimed row into
 * collector_requests; the scanner scheduler claims it on its next poll. The insert uses the same
 * shape as scanner/collect/settings.py request_run(): at most one unclaimed request per source.
 *
 * Post-market rule (server side): on a weekday, before 15:30 IST, the request is refused with 409.
 * Weekends are allowed at any time. There is no holiday list here; the UI handles holidays.
 */

export interface Built {
  sql: string;
  values: unknown[];
}

export const INDEX_EOD_SOURCE = "index_eod";
export const MARKET_CLOSE_MINUTES_IST = 15 * 60 + 30;
export const MARKET_HOURS_MESSAGE = "Refresh opens after 15:30 IST on trading days.";

const ist = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Kolkata",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** True when the given instant is a weekday in IST before 15:30 (the session is still running or not started). */
export function isBeforeCloseOnTradingDayIst(now: Date): boolean {
  const parts = Object.fromEntries(ist.formatToParts(now).map((part) => [part.type, part.value]));
  if (parts.weekday === "Sat" || parts.weekday === "Sun") return false;
  const minutes = Number(parts.hour) * 60 + Number(parts.minute);
  return minutes < MARKET_CLOSE_MINUTES_IST;
}

/** Inserts one request. ON CONFLICT DO NOTHING; RETURNING id gives a row only when a request was inserted. */
export function buildIndexEodRefreshInsert(id: string): Built {
  return {
    sql: "INSERT INTO collector_requests (id, source, requested_at) VALUES ($1, $2, now()) ON CONFLICT DO NOTHING RETURNING id",
    values: [id, INDEX_EOD_SOURCE],
  };
}

/**
 * How long the collector waits between polls for queued requests (collect.py sleeps 60 s). A queued
 * refresh can wait up to this long before the run starts.
 */
export const COLLECTOR_PICKUP_SECONDS = 60;

/**
 * Finish time and duration of the latest successful index_eod run, manual or scheduled. Both come from
 * collector_runs, so the UI shows what the database recorded, not the browser's clock.
 */
export function buildLastIndexEodRunQuery(): Built {
  return {
    sql: "SELECT finished_at, EXTRACT(EPOCH FROM (finished_at - started_at)) AS duration_seconds FROM collector_runs WHERE source = $1 AND status = 'ok' AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1",
    values: [INDEX_EOD_SOURCE],
  };
}

/** Converts the driver's timestamp value to an ISO string, or null when there is no usable value. */
export function lastRefreshedAtFromRow(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const date = value instanceof Date ? value : new Date(String(value));
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** Run duration in whole seconds from the driver's value (a numeric string or number), or null. */
export function lastRunSecondsFromRow(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? Math.round(seconds) : null;
}

/** POST /api/collector/index-eod/refresh: queues one manual index_eod run. GET .../status: last finished run. */
export function registerCollectorRefreshRoute(app: FastifyInstance, query: QueryFn): void {
  app.get("/api/collector/index-eod/status", async (_request, reply) => {
    try {
      const lookup = buildLastIndexEodRunQuery();
      const found = await query(lookup.sql, lookup.values);
      const row = found.rows[0] as { finished_at?: unknown; duration_seconds?: unknown } | undefined;
      return reply.code(200).send({
        lastRefreshedAt: lastRefreshedAtFromRow(row?.finished_at),
        lastRunSeconds: lastRunSecondsFromRow(row?.duration_seconds),
        pickupSeconds: COLLECTOR_PICKUP_SECONDS,
      });
    } catch {
      return reply.code(500).send({ error: "Could not read the last refresh time." });
    }
  });

  app.post("/api/collector/index-eod/refresh", async (_request, reply) => {
    if (isBeforeCloseOnTradingDayIst(new Date())) {
      return reply.code(409).send({ error: "market_hours", message: MARKET_HOURS_MESSAGE });
    }
    try {
      const insert = buildIndexEodRefreshInsert(randomUUID());
      const found = await query(insert.sql, insert.values);
      if (found.rows.length > 0) {
        return reply.code(202).send({ queued: true });
      }
      return reply.code(200).send({ queued: false, message: "A refresh is already queued." });
    } catch {
      return reply.code(500).send({ error: "Could not queue the refresh." });
    }
  });
}
