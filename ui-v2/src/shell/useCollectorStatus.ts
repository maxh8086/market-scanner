import { useEffect, useState } from "react";
import { CollectorStatusError, fetchCollectorStatus } from "../api/collectorStatus";

/**
 * Collector pause flag for the top bar banner (slice S5b). Polls GET /api/collector/status on mount and
 * every COLLECTOR_STATUS_POLL_MS. `paused` is true when the last answer said so, or after
 * COLLECTOR_FAILURE_LIMIT failed requests in a row (network error or 5xx). A 404 means no collector
 * wiring: polling stops and paused stays false. Other 4xx answers keep the last value.
 */

export const COLLECTOR_STATUS_POLL_MS = 60_000;
export const COLLECTOR_FAILURE_LIMIT = 3;

export interface CollectorStatusState {
  paused: boolean;
}

export function useCollectorStatus(): CollectorStatusState {
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const schedule = () => {
      timer = setTimeout(() => {
        void poll();
      }, COLLECTOR_STATUS_POLL_MS);
    };

    async function poll(): Promise<void> {
      try {
        const status = await fetchCollectorStatus({ signal: controller.signal });
        if (!active) return;
        failures = 0;
        setPaused(status.paused);
      } catch (error) {
        if (!active || controller.signal.aborted) return;
        if (error instanceof CollectorStatusError) {
          if (error.status === 404) {
            setPaused(false);
            return;
          }
          if (error.status === null || error.status >= 500) {
            failures += 1;
            if (failures >= COLLECTOR_FAILURE_LIMIT) {
              setPaused(true);
            }
          }
        }
      }
      if (active) schedule();
    }

    void poll();

    return () => {
      active = false;
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, []);

  return { paused };
}
