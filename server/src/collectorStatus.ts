import { toIstIso } from "./collectorDue.js";

/**
 * Pure collector status for GET /api/collector/status (slice S5b). The watchdog polls /internal/due
 * every 60 s, so no poll for more than 3 minutes means the collector is paused. No I/O here: the
 * route injects the last poll time and the clock.
 */

export const COLLECTOR_PAUSED_AFTER_MS = 180_000;

export interface CollectorStatusBody {
  collector: {
    paused: boolean;
    since: string | null;
  };
}

export function buildCollectorStatus(lastPollAt: Date | null, now: Date): CollectorStatusBody {
  if (lastPollAt === null) {
    return { collector: { paused: true, since: null } };
  }
  const paused = now.getTime() - lastPollAt.getTime() > COLLECTOR_PAUSED_AFTER_MS;
  return { collector: { paused, since: toIstIso(lastPollAt) } };
}
