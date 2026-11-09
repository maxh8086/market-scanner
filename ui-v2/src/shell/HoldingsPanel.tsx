import { useEffect, useState } from "react";
import { fetchHoldings, HoldingsError, type Holding } from "../api/holdings";
import { ColumnResizeHandle, useColumnWidths } from "../table/columnWidths";

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

export function HoldingsPanel() {
  const [rows, setRows] = useState<HoldingRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const columnWidths = useColumnWidths();
  const hasManualWidths = Object.keys(columnWidths.widths).length > 0;

  useEffect(() => {
    const controller = new AbortController();
    fetchHoldings({ signal: controller.signal })
      .then((holdings) => {
        setRows(holdings.map(toHoldingRow));
        setError(null);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(caught instanceof HoldingsError ? caught.message : "Could not load holdings.");
      });
    return () => controller.abort();
  }, []);

  const total = rows ? totalHoldings(rows) : null;

  return (
    <section aria-labelledby="holdings-heading" className="rounded-md border border-border bg-surface p-4">
      <h2 id="holdings-heading" className="mb-2 text-sm font-semibold text-text">
        Holdings{rows ? ` (${rows.length})` : ""}
      </h2>

      {error ? (
        <p className="text-sm text-loss">{error}</p>
      ) : rows === null ? (
        <p className="text-sm text-text-muted">Loading holdings…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-text-muted">No holdings found.</p>
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
