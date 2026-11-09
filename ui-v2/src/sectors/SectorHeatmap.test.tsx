import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

async function tiles(): Promise<HTMLElement> {
  return screen.findByRole("list", { name: "Sector tiles" });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SectorHeatmap", () => {
  it("renders a tile per sector with a signed arrow percentage and the stock count", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(BODY)));

    render(<SectorHeatmap runId="run-42" />);

    const list = await tiles();
    expect(within(list).getByText("IT")).toBeInTheDocument();
    expect(within(list).getByText("Banks")).toBeInTheDocument();
    expect(within(list).getByText("▲ +1.23%")).toBeInTheDocument();
    expect(within(list).getByText("▼ −0.87%")).toBeInTheDocument();
    expect(within(list).getByText("10 stocks · 6 up, 4 down")).toBeInTheDocument();
    expect(within(list).getByText("5 stocks · 1 up, 4 down")).toBeInTheDocument();
  });

  it("uses the singular for a one-stock sector", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          period: "1d",
          sectors: [{ sector: "Utilities", count: 1, avgChangePct: 6.57, advancers: 1, decliners: 0 }],
        }),
      ),
    );

    render(<SectorHeatmap runId="run-42" />);

    expect(within(await tiles()).getByText("1 stock · 1 up, 0 down")).toBeInTheDocument();
  });

  it("lists the best and worst sectors in the summary", async () => {
    const sectors = [
      { sector: "IT", count: 10, avgChangePct: 3.1, advancers: 8, decliners: 2 },
      { sector: "Auto", count: 8, avgChangePct: 2.2, advancers: 6, decliners: 2 },
      { sector: "Pharma", count: 6, avgChangePct: 0.4, advancers: 4, decliners: 2 },
      { sector: "Metals", count: 7, avgChangePct: -0.3, advancers: 3, decliners: 4 },
      { sector: "Realty", count: 5, avgChangePct: -1.5, advancers: 1, decliners: 4 },
      { sector: "Banks", count: 9, avgChangePct: -2.4, advancers: 2, decliners: 7 },
    ];
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ period: "1d", sectors })));

    render(<SectorHeatmap runId="run-42" />);

    await tiles();
    const top = screen.getByText("Top sectors").parentElement as HTMLElement;
    const bottom = screen.getByText("Bottom sectors").parentElement as HTMLElement;
    expect(within(top).getByText("IT")).toBeInTheDocument();
    expect(within(top).getByText("Auto")).toBeInTheDocument();
    expect(within(top).getByText("Pharma")).toBeInTheDocument();
    expect(within(bottom).getByText("Banks")).toBeInTheDocument();
    expect(within(bottom).getByText("Realty")).toBeInTheDocument();
    expect(within(bottom).getByText("Metals")).toBeInTheDocument();
  });

  it("renders a table row per sector, ranked by change with the best first", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(BODY)));

    render(<SectorHeatmap runId="run-42" />);

    const table = await screen.findByRole("table", { name: "Sector performance" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("1IT");
    expect(rows[1]).toHaveTextContent("2Banks");
    expect(within(table).getByRole("columnheader", { name: /Change/ })).toHaveAttribute("aria-sort", "descending");
  });

  it("re-sorts the table by stocks when that header is clicked", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(BODY)));

    render(<SectorHeatmap runId="run-42" />);

    const table = await screen.findByRole("table", { name: "Sector performance" });
    fireEvent.click(within(table).getByRole("button", { name: /^Stocks/ }));

    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("IT");
    expect(within(table).getByRole("columnheader", { name: /Stocks/ })).toHaveAttribute("aria-sort", "descending");
    fireEvent.click(within(table).getByRole("button", { name: /^Stocks/ }));
    expect(within(table).getAllByRole("row").slice(1)[0]).toHaveTextContent("Banks");
  });

  it("marks 1D as the active period by default", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(BODY)));

    render(<SectorHeatmap runId="run-42" />);

    await tiles();
    expect(screen.getByRole("button", { name: "1D" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "1W" })).toHaveAttribute("aria-pressed", "false");
  });

  it("refetches with the new period when a period button is clicked", async () => {
    const fetchMock = vi.fn(async (_url: string) => jsonResponse(BODY));
    vi.stubGlobal("fetch", fetchMock);

    render(<SectorHeatmap runId="run-42" />);

    await tiles();
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
