/** Client for GET /api/events. Shape mirrors server/src/eventsRead.ts and server/src/eventsReadRoute.ts. */

import { apiGet } from "./session";

export type EventsTier = "high_priority" | "catalyst";

export interface EventsQuery {
  days?: number;
  tier?: EventsTier;
  limit?: number;
  symbol?: string;
}

export interface EventItem {
  id: string | null;
  symbol: string | null;
  isin: string | null;
  company: string | null;
  event_type: string | null;
  feed_tier: string | null;
  feed_code: string | null;
  headline: string | null;
  published_at: string | null;
  fetched_at: string | null;
  source_url: string | null;
}

export interface EventsResponse {
  generated_at: string;
  latest_fetched_at: string | null;
  window_days: number;
  events: EventItem[];
}

export interface FetchEventsOptions {
  signal?: AbortSignal;
}

/** Failure from the events API: a non-OK status, a network error or a bad body. */
export class EventsError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "EventsError";
    this.status = status;
  }
}

/** Builds a query string from the params that are set. Empty and undefined values are skipped. */
export function buildEventsQueryString(query: EventsQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  return params.toString();
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: unknown };
    if (typeof body.error === "string" && body.error.length > 0) {
      return body.error;
    }
  } catch {
    // Body is not JSON; fall through to the generic message.
  }
  return `Request failed with status ${response.status}.`;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isEventsResponse(body: unknown): body is EventsResponse {
  if (!isPlainObject(body)) {
    return false;
  }
  const response = body as Partial<Record<keyof EventsResponse, unknown>>;
  return (
    typeof response.generated_at === "string" &&
    (typeof response.latest_fetched_at === "string" || response.latest_fetched_at === null) &&
    typeof response.window_days === "number" &&
    Array.isArray(response.events) &&
    response.events.every(isPlainObject)
  );
}

export async function fetchEvents(
  query: EventsQuery = {},
  options: FetchEventsOptions = {},
): Promise<EventsResponse> {
  const queryString = buildEventsQueryString(query);
  const url = queryString ? `/api/events?${queryString}` : "/api/events";

  let response: Response;
  try {
    response = await apiGet(url, {
      headers: { Accept: "application/json" },
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new EventsError("Could not reach the events service.", null);
  }

  if (!response.ok) {
    throw new EventsError(await readErrorMessage(response), response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new EventsError("The events response was not valid JSON.", response.status);
  }

  if (!isEventsResponse(body)) {
    throw new EventsError("The events response had an unexpected shape.", response.status);
  }
  return body;
}
