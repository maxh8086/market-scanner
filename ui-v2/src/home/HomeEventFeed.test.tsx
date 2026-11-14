import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EventItem, EventsResponse } from "../api/events";
import { resetCsrfTokenForTests, SESSION_URL } from "../api/session";
import {
  EVENTS_REFRESH_MS,
  HomeEventFeed,
  relativeAge,
  safeSourceUrl,
} from "./HomeEventFeed";

const GENERATED = "2026-11-14T20:15:00+05:30";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function event(overrides: Partial<EventItem> = {}): EventItem {
  return {
    id: "key-1",
    symbol: "ABC",
    isin: "INE000A01010",
    company: "ABC Ltd",
    event_type: "results",
    feed_tier: "high_priority",
    feed_code: "nse:Financial_Results",
    headline: "Quarterly results",
    published_at: "2026-11-14T19:15:00+05:30",
    fetched_at: "2026-11-14T19:20:00+05:30",
    source_url: "https://example.com/x",
    ...overrides,
  };
}

function response(events: EventItem[], overrides: Partial<EventsResponse> = {}): EventsResponse {
  return {
    generated_at: GENERATED,
    latest_fetched_at: "2020-01-02T10:00:00.000+05:30",
    window_days: 7,
    events,
    ...overrides,
  };
}

/**
 * Answers the session fetch and each GET /api/events call with eventsRead(callIndex, init).
 * Returns the fetch mock so tests can read the events calls.
 */
function stubFetch(eventsRead: (call: number, init?: RequestInit) => Promise<Response>) {
  let calls = 0;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === SESSION_URL) {
      return jsonResponse({ csrfToken: "test-csrf" });
    }
    if (url === "/api/events") {
      const index = calls++;
      return eventsRead(index, init);
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function eventsCalls(fetchMock: ReturnType<typeof stubFetch>) {
  return fetchMock.mock.calls.filter((call) => call[0] === "/api/events");
}

/** The group wrapper for a heading: the heading and its list share one parent element. */
function groupOf(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).parentElement as HTMLElement;
}

/** Lets pending promise chains (session fetch, events fetch, json) settle under fake timers. */
async function flush() {
  for (let i = 0; i < 20; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HomeEventFeed groups and rows", () => {
  it("renders both groups with their rows, company, label, headline and age", async () => {
    stubFetch(async () =>
      jsonResponse(
        response([
          event({ id: "a", company: "Alpha Ltd", symbol: "ALP", headline: "Q2 results", published_at: "2026-11-14T19:15:00+05:30" }),
          event({
            id: "b",
            company: "Beta Ltd",
            symbol: "BET",
            feed_tier: "catalyst",
            event_type: "corporate_action",
            headline: "Dividend declared",
            published_at: "2026-11-14T17:15:00+05:30",
          }),
        ]),
      ),
    );

    render(<HomeEventFeed />);

    expect(await screen.findByText("Alpha Ltd")).toBeInTheDocument();
    const high = groupOf("High priority");
    const catalyst = groupOf("Catalyst");
    expect(within(high).getByText("Alpha Ltd")).toBeInTheDocument();
    expect(within(high).getByText("Results")).toBeInTheDocument();
    expect(within(high).getByText("Q2 results")).toBeInTheDocument();
    expect(within(high).getByText("1 h ago")).toBeInTheDocument();
    expect(within(catalyst).getByText("Beta Ltd")).toBeInTheDocument();
    expect(within(catalyst).getByText("Corporate action")).toBeInTheDocument();
    expect(within(catalyst).getByText("Dividend declared")).toBeInTheDocument();
    expect(within(catalyst).getByText("3 h ago")).toBeInTheDocument();
    expect(within(high).queryByText("Beta Ltd")).not.toBeInTheDocument();
    expect(screen.queryByText("None in this window")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Other" })).not.toBeInTheDocument();
  });

  it("shows None in this window for a group with no rows and keeps the group", async () => {
    stubFetch(async () => jsonResponse(response([event({ company: "Alpha Ltd" })])));

    render(<HomeEventFeed />);

    expect(await screen.findByText("Alpha Ltd")).toBeInTheDocument();
    expect(within(groupOf("Catalyst")).getByText("None in this window")).toBeInTheDocument();
    expect(within(groupOf("High priority")).queryByText("None in this window")).not.toBeInTheDocument();
  });

  it("shows the Other group only when a row has an unknown tier", async () => {
    stubFetch(async () =>
      jsonResponse(
        response([
          event({ id: "x", company: "Odd Ltd", feed_tier: "mystery" }),
          event({ id: "y", company: "Null Tier Ltd", feed_tier: null }),
        ]),
      ),
    );

    render(<HomeEventFeed />);

    expect(await screen.findByText("Odd Ltd")).toBeInTheDocument();
    const other = groupOf("Other");
    expect(within(other).getByText("Odd Ltd")).toBeInTheDocument();
    expect(within(other).getByText("Null Tier Ltd")).toBeInTheDocument();
  });

  it("labels unknown and null event types, and falls back for company and symbol", async () => {
    stubFetch(async () =>
      jsonResponse(
        response([
          event({ id: "u", company: null, symbol: "XYZ", event_type: "new_kind" }),
          event({ id: "n", company: null, symbol: null, event_type: null, headline: null }),
        ]),
      ),
    );

    render(<HomeEventFeed />);

    expect(await screen.findByText("new_kind")).toBeInTheDocument();
    expect(screen.getByText("Filing")).toBeInTheDocument();
    expect(screen.getByText("XYZ")).toBeInTheDocument();
    expect(screen.getByText("Unknown company")).toBeInTheDocument();
  });

  it("shows the stamp from latest_fetched_at and no stamp when it is null", async () => {
    stubFetch(async () => jsonResponse(response([event()])));
    const { unmount } = render(<HomeEventFeed />);

    expect(await screen.findByText("Events as of 02 Jan 2020, 10:00 IST")).toBeInTheDocument();
    unmount();

    stubFetch(async () => jsonResponse(response([], { latest_fetched_at: null })));
    render(<HomeEventFeed />);

    expect(await screen.findByText("No filings in the last 7 days.")).toBeInTheDocument();
    expect(screen.queryByText(/Events as of/)).not.toBeInTheDocument();
  });

  it("uses window_days in the empty state text", async () => {
    stubFetch(async () => jsonResponse(response([], { window_days: 30 })));

    render(<HomeEventFeed />);

    expect(await screen.findByText("No filings in the last 30 days.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Filings feed" })).toBeInTheDocument();
  });
});

