import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SectorHeatmap } from "./SectorHeatmap";

const BODY = {
  period: "1d",
  sectors: [
    { sector: "IT", count: 10, avgChangePct: 1.23, advancers: 6, decliners: 4 },
    { sector: "Banks", count: 5, avgChangePct: -0.87, advancers: 1, decliners: 4 },
  ],
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SectorHeatmap", () => {
  it("renders a tile per sector with a signed arrow percentage", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(BODY)));

    render(<SectorHeatmap runId="run-42" />);

    expect(await screen.findByText("IT")).toBeInTheDocument();
    expect(screen.getByText("Banks")).toBeInTheDocument();
    expect(screen.getByText("▲ +1.23%")).toBeInTheDocument();
    expect(screen.getByText("▼ −0.87%")).toBeInTheDocument();
    expect(screen.getByText("10 stocks · 6 up, 4 down")).toBeInTheDocument();
  });

  it("marks 1D as the active period by default", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(BODY)));

    render(<SectorHeatmap runId="run-42" />);

    await screen.findByText("IT");
    expect(screen.getByRole("button", { name: "1D" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "1W" })).toHaveAttribute("aria-pressed", "false");
  });

  it("refetches with the new period when a period button is clicked", async () => {
    const fetchMock = vi.fn(async (_url: string) => jsonResponse(BODY));
    vi.stubGlobal("fetch", fetchMock);

    render(<SectorHeatmap runId="run-42" />);

    await screen.findByText("IT");
    fireEvent.click(screen.getByRole("button", { name: "1W" }));

    await waitFor(() => expect(fetchMock.mock.calls.map((call) => call[0])).toContain(
      "/api/runs/run-42/sector-summary?period=1w",
    ));
    expect(screen.getByRole("button", { name: "1W" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the server error message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "Run not available" }, 500)));

    render(<SectorHeatmap runId="run-42" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Run not available");
  });

  it("shows the empty state for an empty sector list", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ period: "1d", sectors: [] })));

    render(<SectorHeatmap runId="run-42" />);

    expect(await screen.findByText("No sector data for this period")).toBeInTheDocument();
  });
});
