import { useEffect, useRef, useState, type ReactNode } from "react";
import { EventsError, fetchEvents, type EventItem, type EventsResponse } from "../api/events";
import { formatIstDateTime } from "../lib/format";
import { StateView } from "../shell/StateView";

/** Refetch interval while the tab is visible. */
export const EVENTS_REFRESH_MS = 300_000;

/** Labels for the stored event_type values written by scanner/home_events.py FEEDS. */
export const EVENT_TYPE_LABELS: Record<string, string> = {
  results: "Results",
  insider_trade: "Insider trade",
  corporate_action: "Corporate action",
  governance: "Corporate governance",
  related_party: "Related party transaction",
  shareholding: "Shareholding pattern",
};

/** Labels for the stored feed_tier values. */
export const TIER_LABELS: Record<string, string> = {
  high_priority: "High priority",
  catalyst: "Catalyst",
};

const OTHER_LABEL = "Other";
const UNKNOWN_COMPANY = "Unknown company";
const FILING_LABEL = "Filing";
const EMPTY_GROUP_TEXT = "None in this window";

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/**
 * Age of an event relative to the response's generated_at (never the browser clock).
 * Returns "" when either timestamp is missing or unparseable.
 */
export function relativeAge(publishedAt: string | null, generatedAt: string | null): string {
  if (!publishedAt || !generatedAt) {
    return "";
  }
  const published = Date.parse(publishedAt);
  const generated = Date.parse(generatedAt);
  if (Number.isNaN(published) || Number.isNaN(generated)) {
    return "";
  }
  const diff = generated - published;
  if (diff < MINUTE_MS) {
    return "just now";
  }
  if (diff < HOUR_MS) {
    return `${Math.floor(diff / MINUTE_MS)} min ago`;
  }
  if (diff < DAY_MS) {
    return `${Math.floor(diff / HOUR_MS)} h ago`;
  }
  return `${Math.floor(diff / DAY_MS)} d ago`;
}

/** The normalized href when the URL parses with an http or https scheme, otherwise null. */
export function safeSourceUrl(url: string | null): string | null {
  if (!url) {
    return null;
  }
  const trimmed = url.trim();
  if (trimmed === "") {
    return null;
  }
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }
  return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
}

function hasOwn(map: Record<string, string>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(map, key);
}

function nonEmpty(value: string | null): string | null {
  return value !== null && value.trim() !== "" ? value : null;
}

function eventTypeLabel(eventType: string | null): string {
  const value = nonEmpty(eventType);
  if (value === null) {
    return FILING_LABEL;
  }
  return hasOwn(EVENT_TYPE_LABELS, value) ? EVENT_TYPE_LABELS[value] : value;
}

interface EventGroups {
  high: EventItem[];
  catalyst: EventItem[];
  other: EventItem[];
}

