import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BrokerError } from "../api/broker";
import { HoldingsError } from "../api/holdings";
import {
  formatInr,
  formatLocalTime,
  formatSignedPct,
  HoldingsPanel,
  LOGIN_REQUIRED_NOTICE,
  loginRequiredNotice,
  NO_STORED_PORTFOLIO,
  noStoredPortfolio,
  toHoldingRow,
  totalHoldings,
} from "./HoldingsPanel";

const api = vi.hoisted(() => ({
  fetchBrokerStatus: vi.fn(),
  requestLoginUrl: vi.fn(),
  syncPortfolio: vi.fn(),
  redirectToBrokerLogin: vi.fn(),
  fetchHoldings: vi.fn(),
}));

vi.mock("../api/broker", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/broker")>();
  return {
    ...actual,
    fetchBrokerStatus: api.fetchBrokerStatus,
    requestLoginUrl: api.requestLoginUrl,
    syncPortfolio: api.syncPortfolio,
    redirectToBrokerLogin: api.redirectToBrokerLogin,
  };
});

vi.mock("../api/holdings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/holdings")>();
  return { ...actual, fetchHoldings: api.fetchHoldings };
});

const HOLDING = {
  symbol: "ACE",
  isin: null,
  quantity: 100,
  averagePrice: 834.1,
  lastPrice: 1166,
  pnl: 33190,
  dayChange: 4.9,
  dayChangePct: 0.41,
};
const SYNCED_AT = "2026-11-13T10:15:00.000Z";
const EXPIRES_AT = "2026-11-14T00:30:00.000Z";

function snapshot(
  holdings: unknown[],
  syncedAt: string | null,
  broker: "kite" | "upstox" | null = syncedAt ? "kite" : null,
) {
  return { holdings, syncedAt, broker };
}

beforeEach(() => {
  vi.resetAllMocks();
  window.history.replaceState({}, "", "/");
  api.fetchBrokerStatus.mockResolvedValue({ connected: false, expiresAt: null });
  api.fetchHoldings.mockResolvedValue(snapshot([], null));
});

describe("formatting", () => {
  it("groups digits in the Indian style with two decimals", () => {
    expect(formatInr(116600)).toBe("1,16,600.00");
    expect(formatInr(3306958.8)).toBe("33,06,958.80");
  });

  it("signs percentages and shows a dash when there is no value", () => {
    expect(formatSignedPct(39.79)).toBe("+39.79%");
    expect(formatSignedPct(-1.49)).toBe("-1.49%");
    expect(formatSignedPct(null)).toBe("—");
  });
});

describe("holding rows and totals", () => {
  const ace = toHoldingRow({
    symbol: "ACE",
    isin: null,
    quantity: 100,
    averagePrice: 834.1,
    lastPrice: 1166,
    pnl: 33190,
    dayChange: 4.9,
    dayChangePct: 0.41,
  });

  it("derives invested value, current value and net change from quantity and prices", () => {
    expect(ace.invested).toBeCloseTo(83410);
    expect(ace.curVal).toBeCloseTo(116600);
    expect(ace.netChgPct).toBeCloseTo((33190 / 83410) * 100);
    expect(ace.dayChg).toBeCloseTo(490);
  });

  it("totals invested, current value, P&L and the rupee day change", () => {
    const second = toHoldingRow({
      symbol: "BEL",
      isin: null,
      quantity: 100,
      averagePrice: 430,
      lastPrice: 394,
      pnl: -3600,
      dayChange: -3.5,
      dayChangePct: -0.89,
    });
    const total = totalHoldings([ace, second]);

    expect(total.invested).toBeCloseTo(83410 + 43000);
    expect(total.curVal).toBeCloseTo(116600 + 39400);
    expect(total.pnl).toBeCloseTo(33190 - 3600);
    expect(total.dayChg).toBeCloseTo(490 - 350);
  });

  it("leaves the net change empty when invested value is zero", () => {
    const free = toHoldingRow({
      symbol: "X",
      isin: null,
      quantity: 1,
      averagePrice: 0,
      lastPrice: 10,
      pnl: 10,
      dayChange: null,
      dayChangePct: null,
    });
    expect(free.netChgPct).toBeNull();
  });
});

