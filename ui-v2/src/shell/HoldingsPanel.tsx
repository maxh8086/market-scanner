import { useCallback, useEffect, useState } from "react";
import {
  BrokerError,
  fetchBrokerStatus,
  redirectToBrokerLogin,
  requestLoginUrl,
  syncPortfolio,
  type BrokerName,
} from "../api/broker";
import { fetchHoldings, HoldingsError, type Holding } from "../api/holdings";
import { ColumnResizeHandle, useColumnWidths } from "../table/columnWidths";
import { StateView } from "./StateView";

export interface HoldingRow {
  symbol: string;
  quantity: number;
  avgCost: number;
  ltp: number;
  invested: number;
  curVal: number;
  pnl: number;
  /** Net change: P&L as a percent of invested. */
  netChgPct: number | null;
  /** Today's change in rupees for the whole position. */
  dayChg: number | null;
  dayChgPct: number | null;
}

export interface HoldingsTotal {
  invested: number;
  curVal: number;
  pnl: number;
  netChgPct: number | null;
  dayChg: number;
  dayChgPct: number | null;
}

const inr = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Indian digit grouping (1,16,600.00), two decimals. */
export function formatInr(value: number): string {
  return inr.format(value);
}

/** Signed percent with two decimals, e.g. +39.79% or -1.49%. */
export function formatSignedPct(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/** Date and time of a stored ISO instant in the browser's time zone. */
export function formatLocalTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "unknown time";
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function toHoldingRow(holding: Holding): HoldingRow {
  const invested = holding.quantity * holding.averagePrice;
  const curVal = holding.quantity * holding.lastPrice;
  const dayChg = holding.dayChange === null ? null : holding.dayChange * holding.quantity;
  return {
    symbol: holding.symbol,
    quantity: holding.quantity,
    avgCost: holding.averagePrice,
    ltp: holding.lastPrice,
    invested,
    curVal,
    pnl: holding.pnl,
    netChgPct: invested > 0 ? (holding.pnl / invested) * 100 : null,
    dayChg,
    dayChgPct: holding.dayChangePct,
  };
}

export function totalHoldings(rows: readonly HoldingRow[]): HoldingsTotal {
  let invested = 0;
  let curVal = 0;
  let pnl = 0;
  let dayChg = 0;
  let previousValue = 0;
  for (const row of rows) {
    invested += row.invested;
    curVal += row.curVal;
    pnl += row.pnl;
    if (row.dayChg !== null) {
      dayChg += row.dayChg;
      previousValue += row.curVal - row.dayChg;
    }
  }
  return {
    invested,
    curVal,
    pnl,
    netChgPct: invested > 0 ? (pnl / invested) * 100 : null,
    dayChg,
    dayChgPct: previousValue > 0 ? (dayChg / previousValue) * 100 : null,
  };
}

function toneClass(value: number | null): string {
  if (value === null || value === 0) return "text-text";
  return value > 0 ? "text-gain" : "text-loss";
}

const HEADERS: Array<{ label: string; align: "left" | "right" }> = [
  { label: "Instrument", align: "left" },
  { label: "Qty.", align: "right" },
  { label: "Avg cost", align: "right" },
  { label: "LTP", align: "right" },
  { label: "Day chg.", align: "right" },
  { label: "Day chg. %", align: "right" },
  { label: "Invested", align: "right" },
  { label: "Cur. val", align: "right" },
  { label: "P&L", align: "right" },
  { label: "Net chg.", align: "right" },
];

const KITE: BrokerName = "kite";
const LOGIN_PARAM = "login";
const BROKER_PARAM = "broker";
export const LOGIN_REQUIRED_NOTICE = "Login required. Log in to Kite again.";
export const NO_STORED_PORTFOLIO = "No stored portfolio yet. Log in to Kite and press Sync portfolio.";
const LOGIN_OK_NOTICE = "Kite login complete. Press Sync portfolio to load your holdings.";
const LOGIN_FAILED_NOTICE = "Kite login failed. Try again.";

/** Broker connection as the server reports it. "checking" until the first status read finishes. */
type ConnectionState =
  | { kind: "checking" }
  | { kind: "connected"; expiresAt: string | null }
  | { kind: "disconnected" }
  | { kind: "unavailable" };

interface Notice {
  tone: "ok" | "bad" | "neutral";
  text: string;
}

/** The notice for the `login` parameter the server's callback put in the URL. Null when there is none. */
export function loginNoticeFromSearch(search: string): Notice | null {
  const login = new URLSearchParams(search).get(LOGIN_PARAM);
  if (login === "ok") return { tone: "ok", text: LOGIN_OK_NOTICE };
  if (login === "failed") return { tone: "bad", text: LOGIN_FAILED_NOTICE };
  return null;
}

/** Removes the login notice parameters from the address bar. Other parameters and the hash are kept. */
function clearLoginParams(): void {
  const url = new URL(window.location.href);
  if (!url.searchParams.has(LOGIN_PARAM) && !url.searchParams.has(BROKER_PARAM)) return;
  url.searchParams.delete(LOGIN_PARAM);
  url.searchParams.delete(BROKER_PARAM);
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
}

function connectionText(connection: ConnectionState): string {
  switch (connection.kind) {
    case "checking":
      return "Kite: checking…";
    case "connected":
      return connection.expiresAt
        ? `Kite: connected until ${formatLocalTime(connection.expiresAt)}`
        : "Kite: connected";
    case "disconnected":
      return "Kite: not connected";
    case "unavailable":
      return "Kite: status unavailable";
  }
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

const BUTTON_CLASS =
  "whitespace-nowrap rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text disabled:cursor-not-allowed disabled:opacity-50";

export function HoldingsPanel() {
  const [rows, setRows] = useState<HoldingRow[] | null>(null);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  const [holdingsError, setHoldingsError] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionState>({ kind: "checking" });
  // Read once on mount: the login callback's notice is in the URL until the effect below removes it.
  const [notice, setNotice] = useState<Notice | null>(() => loginNoticeFromSearch(window.location.search));
  const [loginBusy, setLoginBusy] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const columnWidths = useColumnWidths();
  const hasManualWidths = Object.keys(columnWidths.widths).length > 0;

  useEffect(() => {
    clearLoginParams();
  }, []);

  const loadHoldings = useCallback(async (signal?: AbortSignal) => {
    try {
      const snapshot = await fetchHoldings({ signal });
      if (signal?.aborted) return;
      setRows(snapshot.holdings.map(toHoldingRow));
      setSyncedAt(snapshot.syncedAt);
      setHoldingsError(null);
    } catch (caught: unknown) {
      if (signal?.aborted) return;
      setHoldingsError(caught instanceof HoldingsError ? caught.message : "Could not load holdings.");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadHoldings(controller.signal);
    fetchBrokerStatus(KITE)
      .then((status) => {
        if (controller.signal.aborted) return;
        setConnection(
          status.connected ? { kind: "connected", expiresAt: status.expiresAt } : { kind: "disconnected" },
        );
      })
      .catch(() => {
        if (!controller.signal.aborted) setConnection({ kind: "unavailable" });
      });
    return () => controller.abort();
  }, [loadHoldings]);

  async function handleLogin() {
    setLoginBusy(true);
    setNotice(null);
    try {
      const url = await requestLoginUrl(KITE);
      // The page leaves here; the busy state stays on until then.
      redirectToBrokerLogin(url);
    } catch (error) {
      setNotice({ tone: "bad", text: messageOf(error) });
      setLoginBusy(false);
    }
  }

  async function handleSync() {
    setSyncing(true);
    setNotice({ tone: "neutral", text: "Syncing portfolio from Kite…" });
    try {
      await syncPortfolio(KITE);
      setNotice({ tone: "ok", text: "Portfolio synced from Kite." });
      await loadHoldings();
    } catch (error) {
      if (error instanceof BrokerError && error.status === 401) {
        setConnection({ kind: "disconnected" });
        setNotice({ tone: "bad", text: LOGIN_REQUIRED_NOTICE });
      } else {
        setNotice({ tone: "bad", text: messageOf(error) });
      }
    } finally {
      setSyncing(false);
    }
  }

  const total = rows ? totalHoldings(rows) : null;
  const noticeClass = notice?.tone === "bad" ? "text-loss" : notice?.tone === "ok" ? "text-gain" : "text-text-muted";

  return (
    <section aria-labelledby="holdings-heading" className="rounded-md border border-border bg-surface p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h2 id="holdings-heading" className="text-sm font-semibold text-text">
          Holdings{rows ? ` (${rows.length})` : ""}
        </h2>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <span className="text-text-muted">{connectionText(connection)}</span>
          {connection.kind === "disconnected" ? (
            <button type="button" onClick={handleLogin} disabled={loginBusy} className={BUTTON_CLASS}>
              Log in to Kite
            </button>
          ) : null}
          {connection.kind === "connected" ? (
            <button
              type="button"
              onClick={handleSync}
              disabled={syncing}
              aria-busy={syncing ? "true" : undefined}
              className={BUTTON_CLASS}
            >
              Sync portfolio
            </button>
          ) : null}
          {syncedAt ? <span className="text-xs text-text-muted">Synced {formatLocalTime(syncedAt)}</span> : null}
        </div>
      </div>

      <div aria-live="polite">
        {notice ? <p className={`mb-2 text-sm ${noticeClass}`}>{notice.text}</p> : null}
      </div>

      {holdingsError ? (
        <StateView kind="error" message={holdingsError} />
      ) : rows === null ? (
        <StateView kind="loading" message="Loading holdings…" />
      ) : rows.length === 0 ? (
        <StateView kind="empty" message={syncedAt ? "No holdings found." : NO_STORED_PORTFOLIO} />
      ) : (
        <div className="overflow-x-auto">
          <table
            className={`w-full text-sm tabular-nums whitespace-nowrap [&_td]:overflow-hidden [&_td]:text-ellipsis ${hasManualWidths ? "table-fixed" : "table-auto"}`}
          >
            <thead>
              <tr className="border-b border-border text-xs text-text-muted">
                {HEADERS.map((header) => (
                  <th
                    key={header.label}
                    data-col={header.label}
                    scope="col"
                    style={
                      columnWidths.widths[header.label] !== undefined
                        ? { width: columnWidths.widths[header.label] }
                        : undefined
                    }
                    className={`relative px-2 py-1.5 font-normal ${header.align === "right" ? "text-right" : "text-left"}`}
                  >
                    <span className="block min-w-0 truncate">{header.label}</span>
                    <ColumnResizeHandle
                      label={header.label}
                      onStart={(event) => columnWidths.startResize(event, header.label)}
                      onReset={columnWidths.reset}
                    />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.symbol} className="border-b border-border/60 text-text">
                  <th scope="row" className="px-2 py-1.5 text-left font-medium">
                    {row.symbol}
                  </th>
                  <td className="px-2 py-1.5 text-right">{row.quantity}</td>
                  <td className="px-2 py-1.5 text-right">{formatInr(row.avgCost)}</td>
                  <td className="px-2 py-1.5 text-right">{formatInr(row.ltp)}</td>
                  <td className={`px-2 py-1.5 text-right ${toneClass(row.dayChg)}`}>
                    {row.dayChg === null ? "—" : formatInr(row.dayChg)}
                  </td>
                  <td className={`px-2 py-1.5 text-right ${toneClass(row.dayChgPct)}`}>
                    {formatSignedPct(row.dayChgPct)}
                  </td>
                  <td className="px-2 py-1.5 text-right">{formatInr(row.invested)}</td>
                  <td className="px-2 py-1.5 text-right">{formatInr(row.curVal)}</td>
                  <td className={`px-2 py-1.5 text-right ${toneClass(row.pnl)}`}>{formatInr(row.pnl)}</td>
                  <td className={`px-2 py-1.5 text-right ${toneClass(row.netChgPct)}`}>
                    {formatSignedPct(row.netChgPct)}
                  </td>
                </tr>
              ))}
            </tbody>
            {total ? (
              <tfoot>
                <tr className="font-semibold text-text">
                  <th scope="row" className="px-2 py-1.5 text-left">
                    Total
                  </th>
                  <td />
                  <td />
                  <td />
                  <td className={`px-2 py-1.5 text-right ${toneClass(total.dayChg)}`}>{formatInr(total.dayChg)}</td>
                  <td className={`px-2 py-1.5 text-right ${toneClass(total.dayChgPct)}`}>
                    {formatSignedPct(total.dayChgPct)}
                  </td>
                  <td className="px-2 py-1.5 text-right">{formatInr(total.invested)}</td>
                  <td className="px-2 py-1.5 text-right">{formatInr(total.curVal)}</td>
                  <td className={`px-2 py-1.5 text-right ${toneClass(total.pnl)}`}>{formatInr(total.pnl)}</td>
                  <td className={`px-2 py-1.5 text-right ${toneClass(total.netChgPct)}`}>
                    {formatSignedPct(total.netChgPct)}
                  </td>
                </tr>
              </tfoot>
            ) : null}
          </table>
        </div>
      )}
    </section>
  );
}
