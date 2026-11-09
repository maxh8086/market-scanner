import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  EodRefreshButton,
  estimateSeconds,
  formatCountdown,
  formatIstTimestamp,
  queuedProgressText,
} from "./EodRefreshButton";

const session = vi.hoisted(() => ({ status: "closed" as "open" | "closed" | "pre_open" }));

vi.mock("../lib/marketSession", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/marketSession")>();
  return {
    ...actual,
    getMarketSession: () => ({ status: session.status, lastCloseLabel: "Fri 6 Nov, 15:30 IST" }),
  };
});

function stubFetch(
  status: number,
  body: unknown = {},
  lastRefreshedAt: string | null = null,
  lastRunSeconds: number | null = null,
) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/collector/index-eod/status") {
      return {
        status: 200,
        ok: true,
        json: async () => ({ lastRefreshedAt, lastRunSeconds, pickupSeconds: 60 }),
      };
    }
    return { status, ok: status >= 200 && status < 300, json: async () => body };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function postCalls(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("formatIstTimestamp", () => {
  it("formats an ISO instant as IST day, month, year and 24-hour time", () => {
    expect(formatIstTimestamp("2026-11-09T10:22:00.000Z")).toBe("09 Nov 2026, 15:52 IST");
  });

  it("returns an empty string for an invalid value", () => {
    expect(formatIstTimestamp("not a date")).toBe("");
  });
});

describe("estimateSeconds", () => {
  it("adds the collector pickup interval to the last run duration", () => {
    expect(estimateSeconds({ lastRunSeconds: 14, pickupSeconds: 60 })).toBe(74);
  });

  it("assumes a 60 second run when no run has finished yet", () => {
    expect(estimateSeconds({ lastRunSeconds: null, pickupSeconds: 60 })).toBe(120);
    expect(estimateSeconds(null)).toBe(120);
  });
});

describe("formatCountdown", () => {
  it("formats minutes and seconds, rounding partial seconds up", () => {
    expect(formatCountdown(74_000)).toBe("1:14");
    expect(formatCountdown(9_100)).toBe("0:10");
    expect(formatCountdown(0)).toBe("0:00");
    expect(formatCountdown(-500)).toBe("0:00");
  });
});

describe("queuedProgressText", () => {
  it("shows the estimated time left until the countdown ends", () => {
    expect(queuedProgressText(0, 74)).toBe("Estimated 1:14 left.");
    expect(queuedProgressText(70_000, 74)).toBe("Estimated 0:04 left.");
  });

  it("switches to 'Wait a few more seconds' when the countdown reaches zero", () => {
    expect(queuedProgressText(74_000, 74)).toBe("Wait a few more seconds…");
    expect(queuedProgressText(90_000, 74)).toBe("Wait a few more seconds…");
  });

  it("switches to 'About to finish' after the extra wait", () => {
    expect(queuedProgressText(110_000, 74)).toBe("About to finish, please wait…");
  });

  it("says the collector may be busy after ten minutes", () => {
    expect(queuedProgressText(10 * 60_000 + 1, 74)).toBe(
      "Still not updated. The collector may be busy; check again shortly.",
    );
  });
});

describe("EodRefreshButton", () => {
  it("is disabled with the market-hours title while the market is open", () => {
    session.status = "open";
    const fetchMock = stubFetch(202, { queued: true });
    render(<EodRefreshButton />);

    const button = screen.getByRole("button", { name: "Refresh EOD prices" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Available after market close (15:30 IST) on trading days");
    expect(button.className).toContain("cursor-not-allowed");
    expect(postCalls(fetchMock)).toHaveLength(0);
  });

  it("is enabled when the market is closed and sends no refresh until clicked", () => {
    session.status = "closed";
    const fetchMock = stubFetch(202, { queued: true });
    render(<EodRefreshButton />);

    const button = screen.getByRole("button", { name: "Refresh EOD prices" });
    expect(button).toBeEnabled();
    expect(postCalls(fetchMock)).toHaveLength(0);
  });

  it("shows the last refresh time the database recorded, in IST", async () => {
    session.status = "closed";
    stubFetch(202, {}, "2026-11-09T10:22:00.000Z");
    render(<EodRefreshButton />);

    expect(await screen.findByTestId("eod-last-refreshed")).toHaveTextContent("Last refreshed: 09 Nov 2026, 15:52 IST");
  });

  it("shows no timestamp when the database has no finished index_eod run", async () => {
    session.status = "closed";
    const fetchMock = stubFetch(202, {}, null);
    render(<EodRefreshButton />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/collector/index-eod/status", expect.anything()));
    expect(screen.queryByTestId("eod-last-refreshed")).toBeNull();
  });

  it("POSTs to the refresh endpoint and shows the countdown estimate on 202", async () => {
    session.status = "closed";
    const fetchMock = stubFetch(202, { queued: true }, "2026-11-09T10:22:00.000Z", 14);
    render(<EodRefreshButton />);
    await screen.findByTestId("eod-last-refreshed");

    fireEvent.click(screen.getByRole("button", { name: "Refresh EOD prices" }));

    expect(await screen.findByText(/^Refresh queued\. Estimated 1:1[34] left\.$/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/collector/index-eod/refresh",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows the market-open text on 409", async () => {
    session.status = "closed";
    stubFetch(409, { error: "market_hours", message: "Refresh opens after 15:30 IST on trading days." });
    render(<EodRefreshButton />);

    fireEvent.click(screen.getByRole("button", { name: "Refresh EOD prices" }));

    expect(await screen.findByText("Market is still open. Try after 15:30 IST.")).toBeInTheDocument();
  });

  it("shows the already-queued text on 200", async () => {
    session.status = "closed";
    stubFetch(200, { queued: false, message: "A refresh is already queued." });
    render(<EodRefreshButton />);

    fireEvent.click(screen.getByRole("button", { name: "Refresh EOD prices" }));

    expect(await screen.findByText(/^A refresh is already queued\. Estimated \d+:\d{2} left\.$/)).toBeInTheDocument();
  });

  it("shows the error text when the request fails", async () => {
    session.status = "closed";
    stubFetch(500, { error: "Could not queue the refresh." });
    render(<EodRefreshButton />);

    fireEvent.click(screen.getByRole("button", { name: "Refresh EOD prices" }));

    await waitFor(() =>
      expect(screen.getByText("Refresh failed: Could not queue the refresh.")).toBeInTheDocument(),
    );
  });
});
