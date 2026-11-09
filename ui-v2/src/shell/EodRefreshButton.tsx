import { useEffect, useRef, useState } from "react";
import { fetchIndexEodStatus, requestIndexEodRefresh, type IndexEodStatus } from "../api/collectorRefresh";
import { getMarketSession } from "../lib/marketSession";

type RefreshState = "idle" | "sending" | "queued" | "already_queued" | "updated" | "market_open" | "error";

const DISABLED_TITLE = "Available after market close (15:30 IST) on trading days";
const CLOCK_TICK_MS = 60_000;
/** Countdown redraw interval while a refresh is waiting. */
const PROGRESS_TICK_MS = 1_000;
/** While a refresh is waiting, the database status is re-read this often until the timestamp changes. */
const STATUS_POLL_MS = 5_000;
/** Run length assumed when the database has no successful run to measure. */
const DEFAULT_RUN_SECONDS = 60;
/** After the countdown ends, how long to say "Wait a few more seconds" before "About to finish". */
const EXTRA_WAIT_MS = 30_000;
/** After this long without an update, the message says the collector may be busy. */
const GIVE_UP_MS = 10 * 60_000;

const istFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata",
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** "09 Nov 2026, 15:52 IST" for an ISO instant from the database. Empty string for an invalid value. */
export function formatIstTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${istFormat.format(date)} IST`;
}

/**
 * Expected seconds from queuing to new prices: the longest pickup wait the collector can add, plus the
 * duration of the last successful run. Both values come from the database.
 */
export function estimateSeconds(status: Pick<IndexEodStatus, "lastRunSeconds" | "pickupSeconds"> | null): number {
  const pickup = status?.pickupSeconds ?? 60;
  const run = status?.lastRunSeconds ?? DEFAULT_RUN_SECONDS;
  return pickup + run;
}

/** "m:ss" for a remaining duration in milliseconds, rounded up so the countdown never shows 0:00 early. */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** The waiting message for a queued refresh, given how long it has been waiting. */
export function queuedProgressText(elapsedMs: number, etaSeconds: number): string {
  const remainingMs = etaSeconds * 1000 - elapsedMs;
  if (remainingMs > 0) return `Estimated ${formatCountdown(remainingMs)} left.`;
  if (elapsedMs < etaSeconds * 1000 + EXTRA_WAIT_MS) return "Wait a few more seconds…";
  if (elapsedMs < GIVE_UP_MS) return "About to finish, please wait…";
  return "Still not updated. The collector may be busy; check again shortly.";
}

/** Manual refresh of the index EOD collector. Enabled only when the market session is closed. */
export function EodRefreshButton() {
  const [now, setNow] = useState(() => new Date());
  const [state, setState] = useState<RefreshState>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [status, setStatus] = useState<IndexEodStatus | null>(null);
  const [queuedAt, setQueuedAt] = useState<number | null>(null);
  const [etaSeconds, setEtaSeconds] = useState(0);
  const [progressNow, setProgressNow] = useState(() => Date.now());
  const controllerRef = useRef<AbortController | null>(null);
  const statusRef = useRef<IndexEodStatus | null>(null);
  const baselineRef = useRef<string | null>(null);

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), CLOCK_TICK_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => () => controllerRef.current?.abort(), []);

  // Reads the database's status on mount. A failed read keeps the last value shown.
  useEffect(() => {
    const controller = new AbortController();
    fetchIndexEodStatus({ signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setStatus(value);
      })
      .catch(() => {
        // Keep the previous value; an aborted request is the unmount path.
      });
    return () => controller.abort();
  }, []);

  const queued = state === "queued" || state === "already_queued";

  // While a refresh waits: redraw the countdown each second and re-read the database every few seconds.
  useEffect(() => {
    if (!queued) return;
    const controller = new AbortController();
    const tick = setInterval(() => setProgressNow(Date.now()), PROGRESS_TICK_MS);
    const poll = setInterval(() => {
      fetchIndexEodStatus({ signal: controller.signal })
        .then((value) => {
          if (!controller.signal.aborted) setStatus(value);
        })
        .catch(() => {
          // Try again on the next tick.
        });
    }, STATUS_POLL_MS);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
      controller.abort();
    };
  }, [queued]);

  // The database has a finish time newer than the one seen when the refresh was queued: prices are in.
  useEffect(() => {
    if (!queued || status?.lastRefreshedAt == null) return;
    if (status.lastRefreshedAt !== baselineRef.current) {
      setQueuedAt(null);
      setState("updated");
    }
  }, [queued, status]);

  const enabled = getMarketSession(now).status === "closed";
  const sending = state === "sending";

  async function handleClick() {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    if (queuedAt === null) {
      // First click of a new wait: remember the finish time to compare against, and size the countdown.
      baselineRef.current = statusRef.current?.lastRefreshedAt ?? null;
      setEtaSeconds(estimateSeconds(statusRef.current));
    }
    setState("sending");
    setErrorMessage("");
    try {
      const result = await requestIndexEodRefresh({ signal: controller.signal });
      if (result.kind === "market_open") {
        setQueuedAt(null);
        setState("market_open");
        return;
      }
      setQueuedAt((previous) => previous ?? Date.now());
      setProgressNow(Date.now());
      setState(result.kind === "queued" ? "queued" : "already_queued");
    } catch (error) {
      if (controller.signal.aborted) return;
      setQueuedAt(null);
      setErrorMessage(error instanceof Error ? error.message : "Unknown error");
      setState("error");
    }
  }

  const elapsedMs = queuedAt === null ? 0 : progressNow - queuedAt;
  const statusText = (() => {
    switch (state) {
      case "queued":
        return `Refresh queued. ${queuedProgressText(elapsedMs, etaSeconds)}`;
      case "already_queued":
        return `A refresh is already queued. ${queuedProgressText(elapsedMs, etaSeconds)}`;
      case "updated":
        return "Prices updated.";
      case "market_open":
        return "Market is still open. Try after 15:30 IST.";
      case "error":
        return `Refresh failed: ${errorMessage}`;
      default:
        return null;
    }
  })();

  const lastText = status?.lastRefreshedAt ? formatIstTimestamp(status.lastRefreshedAt) : "";

  return (
    <span className="inline-flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <button
        type="button"
        onClick={handleClick}
        disabled={!enabled || sending}
        aria-label="Refresh EOD prices"
        title={enabled ? "Queue an index EOD price refresh" : DISABLED_TITLE}
        className={`whitespace-nowrap rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text${
          !enabled || sending ? " opacity-50 cursor-not-allowed" : ""
        }`}
      >
        Refresh
      </button>
      {statusText ? (
        <span
          role="status"
          title="The collector checks for queued requests every 60 seconds, then runs the index EOD update."
          className="min-w-0 text-text-muted"
        >
          {statusText}
        </span>
      ) : null}
      {lastText ? (
        <span data-testid="eod-last-refreshed" className="whitespace-nowrap text-xs text-text-muted">
          Last refreshed: {lastText}
        </span>
      ) : null}
    </span>
  );
}
