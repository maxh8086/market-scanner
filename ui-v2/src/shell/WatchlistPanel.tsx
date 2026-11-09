import { useState, type FormEvent } from "react";
import { useLiveTicks, type LiveTick } from "../live/useLiveTicks";
import { ColumnResizeHandle, useColumnWidths } from "../table/columnWidths";
import {
  addCustomSymbol,
  DEFAULT_SEGMENT,
  type IndexSegment,
  loadCustomWatchlist,
  saveCustomWatchlist,
  SEGMENT_NAMES,
  segmentIndices,
} from "./watchlistStore";

type SegmentChoice = IndexSegment | "All Indices";
const SEGMENT_OPTIONS: ReadonlyArray<SegmentChoice> = [...SEGMENT_NAMES, "All Indices"];

const inr = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signed = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: "always" });

function formatPrice(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? inr.format(value) : "—";
}

/** Signed value with its colour and arrow. Zero and missing values are neutral. */
function formatMove(value: number | null, suffix: string): { text: string; tone: string; arrow: string } {
  if (value === null || !Number.isFinite(value)) {
    return { text: "—", tone: "text-text-muted", arrow: "" };
  }
  if (value === 0) {
    return { text: `0.00${suffix}`, tone: "text-text-muted", arrow: "" };
  }
  return {
    text: `${signed.format(value)}${suffix}`,
    tone: value > 0 ? "text-gain" : "text-loss",
    arrow: value > 0 ? "▲" : "▼",
  };
}

/** Change in points and percent, from the last price and the previous close. */
export function indexChange(ltp: number | null, prevClose: number | null): { points: number | null; percent: number | null } {
  if (ltp === null || prevClose === null || prevClose <= 0) {
    return { points: null, percent: null };
  }
  const points = ltp - prevClose;
  return { points, percent: (points / prevClose) * 100 };
}

const WATCHLIST_COLUMNS: ReadonlyArray<{ id: string; label: string; align: "left" | "right" }> = [
  { id: "index", label: "Index", align: "left" },
  { id: "price", label: "Price", align: "right" },
  { id: "chg", label: "Chg", align: "right" },
  { id: "chg_pct", label: "Chg %", align: "right" },
];

function IndexRow({ name, tick }: { name: string; tick: LiveTick | undefined }) {
  const ltp = tick?.ltp ?? null;
  const { points, percent } = indexChange(ltp, tick?.cp ?? null);
  const pts = formatMove(points, "");
  const pct = formatMove(percent, "%");
  const hasOhl = tick?.open != null || tick?.high != null || tick?.low != null;
  return (
    <tr className="border-b border-border/60 last:border-b-0">
      <th scope="row" className="py-1.5 pr-2 text-left font-medium">
        <span className="block truncate">{name}</span>
        {hasOhl ? (
          <span className="block text-xs font-normal tabular-nums text-text-muted">
            O {formatPrice(tick?.open)} · H {formatPrice(tick?.high)} · L {formatPrice(tick?.low)}
          </span>
        ) : null}
      </th>
      <td className="py-1.5 text-right tabular-nums">{formatPrice(ltp)}</td>
      <td className={`py-1.5 pl-2 text-right tabular-nums ${pts.tone}`}>
        {pts.arrow ? `${pts.arrow} ` : ""}
        {pts.text}
      </td>
      <td className={`py-1.5 pl-2 text-right tabular-nums ${pct.tone}`}>
        {pct.arrow ? `${pct.arrow} ` : ""}
        {pct.text}
      </td>
    </tr>
  );
}

function SymbolRow({ symbol, onRemove }: { symbol: string; onRemove: () => void }) {
  return (
    <li className="flex items-baseline justify-between gap-2 border-b border-border/60 py-1.5 last:border-b-0">
      <span className="truncate font-medium">{symbol}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${symbol}`}
        className="px-1 text-text-muted hover:text-loss"
      >
        ×
      </button>
    </li>
  );
}

export function WatchlistPanel() {
  const [custom, setCustom] = useState<string[]>(() => loadCustomWatchlist());
  const [segment, setSegment] = useState<SegmentChoice>(DEFAULT_SEGMENT);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const columnWidths = useColumnWidths();
  const hasManualWidths = Object.keys(columnWidths.widths).length > 0;
  const { ticks } = useLiveTicks({ runId: "", symbols: [], enabled: true, indices: true });

  const update = (next: string[]) => {
    setCustom(next);
    saveCustomWatchlist(next);
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const result = addCustomSymbol(custom, draft);
    setError(result.error);
    if (!result.error) {
      update(result.symbols);
      setDraft("");
    }
  };

  return (
    <section aria-labelledby="watchlist-heading" className="rounded-md border border-border bg-surface p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 id="watchlist-heading" className="text-sm font-semibold text-text">
          Market Watch
        </h2>
        <select
          aria-label="Index segment"
          value={segment}
          onChange={(event) => setSegment(event.target.value as SegmentChoice)}
          className="min-w-0 rounded-(--radius-control) border border-border-ui bg-bg px-2 py-1 text-sm text-text"
        >
          {SEGMENT_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </div>

      <div className="mb-3 overflow-x-auto">
      <table
        className={`w-full text-sm text-text whitespace-nowrap [&_td]:overflow-hidden [&_td]:text-ellipsis ${hasManualWidths ? "table-fixed" : "table-auto"}`}
      >
        <caption className="sr-only">{segment}</caption>
        <thead>
          <tr className="border-b border-border text-xs text-text-muted">
            {WATCHLIST_COLUMNS.map((column) => (
              <th
                key={column.id}
                data-col={column.id}
                scope="col"
                style={columnWidths.widths[column.id] !== undefined ? { width: columnWidths.widths[column.id] } : undefined}
                className={`relative pb-1 font-normal ${column.align === "left" ? "text-left" : "pl-2 text-right"}`}
              >
                <span className="block min-w-0 truncate">{column.label}</span>
                <ColumnResizeHandle
                  label={column.label}
                  onStart={(event) => columnWidths.startResize(event, column.id)}
                  onReset={columnWidths.reset}
                />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {segmentIndices(segment).map((name) => (
            <IndexRow key={name} name={name} tick={ticks.get(name)} />
          ))}
        </tbody>
      </table>
      </div>

      <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-muted">Custom</h3>
      <form onSubmit={onSubmit} className="mb-2 flex gap-2">
        <label htmlFor="watchlist-add" className="sr-only">
          Add a stock or index
        </label>
        <input
          id="watchlist-add"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            setError(null);
          }}
          placeholder="Add symbol, e.g. RELIANCE"
          autoComplete="off"
          className="min-w-0 flex-1 rounded-(--radius-control) border border-border-ui bg-bg px-2 py-1 text-sm text-text"
        />
        <button
          type="submit"
          className="rounded-(--radius-control) border border-border-ui px-2 py-1 text-sm text-text"
        >
          Add
        </button>
      </form>
      {error ? <p className="mb-2 text-xs text-loss">{error}</p> : null}

      {custom.length === 0 ? (
        <p className="text-sm text-text-muted">No custom symbols yet.</p>
      ) : (
        <ul className="text-sm text-text">
          {custom.map((symbol) => (
            <SymbolRow key={symbol} symbol={symbol} onRemove={() => update(custom.filter((item) => item !== symbol))} />
          ))}
        </ul>
      )}
    </section>
  );
}
