import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import {
  BROKER_NAMES,
  BrokerError,
  brokerLabel,
  DEFAULT_PROFILE,
  fetchBrokerStatus,
  isBrokerName,
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

const LOGIN_PARAM = "login";
const BROKER_PARAM = "broker";
const BODY_ID = "holdings-broker-panel";

export function loginRequiredNotice(broker: BrokerName): string {
  return `Login required. Log in to ${brokerLabel(broker)} again.`;
}

export function noStoredPortfolio(broker: BrokerName): string {
  return `No stored portfolio yet. Log in to ${brokerLabel(broker)} and press Sync portfolio.`;
}

export const LOGIN_REQUIRED_NOTICE = loginRequiredNotice("kite");
export const NO_STORED_PORTFOLIO = noStoredPortfolio("kite");

/** The broker named by the `broker` parameter of a URL, or kite when it is missing or unknown. */
export function brokerFromSearch(search: string): BrokerName {
  const value = new URLSearchParams(search).get(BROKER_PARAM);
  return isBrokerName(value) ? value : "kite";
}

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
  const label = brokerLabel(brokerFromSearch(search));
  if (login === "ok") return { tone: "ok", text: `${label} login complete. Press Sync portfolio to load your holdings.` };
  if (login === "failed") return { tone: "bad", text: `${label} login failed. Try again.` };
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

function connectionText(connection: ConnectionState, broker: BrokerName): string {
  const label = brokerLabel(broker);
  switch (connection.kind) {
    case "checking":
      return `${label}: checking…`;
    case "connected":
      return connection.expiresAt
        ? `${label}: connected until ${formatLocalTime(connection.expiresAt)}`
        : `${label}: connected`;
    case "disconnected":
      return `${label}: not connected`;
    case "unavailable":
      return `${label}: status unavailable`;
  }
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

const BUTTON_CLASS =
  "whitespace-nowrap rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text disabled:cursor-not-allowed disabled:opacity-50";

export function HoldingsPanel() {
  // Read once on mount: the login callback's broker and notice are in the URL until the effect below removes them.
  const [broker, setBroker] = useState<BrokerName>(() => brokerFromSearch(window.location.search));
  const [rows, setRows] = useState<HoldingRow[] | null>(null);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  const [holdingsError, setHoldingsError] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionState>({ kind: "checking" });
  const [notice, setNotice] = useState<Notice | null>(() => loginNoticeFromSearch(window.location.search));
  const [loginBusy, setLoginBusy] = useState(false);
  const [syncing, setSyncing] = useState(false);
  // The broker the user has selected now. Async results for any other broker are dropped.
  const selectedBroker = useRef<BrokerName>(broker);
  const tabRefs = useRef<Partial<Record<BrokerName, HTMLButtonElement | null>>>({});
  const columnWidths = useColumnWidths();
  const hasManualWidths = Object.keys(columnWidths.widths).length > 0;

  useEffect(() => {
    clearLoginParams();
  }, []);

  const loadHoldings = useCallback(async (target: BrokerName, signal?: AbortSignal) => {
    try {
      const snapshot = await fetchHoldings(DEFAULT_PROFILE, target, { signal });
      if (signal?.aborted || selectedBroker.current !== target) return;
      setRows(snapshot.holdings.map(toHoldingRow));
      setSyncedAt(snapshot.syncedAt);
      setHoldingsError(null);
    } catch (caught: unknown) {
      if (signal?.aborted || selectedBroker.current !== target) return;
      setHoldingsError(caught instanceof HoldingsError ? caught.message : "Could not load holdings.");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadHoldings(broker, controller.signal);
    fetchBrokerStatus(broker)
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
  }, [broker, loadHoldings]);

  /** Switches the panel to another broker and clears everything that belonged to the previous one. */
  function selectBroker(next: BrokerName) {
    if (next === selectedBroker.current) return;
    selectedBroker.current = next;
    setBroker(next);
    setRows(null);
    setSyncedAt(null);
    setHoldingsError(null);
    setConnection({ kind: "checking" });
    setNotice(null);
    setLoginBusy(false);
    setSyncing(false);
  }

  /** Arrow keys, Home and End move between the broker tabs, as the tablist pattern asks. */
  function handleTabKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = BROKER_NAMES.indexOf(broker);
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % BROKER_NAMES.length;
    else if (event.key === "ArrowLeft") nextIndex = (index - 1 + BROKER_NAMES.length) % BROKER_NAMES.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = BROKER_NAMES.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const next = BROKER_NAMES[nextIndex];
    selectBroker(next);
    tabRefs.current[next]?.focus();
  }

  async function handleLogin() {
    const target = broker;
    setLoginBusy(true);
    setNotice(null);
    try {
      const url = await requestLoginUrl(target);
      // The page leaves here; the busy state stays on until then. A broker the user has left is not sent anywhere.
      if (selectedBroker.current === target) redirectToBrokerLogin(url);
    } catch (error) {
      if (selectedBroker.current !== target) return;
      setNotice({ tone: "bad", text: messageOf(error) });
      setLoginBusy(false);
    }
  }

  async function handleSync() {
    const target = broker;
    const label = brokerLabel(target);
    const isCurrent = () => selectedBroker.current === target;
    setSyncing(true);
    setNotice({ tone: "neutral", text: `Syncing portfolio from ${label}…` });
    try {
      await syncPortfolio(target);
      if (!isCurrent()) return;
      setNotice({ tone: "ok", text: `Portfolio synced from ${label}.` });
      await loadHoldings(target);
    } catch (error) {
      if (!isCurrent()) return;
      if (error instanceof BrokerError && error.status === 401) {
        setConnection({ kind: "disconnected" });
        setNotice({ tone: "bad", text: loginRequiredNotice(target) });
      } else {
        setNotice({ tone: "bad", text: messageOf(error) });
      }
    } finally {
      if (isCurrent()) setSyncing(false);
    }
  }

  const total = rows ? totalHoldings(rows) : null;
  const label = brokerLabel(broker);
  const noticeClass = notice?.tone === "bad" ? "text-loss" : notice?.tone === "ok" ? "text-gain" : "text-text-muted";

  return (
    <section aria-labelledby="holdings-heading" className="rounded-md border border-border bg-surface p-4">
      <h2 id="holdings-heading" className="mb-2 text-sm font-semibold text-text">
        Holdings{rows ? ` (${rows.length})` : ""}
      </h2>

      <div
        role="tablist"
        aria-label="Broker"
        onKeyDown={handleTabKeyDown}
        className="mb-2 flex gap-4 border-b border-border"
      >
        {BROKER_NAMES.map((name) => {
          const selected = name === broker;
          return (
            <button
              key={name}
              ref={(element) => {
                tabRefs.current[name] = element;
              }}
              type="button"
              role="tab"
              id={`broker-tab-${name}`}
              aria-selected={selected}
              aria-controls={BODY_ID}
              tabIndex={selected ? 0 : -1}
              onClick={() => selectBroker(name)}
              className={`-mb-px border-b-2 px-1 py-1.5 text-sm ${
                selected ? "border-accent font-semibold text-accent" : "border-transparent text-text-muted"
              }`}
            >
              {brokerLabel(name)}
            </button>
          );
        })}
      </div>

      <div id={BODY_ID} role="tabpanel" aria-labelledby={`broker-tab-${broker}`}>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <span className="text-text-muted">{connectionText(connection, broker)}</span>
            {connection.kind === "disconnected" ? (
              <button type="button" onClick={handleLogin} disabled={loginBusy} className={BUTTON_CLASS}>
                Log in to {label}
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
          </div>
          {syncedAt ? <span className="text-xs text-text-muted">Synced {formatLocalTime(syncedAt)}</span> : null}
        </div>

        <div aria-live="polite">
          {notice ? <p className={`mb-2 text-sm ${noticeClass}`}>{notice.text}</p> : null}
        </div>

        {holdingsError ? (
          <StateView kind="error" message={holdingsError} />
        ) : rows === null ? (
          <StateView kind="loading" message="Loading holdings…" />
        ) : rows.length === 0 ? (
          <StateView kind="empty" message={syncedAt ? "No holdings found." : noStoredPortfolio(broker)} />
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
      </div>
    </section>
  );
}
