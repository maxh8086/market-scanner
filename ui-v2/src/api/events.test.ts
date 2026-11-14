import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildEventsQueryString,
  EventsError,
  type EventsResponse,
  fetchEvents,
} from "./events";
import { resetCsrfTokenForTests, SESSION_URL } from "./session";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** Answers GET /api/session with a test token and every other URL with the given read. */
function withSession(read: (url: string, init?: RequestInit) => Promise<Response>) {
  return vi.fn(async (url: string, init?: RequestInit) =>
    url === SESSION_URL ? jsonResponse({ csrfToken: "test-csrf" }) : read(url, init),
  );
}

const EMPTY: EventsResponse = {
  generated_at: "2026-11-14T20:15:00+05:30",
  latest_fetched_at: null,
  window_days: 7,
  events: [],
};

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildEventsQueryString", () => {
  it("returns an empty string for an empty query", () => {
    expect(buildEventsQueryString({})).toBe("");
  });

  it("includes the params that are set", () => {
    expect(
      buildEventsQueryString({ days: 7, tier: "catalyst", limit: 50, symbol: "ABC" }),
    ).toBe("days=7&tier=catalyst&limit=50&symbol=ABC");
  });

  it("skips empty and undefined values", () => {
    expect(buildEventsQueryString({ days: undefined, symbol: "", tier: undefined })).toBe("");
  });
});

describe("fetchEvents", () => {
  it("requests /api/events with the Accept header and returns the body", async () => {
    const fetchMock = withSession(async () => jsonResponse(EMPTY));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchEvents();

    // Call 0 is the session fetch that apiGet makes first; call 1 is the events read.
    expect(fetchMock.mock.calls[1][0]).toBe("/api/events");
    expect(fetchMock.mock.calls[1][1]?.headers).toEqual({ Accept: "application/json" });
    expect(result).toEqual(EMPTY);
  });

  it("appends the query string when params are given", async () => {
    const fetchMock = withSession(async () => jsonResponse(EMPTY));
    vi.stubGlobal("fetch", fetchMock);

    await fetchEvents({ days: 7, tier: "high_priority" });

    expect(fetchMock.mock.calls[1][0]).toBe("/api/events?days=7&tier=high_priority");
  });

  it("throws an EventsError with the server message and status on a 503", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ error: "events_database_unavailable" }, 503)),
    );

    const error = (await fetchEvents().catch((e: unknown) => e)) as EventsError;

    expect(error).toBeInstanceOf(EventsError);
    expect(error.message).toBe("events_database_unavailable");
    expect(error.status).toBe(503);
  });

  it("throws an EventsError with a null status on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    const error = (await fetchEvents().catch((e: unknown) => e)) as EventsError;

    expect(error).toBeInstanceOf(EventsError);
    expect(error.status).toBeNull();
    expect(error.message).toBe("Could not reach the events service.");
  });

  it("rethrows an abort without wrapping it", async () => {
    const abort = new DOMException("aborted", "AbortError");
    vi.stubGlobal(
      "fetch",
      withSession(async () => {
        throw abort;
      }),
    );

    await expect(fetchEvents()).rejects.toBe(abort);
  });

  it("throws an EventsError for a body that is not JSON", async () => {
    const response = {
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError("bad json");
      },
    } as unknown as Response;
    vi.stubGlobal("fetch", withSession(async () => response));

    const error = (await fetchEvents().catch((e: unknown) => e)) as EventsError;

    expect(error).toBeInstanceOf(EventsError);
    expect(error.status).toBe(200);
  });

  it("throws an EventsError for a 200 body with the wrong shape", async () => {
    vi.stubGlobal("fetch", withSession(async () => jsonResponse({ nope: true })));

    const error = (await fetchEvents().catch((e: unknown) => e)) as EventsError;

    expect(error).toBeInstanceOf(EventsError);
    expect(error.status).toBe(200);
  });

  it("rejects an envelope whose latest_fetched_at is not a string or null", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ ...EMPTY, latest_fetched_at: 12 })),
    );

    await expect(fetchEvents()).rejects.toBeInstanceOf(EventsError);
  });

  it("rejects an event that is not an object", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ ...EMPTY, events: ["ABC"] })),
    );

    await expect(fetchEvents()).rejects.toBeInstanceOf(EventsError);
  });
});
