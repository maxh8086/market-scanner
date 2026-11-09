import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ScreenerTable } from "./ScreenerTable";

const RUN_ID = "2026-11-09";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function lastUrl(fetchMock: ReturnType<typeof vi.fn>): string {
  return fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0] as string;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue(jsonResponse({ results: [], total: 0, page: 1, perPage: 50 }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ScreenerTable filters", () => {
  it("sends the active filters with the results query", async () => {
    render(<ScreenerTable runId={RUN_ID} filters={{ bucket: "A", ltpMin: 100 }} />);

    await waitFor(() =>
      expect(lastUrl(fetchMock)).toBe(
        `/api/runs/${RUN_ID}/results?bucket=A&ltpMin=100&page=1&perPage=50`,
      ),
    );
  });

  it("offers Clear filters in the no-results state and calls the clear action", async () => {
    const onClearFilters = vi.fn();
    render(<ScreenerTable runId={RUN_ID} filters={{ search: "zzz" }} onClearFilters={onClearFilters} />);

    expect(await screen.findByText("No results match these filters.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(onClearFilters).toHaveBeenCalledTimes(1);
  });

  it("shows the plain empty message when no filters are active", async () => {
    render(<ScreenerTable runId={RUN_ID} />);

    expect(await screen.findByText("No results for this run.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });
});