describe("HomeEventFeed error states", () => {
  it("shows the database message on 503 and Retry refetches and then shows data", async () => {
    const fetchMock = stubFetch(async (call) =>
      call === 0
        ? jsonResponse({ error: "events_database_unavailable" }, 503)
        : jsonResponse(response([event({ company: "Alpha Ltd" })])),
    );

    render(<HomeEventFeed />);

    expect(await screen.findByText("Events database unavailable.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Alpha Ltd")).toBeInTheDocument();
    expect(eventsCalls(fetchMock)).toHaveLength(2);
  });

  it("shows the generic message for other failures and does not throw", async () => {
    stubFetch(async () => jsonResponse({ error: "internal_error" }, 500));

    render(<HomeEventFeed />);

    expect(await screen.findByText("Could not load filings.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("shows the generic message on a network failure", async () => {
    stubFetch(async () => {
      throw new TypeError("Failed to fetch");
    });

    render(<HomeEventFeed />);

    expect(await screen.findByText("Could not load filings.")).toBeInTheDocument();
  });
});

describe("HomeEventFeed source links and text", () => {
  it("links only http and https sources and shows Source unavailable otherwise", async () => {
    stubFetch(async () =>
      jsonResponse(
        response([
          event({ id: "j", company: "Js Ltd", source_url: "javascript:alert(1)" }),
          event({ id: "d", company: "Data Ltd", source_url: "data:text/html,x" }),
          event({ id: "n", company: "Null Ltd", source_url: null }),
          event({ id: "h", company: "Https Ltd", source_url: "https://example.com/x" }),
        ]),
      ),
    );

    const { container } = render(<HomeEventFeed />);

    expect(await screen.findByText("Https Ltd")).toBeInTheDocument();
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://example.com/x");
    expect(links[0]).toHaveAttribute("target", "_blank");
    expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getAllByText("Source unavailable")).toHaveLength(3);
  });

  it("renders a headline containing HTML as plain text", async () => {
    stubFetch(async () =>
      jsonResponse(response([event({ headline: "<img src=x onerror=alert(1)>" })])),
    );

    const { container } = render(<HomeEventFeed />);

    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("HomeEventFeed refresh, visibility and abort", () => {
  function setVisibility(state: "visible" | "hidden") {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => state,
    });
  }

  beforeEach(() => {
    vi.useFakeTimers();
    setVisibility("visible");
  });

  afterEach(() => {
    vi.useRealTimers();
    // Remove the instance override so the jsdom getter applies again.
    delete (document as unknown as { visibilityState?: unknown }).visibilityState;
  });

  it("refetches after EVENTS_REFRESH_MS while visible", async () => {
    const fetchMock = stubFetch(async () => jsonResponse(response([event({ company: "Alpha Ltd" })])));

    render(<HomeEventFeed />);
    await flush();
    expect(eventsCalls(fetchMock)).toHaveLength(1);

    await act(async () => {
      vi.advanceTimersByTime(EVENTS_REFRESH_MS);
    });
    await flush();

    expect(eventsCalls(fetchMock)).toHaveLength(2);
  });

  it("does not refetch on the interval while hidden, and refetches on becoming visible", async () => {
    const fetchMock = stubFetch(async () => jsonResponse(response([event({ company: "Alpha Ltd" })])));

    render(<HomeEventFeed />);
    await flush();

    setVisibility("hidden");
    await act(async () => {
      vi.advanceTimersByTime(EVENTS_REFRESH_MS);
    });
    await flush();
    expect(eventsCalls(fetchMock)).toHaveLength(1);

    setVisibility("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await flush();
    expect(eventsCalls(fetchMock)).toHaveLength(2);
  });

  it("keeps the old rows when a refetch after a success fails", async () => {
    const fetchMock = stubFetch(async (call) =>
      call === 0
        ? jsonResponse(response([event({ company: "Alpha Ltd" })]))
        : jsonResponse({ error: "internal_error" }, 500),
    );

    render(<HomeEventFeed />);
    await flush();
    expect(screen.getByText("Alpha Ltd")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(EVENTS_REFRESH_MS);
    });
    await flush();

    expect(eventsCalls(fetchMock)).toHaveLength(2);
    expect(screen.getByText("Alpha Ltd")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Could not load filings.")).not.toBeInTheDocument();
  });

  it("aborts the in-flight request and stops the timer on unmount", async () => {
    const fetchMock = stubFetch(() => new Promise<Response>(() => {}));

    const { unmount } = render(<HomeEventFeed />);
    await flush();
    const signal = eventsCalls(fetchMock)[0][1]?.signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    unmount();

    expect(signal.aborted).toBe(true);
    await act(async () => {
      vi.advanceTimersByTime(EVENTS_REFRESH_MS);
    });
    await flush();
    expect(eventsCalls(fetchMock)).toHaveLength(1);
  });
});

describe("relativeAge", () => {
  it("returns an empty string when a timestamp is missing or unparseable", () => {
    expect(relativeAge(null, GENERATED)).toBe("");
    expect(relativeAge("2026-11-14T19:00:00+05:30", null)).toBe("");
    expect(relativeAge("not a date", GENERATED)).toBe("");
  });

  it("formats the age from generated_at", () => {
    expect(relativeAge("2026-11-14T20:14:30+05:30", GENERATED)).toBe("just now");
    expect(relativeAge("2026-11-14T20:10:00+05:30", GENERATED)).toBe("5 min ago");
    expect(relativeAge("2026-11-14T17:15:00+05:30", GENERATED)).toBe("3 h ago");
    expect(relativeAge("2026-11-12T20:15:00+05:30", GENERATED)).toBe("2 d ago");
  });
});

describe("safeSourceUrl", () => {
  it("returns the href for http and https URLs", () => {
    expect(safeSourceUrl("https://example.com/x")).toBe("https://example.com/x");
    expect(safeSourceUrl("http://example.com/a")).toBe("http://example.com/a");
  });

  it("returns null for other schemes, empty, null and unparseable input", () => {
    expect(safeSourceUrl("javascript:alert(1)")).toBeNull();
    expect(safeSourceUrl("data:text/html,x")).toBeNull();
    expect(safeSourceUrl(null)).toBeNull();
    expect(safeSourceUrl("")).toBeNull();
    expect(safeSourceUrl("not a url")).toBeNull();
  });
});