describe("connection controls", () => {
  it("shows the login button when Kite is not connected", async () => {
    render(<HoldingsPanel />);

    expect(await screen.findByRole("button", { name: "Log in to Kite" })).toBeInTheDocument();
    expect(screen.getByText("Kite: not connected")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync portfolio" })).not.toBeInTheDocument();
  });

  it("requests the login URL and sends the browser to it", async () => {
    const loginUrl = "https://kite.zerodha.com/connect/login?v=3";
    api.requestLoginUrl.mockResolvedValue(loginUrl);
    render(<HoldingsPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Log in to Kite" }));

    await waitFor(() => expect(api.redirectToBrokerLogin).toHaveBeenCalledWith(loginUrl));
    expect(api.requestLoginUrl).toHaveBeenCalledWith("kite");
  });

  it("shows the connection expiry and the sync button when connected, and syncs", async () => {
    api.fetchBrokerStatus.mockResolvedValue({ connected: true, expiresAt: EXPIRES_AT });
    api.fetchHoldings
      .mockResolvedValueOnce(snapshot([HOLDING], SYNCED_AT))
      .mockResolvedValueOnce(snapshot([HOLDING], "2026-11-13T11:00:00.000Z"));
    api.syncPortfolio.mockResolvedValue({ syncedAt: "2026-11-13T11:00:00.000Z", broker: "kite", rowCount: 1 });
    render(<HoldingsPanel />);

    expect(await screen.findByText(`Kite: connected until ${formatLocalTime(EXPIRES_AT)}`)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Log in to Kite" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sync portfolio" }));

    await waitFor(() => expect(api.syncPortfolio).toHaveBeenCalledWith("kite"));
    await waitFor(() => expect(api.fetchHoldings).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Portfolio synced from Kite.")).toBeInTheDocument();
  });

  it("flips to not connected and shows the login notice when a sync is refused with login required", async () => {
    api.fetchBrokerStatus.mockResolvedValue({ connected: true, expiresAt: EXPIRES_AT });
    api.fetchHoldings.mockResolvedValue(snapshot([HOLDING], SYNCED_AT));
    api.syncPortfolio.mockRejectedValue(new BrokerError("login required", 401));
    render(<HoldingsPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Sync portfolio" }));

    expect(await screen.findByText(LOGIN_REQUIRED_NOTICE)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log in to Kite" })).toBeInTheDocument();
    expect(screen.getByText("Kite: not connected")).toBeInTheDocument();
  });

  it("shows the sync error for other failures and stays connected", async () => {
    api.fetchBrokerStatus.mockResolvedValue({ connected: true, expiresAt: EXPIRES_AT });
    api.fetchHoldings.mockResolvedValue(snapshot([HOLDING], SYNCED_AT));
    api.syncPortfolio.mockRejectedValue(new BrokerError("broker exchange failed", 502));
    render(<HoldingsPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Sync portfolio" }));

    expect(await screen.findByText("broker exchange failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync portfolio" })).toBeInTheDocument();
  });

  it("shows a status-unavailable line when the status read fails", async () => {
    api.fetchBrokerStatus.mockRejectedValue(new BrokerError("Could not reach the broker service.", null));
    render(<HoldingsPanel />);

    expect(await screen.findByText("Kite: status unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Log in to Kite" })).not.toBeInTheDocument();
  });
});

describe("login notice from the URL", () => {
  it("shows the success notice and removes the login parameters", async () => {
    window.history.replaceState({}, "", "/?broker=kite&login=ok");
    render(<HoldingsPanel />);

    expect(
      await screen.findByText("Kite login complete. Press Sync portfolio to load your holdings."),
    ).toBeInTheDocument();
    await waitFor(() => expect(window.location.search).toBe(""));
  });

  it("shows the failure notice and keeps unrelated parameters", async () => {
    window.history.replaceState({}, "", "/?view=holdings&broker=kite&login=failed");
    render(<HoldingsPanel />);

    expect(await screen.findByText("Kite login failed. Try again.")).toBeInTheDocument();
    await waitFor(() => expect(window.location.search).toBe("?view=holdings"));
  });
});

describe("broker switch", () => {
  it("opens on kite and switches to upstox, reading its status and holdings", async () => {
    render(<HoldingsPanel />);

    expect(await screen.findByRole("tab", { name: "Kite" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Upstox" }));

    expect(screen.getByRole("tab", { name: "Upstox" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Kite" })).toHaveAttribute("aria-selected", "false");
    expect(await screen.findByRole("button", { name: "Log in to Upstox" })).toBeInTheDocument();
    expect(api.fetchBrokerStatus).toHaveBeenCalledWith("upstox");
    expect(api.fetchHoldings).toHaveBeenLastCalledWith("default", "upstox", { signal: expect.any(AbortSignal) });
  });

  it("starts on upstox when the login redirect names it, and says so in the notice", async () => {
    window.history.replaceState({}, "", "/?broker=upstox&login=ok");
    render(<HoldingsPanel />);

    expect(
      await screen.findByText("Upstox login complete. Press Sync portfolio to load your holdings."),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Upstox" })).toHaveAttribute("aria-selected", "true");
    expect(api.fetchBrokerStatus).toHaveBeenCalledWith("upstox");
    await waitFor(() => expect(window.location.search).toBe(""));
  });

  it("starts on kite for an unknown broker parameter", async () => {
    window.history.replaceState({}, "", "/?broker=zerodha");
    render(<HoldingsPanel />);

    expect(await screen.findByRole("tab", { name: "Kite" })).toHaveAttribute("aria-selected", "true");
    expect(api.fetchBrokerStatus).toHaveBeenCalledWith("kite");
  });

  it("requests the Upstox login URL from the Upstox tab", async () => {
    const loginUrl = "https://api.upstox.com/v2/login/authorization/dialog?response_type=code";
    api.requestLoginUrl.mockResolvedValue(loginUrl);
    render(<HoldingsPanel />);

    fireEvent.click(await screen.findByRole("tab", { name: "Upstox" }));
    fireEvent.click(await screen.findByRole("button", { name: "Log in to Upstox" }));

    await waitFor(() => expect(api.redirectToBrokerLogin).toHaveBeenCalledWith(loginUrl));
    expect(api.requestLoginUrl).toHaveBeenCalledWith("upstox");
  });

  it("keeps one broker's error off the other broker's tab", async () => {
    api.fetchHoldings.mockImplementation(async (_profile: string, broker: string) => {
      if (broker === "kite") throw new HoldingsError("Kite snapshot could not be read.", 500);
      return snapshot([], null);
    });
    render(<HoldingsPanel />);

    expect(await screen.findByText("Kite snapshot could not be read.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Upstox" }));

    expect(await screen.findByText(noStoredPortfolio("upstox"))).toBeInTheDocument();
    expect(screen.queryByText("Kite snapshot could not be read.")).not.toBeInTheDocument();
  });

  it("syncs through the Upstox route and reports the Upstox sync", async () => {
    api.fetchBrokerStatus.mockImplementation(async (broker: string) =>
      broker === "upstox" ? { connected: true, expiresAt: EXPIRES_AT } : { connected: false, expiresAt: null },
    );
    api.fetchHoldings.mockResolvedValue(snapshot([HOLDING], SYNCED_AT, "upstox"));
    api.syncPortfolio.mockResolvedValue({ syncedAt: SYNCED_AT, broker: "upstox", rowCount: 1 });
    render(<HoldingsPanel />);

    fireEvent.click(await screen.findByRole("tab", { name: "Upstox" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sync portfolio" }));

    await waitFor(() => expect(api.syncPortfolio).toHaveBeenCalledWith("upstox"));
    expect(await screen.findByText("Portfolio synced from Upstox.")).toBeInTheDocument();
    expect(screen.getByText("ACE")).toBeInTheDocument();
  });

  it("shows the Upstox login-required notice and disconnects only the Upstox tab", async () => {
    api.fetchBrokerStatus.mockImplementation(async (broker: string) =>
      broker === "upstox" ? { connected: true, expiresAt: EXPIRES_AT } : { connected: false, expiresAt: null },
    );
    api.fetchHoldings.mockResolvedValue(snapshot([HOLDING], SYNCED_AT, "upstox"));
    api.syncPortfolio.mockRejectedValue(new BrokerError("login required", 401));
    render(<HoldingsPanel />);

    fireEvent.click(await screen.findByRole("tab", { name: "Upstox" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sync portfolio" }));

    expect(await screen.findByText(loginRequiredNotice("upstox"))).toBeInTheDocument();
    expect(screen.getByText("Upstox: not connected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log in to Upstox" })).toBeInTheDocument();
  });
});

describe("holdings body", () => {
  it("shows the empty state when no portfolio has been stored", async () => {
    render(<HoldingsPanel />);

    expect(await screen.findByText(NO_STORED_PORTFOLIO)).toBeInTheDocument();
    expect(screen.queryByText(/^Synced /)).not.toBeInTheDocument();
  });

  it("shows the synced-at stamp from the stored snapshot", async () => {
    api.fetchHoldings.mockResolvedValue(snapshot([HOLDING], SYNCED_AT));
    render(<HoldingsPanel />);

    expect(await screen.findByText(`Synced ${formatLocalTime(SYNCED_AT)}`)).toBeInTheDocument();
    expect(screen.getByText("ACE")).toBeInTheDocument();
  });

  it("shows the holdings error from the holdings client", async () => {
    api.fetchHoldings.mockRejectedValue(new HoldingsError("The holdings response had an unexpected shape.", 200));
    render(<HoldingsPanel />);

    expect(await screen.findByText("The holdings response had an unexpected shape.")).toBeInTheDocument();
  });
});