function groupEvents(events: EventItem[]): EventGroups {
  const groups: EventGroups = { high: [], catalyst: [], other: [] };
  for (const event of events) {
    if (event.feed_tier === "high_priority") {
      groups.high.push(event);
    } else if (event.feed_tier === "catalyst") {
      groups.catalyst.push(event);
    } else {
      groups.other.push(event);
    }
  }
  return groups;
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

type FeedState =
  | { kind: "loading" }
  | { kind: "ready"; data: EventsResponse }
  | { kind: "error"; status: number | null };

function EventRow({ event, generatedAt }: { event: EventItem; generatedAt: string }) {
  const company = nonEmpty(event.company);
  const symbol = nonEmpty(event.symbol);
  const primary = company ?? symbol ?? UNKNOWN_COMPANY;
  const headline = nonEmpty(event.headline);
  const href = safeSourceUrl(event.source_url);
  const age = relativeAge(event.published_at, generatedAt);

  return (
    <li className="flex flex-col gap-1 border-b border-border py-2 last:border-b-0">
      <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
        <span className="font-medium text-text">{primary}</span>
        {symbol !== null && symbol !== primary ? <span className="text-text-muted">{symbol}</span> : null}
        <span className="text-text-muted">{eventTypeLabel(event.event_type)}</span>
      </div>
      {headline !== null ? <p className="text-sm text-text">{headline}</p> : null}
      <div className="flex flex-wrap gap-x-3 text-xs text-text-muted">
        {age !== "" ? <span>{age}</span> : null}
        {href !== null ? (
          <a href={href} target="_blank" rel="noopener noreferrer" className="underline">
            Source
          </a>
        ) : (
          <span>Source unavailable</span>
        )}
      </div>
    </li>
  );
}

function EventGroup({
  title,
  events,
  generatedAt,
}: {
  title: string;
  events: EventItem[];
  generatedAt: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-sm font-semibold text-text">{title}</h3>
      {events.length === 0 ? (
        <p className="text-sm text-text-muted">{EMPTY_GROUP_TEXT}</p>
      ) : (
        <ul className="flex flex-col">
          {events.map((event, index) => (
            <EventRow key={`${event.id ?? "event"}-${index}`} event={event} generatedAt={generatedAt} />
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Home event feed: filings from GET /api/events in two groups (high priority, catalyst) plus an
 * "Other" group when a row has an unknown tier. Refetches every EVENTS_REFRESH_MS while the tab is
 * visible. A failed refetch after a success keeps the data on screen.
 */
export function HomeEventFeed() {
  const [state, setState] = useState<FeedState>({ kind: "loading" });
  const retryRef = useRef<() => void>(() => {});

  useEffect(() => {
    let controller: AbortController | null = null;
    let lastFetchAt = 0;

    const load = () => {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      lastFetchAt = Date.now();
      fetchEvents({}, { signal: current.signal })
        .then((data) => {
          if (current.signal.aborted) {
            return;
          }
          setState({ kind: "ready", data });
        })
        .catch((error: unknown) => {
          if (current.signal.aborted || isAbortError(error)) {
            return;
          }
          const status = error instanceof EventsError ? error.status : null;
          setState((previous) => (previous.kind === "ready" ? previous : { kind: "error", status }));
        });
    };

    retryRef.current = () => {
      setState({ kind: "loading" });
      load();
    };

    const timer = setInterval(() => {
      if (document.visibilityState === "visible") {
        load();
      }
    }, EVENTS_REFRESH_MS);

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible" && Date.now() - lastFetchAt >= EVENTS_REFRESH_MS) {
        load();
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    load();

    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      controller?.abort();
    };
  }, []);

  const data = state.kind === "ready" ? state.data : null;
  const stamp = data !== null && data.latest_fetched_at ? formatIstDateTime(data.latest_fetched_at) : null;

  let body: ReactNode;
  if (state.kind === "loading") {
    body = <StateView kind="loading" message="Loading filings." />;
  } else if (state.kind === "error") {
    const message = state.status === 503 ? "Events database unavailable." : "Could not load filings.";
    body = (
      <StateView
        kind="error"
        message={message}
        action={{ label: "Retry", onClick: () => retryRef.current() }}
      />
    );
  } else if (state.data.events.length === 0) {
    body = <StateView kind="empty" message={`No filings in the last ${state.data.window_days} days.`} />;
  } else {
    const groups = groupEvents(state.data.events);
    const generatedAt = state.data.generated_at;
    body = (
      <div className="flex flex-col gap-4">
        <EventGroup title={TIER_LABELS.high_priority} events={groups.high} generatedAt={generatedAt} />
        <EventGroup title={TIER_LABELS.catalyst} events={groups.catalyst} generatedAt={generatedAt} />
        {groups.other.length > 0 ? (
          <EventGroup title={OTHER_LABEL} events={groups.other} generatedAt={generatedAt} />
        ) : null}
      </div>
    );
  }

  return (
    <section aria-label="Filings feed" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-text">Filings</h2>
        {stamp !== null ? <p className="text-xs text-text-muted">Events as of {stamp}</p> : null}
      </div>
      {body}
    </section>
  );
}
