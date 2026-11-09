import { useEffect, useRef, useState, type FormEvent } from "react";
import { useLiveTicks, type LiveTick } from "../live/useLiveTicks";
import { getMarketSession } from "../lib/marketSession";
import { ColumnResizeHandle, useColumnWidths } from "../table/columnWidths";
import {
  addCustomSymbol,
  type IndexSegment,
  loadCustomWatchlist,
  saveCustomWatchlist,
  SEGMENT_NAMES,
  segmentIndices,
} from "./watchlistStore";

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

/** How often the panel re-checks whether the market is open, so the live feed starts and stops on its own. */
const SESSION_CHECK_MS = 60_000;
/** How often the last index closes are re-fetched while the market is shut. */
const EOD_REFRESH_MS = 5 * 60_000;

/** Visible-row changes are published at most this often, so fast scrolling does not reconnect the feed on every row. */
const VISIBLE_PUBLISH_MS = 300;
export const INDEX_EOD_URL = "/api/index-eod";

const NO_EOD_TICKS: ReadonlyMap<string, LiveTick> = new Map();

/** Maps the /api/index-eod body to the tick shape the table reads: ltp = close, cp = previous close, plus the day's open, high and low. */
export function eodTicksFromResponse(body: unknown): Map<string, LiveTick> {
  const ticks = new Map<string, LiveTick>();
  const indices = body && typeof body === "object" ? (body as { indices?: unknown }).indices : undefined;
  if (!Array.isArray(indices)) return ticks;
  const finiteOrNull = (value: unknown): number | null =>
    typeof value === "number" && Number.isFinite(value) ? value : null;
  for (const item of indices) {
    if (!item || typeof item !== "object") continue;
    const row = item as { name?: unknown; close?: unknown; prevClose?: unknown; open?: unknown; high?: unknown; low?: unknown };
    if (typeof row.name !== "string" || typeof row.close !== "number" || !Number.isFinite(row.close)) continue;
    ticks.set(row.name, {
      symbol: row.name,
      ltp: row.close,
      ltt: null,
      cp: finiteOrNull(row.prevClose),
      open: finiteOrNull(row.open),
      high: finiteOrNull(row.high),
      low: finiteOrNull(row.low),
    });
  }
  return ticks;
}

/** Optional columns the user can switch on or off with the gear control. Price and Index are always shown. */
type ColumnId = "chg" | "chg_pct" | "open" | "high" | "low" | "prev_close";

const OPTIONAL_COLUMNS: ReadonlyArray<{ id: ColumnId; label: string }> = [
  { id: "chg", label: "Chg" },
  { id: "chg_pct", label: "Chg %" },
  { id: "open", label: "Open" },
  { id: "high", label: "High" },
  { id: "low", label: "Low" },
  { id: "prev_close", label: "Prev. Close" },
];
const DEFAULT_VISIBLE: ColumnId[] = ["chg", "chg_pct", "open", "high", "low"];
const COLUMNS_STORAGE_KEY = "marketScanner.watchlistColumns";

/** Per-browser column choice. Unknown ids are dropped; a broken value falls back to the defaults. */
function loadVisibleColumns(): ColumnId[] {
  try {
    const raw = window.localStorage.getItem(COLUMNS_STORAGE_KEY);
    if (!raw) return [...DEFAULT_VISIBLE];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [...DEFAULT_VISIBLE];
    const known = new Set<string>(OPTIONAL_COLUMNS.map((column) => column.id));
    return parsed.filter((item): item is ColumnId => typeof item === "string" && known.has(item));
  } catch {
    return [...DEFAULT_VISIBLE];
  }
}

function saveVisibleColumns(ids: readonly ColumnId[]): void {
  try {
    window.localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // Storage is blocked or full. The choice still applies for this session.
  }
}

function IndexRow({ name, tick, columns }: { name: string; tick: LiveTick | undefined; columns: readonly ColumnId[] }) {
  const ltp = tick?.ltp ?? null;
  const prevClose = tick?.cp ?? null;
  const { points, percent } = indexChange(ltp, prevClose);
  const pts = formatMove(points, "");
  const pct = formatMove(percent, "%");
  const cell = (id: ColumnId) => {
    switch (id) {
      case "chg":
        return (
          <td key={id} className={`py-1.5 pl-2 text-right tabular-nums ${pts.tone}`}>
            {pts.arrow ? `${pts.arrow} ` : ""}
            {pts.text}
          </td>
        );
      case "chg_pct":
        return (
          <td key={id} className={`py-1.5 pl-2 text-right tabular-nums ${pct.tone}`}>
            {pct.arrow ? `${pct.arrow} ` : ""}
            {pct.text}
          </td>
        );
      case "open":
        return <td key={id} className="py-1.5 pl-2 text-right tabular-nums">{formatPrice(tick?.open)}</td>;
      case "high":
        return <td key={id} className="py-1.5 pl-2 text-right tabular-nums">{formatPrice(tick?.high)}</td>;
      case "low":
        return <td key={id} className="py-1.5 pl-2 text-right tabular-nums">{formatPrice(tick?.low)}</td>;
      case "prev_close":
        return <td key={id} className="py-1.5 pl-2 text-right tabular-nums">{formatPrice(prevClose)}</td>;
    }
  };
  return (
    <tr data-index-name={name} className="border-b border-border/60 last:border-b-0">
      <th scope="row" className="py-1.5 pr-2 text-left font-medium">
        <span className="block truncate">{name}</span>
      </th>
      <td className="py-1.5 pl-2 text-right tabular-nums">{formatPrice(ltp)}</td>
      {columns.map((id) => cell(id))}
    </tr>
  );
}

/** Divider row that labels a Market Watch section. */
function SectionDivider({ label, span }: { label: string; span: number }) {
  return (
    <tr>
      <th
        scope="colgroup"
        colSpan={span}
        className="border-b border-border bg-surface pb-1 pt-3 text-left text-xs font-medium uppercase tracking-wide text-text-muted"
      >
        {label}
      </th>
    </tr>
  );
}

/** One section: its divider followed by its index rows. */
function SectionGroup({
  label,
  names,
  ticks,
  columns,
}: {
  label: IndexSegment;
  names: readonly string[];
  ticks: ReadonlyMap<string, LiveTick>;
  columns: readonly ColumnId[];
}) {
  return (
    <>
      <SectionDivider label={label} span={columns.length + 2} />
      {names.map((name) => (
        <IndexRow key={name} name={name} tick={ticks.get(name.toUpperCase())} columns={columns} />
      ))}
    </>
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

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

export function WatchlistPanel() {
  const [custom, setCustom] = useState<string[]>(() => loadCustomWatchlist());
  const [visible, setVisible] = useState<ColumnId[]>(() => loadVisibleColumns());
  const [chooserOpen, setChooserOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const columnWidths = useColumnWidths();
  const hasManualWidths = Object.keys(columnWidths.widths).length > 0;
  const [now, setNow] = useState(() => new Date());
  const live = getMarketSession(now).status === "open";
  const scrollRef = useRef<HTMLDivElement>(null);
  const [visibleNames, setVisibleNames] = useState<string[]>([]);
  const { ticks: liveTicks } = useLiveTicks({ runId: "", symbols: visibleNames, enabled: live, indices: true });
  const [eodTicks, setEodTicks] = useState<ReadonlyMap<string, LiveTick>>(NO_EOD_TICKS);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), SESSION_CHECK_MS);
    return () => clearInterval(timer);
  }, []);

  // Tracks which index rows are inside the scroll area, so the live feed subscribes only to those.
  // Without IntersectionObserver (for example in jsdom) every row counts as visible.
  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    const rows = Array.from(root.querySelectorAll<HTMLElement>("tr[data-index-name]"));
    const allNames = rows.map((row) => row.dataset.indexName ?? "").filter((name) => name !== "");
    if (typeof IntersectionObserver === "undefined") {
      setVisibleNames(allNames);
      return;
    }
    const inView = new Set<string>();
    let timer: ReturnType<typeof setTimeout> | null = null;
    const publish = () => {
      timer = null;
      setVisibleNames([...inView].sort());
    };
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const name = (entry.target as HTMLElement).dataset.indexName ?? "";
          if (entry.isIntersecting) inView.add(name);
          else inView.delete(name);
        }
        if (timer === null) timer = setTimeout(publish, VISIBLE_PUBLISH_MS);
      },
      { root, threshold: 0 },
    );
    rows.forEach((row) => observer.observe(row));
    return () => {
      observer.disconnect();
      if (timer !== null) clearTimeout(timer);
    };
  }, []);

  // Last stored index closes, used while the market is shut. Fetched on mount and every few minutes.
  useEffect(() => {
    let controller: AbortController | null = null;
    const load = async () => {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      try {
        const response = await fetch(INDEX_EOD_URL, { signal: current.signal });
        if (!response.ok) throw new Error(`index EOD ${response.status}`);
        const next = eodTicksFromResponse(await response.json());
        if (!current.signal.aborted) setEodTicks(next);
      } catch {
        // No EOD data: rows keep showing a dash. An aborted request is the unmount path, not an error.
        if (!current.signal.aborted) setEodTicks(NO_EOD_TICKS);
      }
    };
    void load();
    const timer = setInterval(() => void load(), EOD_REFRESH_MS);
    return () => {
      clearInterval(timer);
      controller?.abort();
    };
  }, []);

  const ticks = live ? liveTicks : eodTicks;
  const columns = OPTIONAL_COLUMNS.filter((column) => visible.includes(column.id)).map((column) => column.id);

  const toggleColumn = (id: ColumnId) => {
    const next = visible.includes(id) ? visible.filter((item) => item !== id) : [...visible, id];
    setVisible(next);
    saveVisibleColumns(next);
  };

  const resetColumns = () => {
    setVisible([...DEFAULT_VISIBLE]);
    saveVisibleColumns(DEFAULT_VISIBLE);
  };

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
        <div className="relative">
          <button
            type="button"
            onClick={() => setChooserOpen((open) => !open)}
            aria-label="Choose columns"
            aria-expanded={chooserOpen}
            aria-haspopup="dialog"
            title="Choose columns"
            className="rounded-(--radius-control) p-1 text-text-muted hover:text-text"
          >
            <GearIcon />
          </button>
          {chooserOpen ? (
            <div
              role="dialog"
              aria-label="Choose columns"
              className="absolute right-0 z-20 mt-1 w-56 rounded-md border border-border-ui bg-surface p-3 shadow-md"
            >
              <p className="mb-2 text-xs font-medium text-text">Choose your columns</p>
              <p className="mb-2 text-xs text-text-muted">Index and Price always show.</p>
              <ul className="mb-3 space-y-1.5 text-sm text-text">
                {OPTIONAL_COLUMNS.map((column) => (
                  <li key={column.id}>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={visible.includes(column.id)}
                        onChange={() => toggleColumn(column.id)}
                      />
                      {column.label}
                    </label>
                  </li>
                ))}
              </ul>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={resetColumns}
                  className="rounded-(--radius-control) border border-border-ui px-2 py-1 text-sm text-text"
                >
                  Reset
                </button>
                <button
                  type="button"
                  onClick={() => setChooserOpen(false)}
                  className="rounded-(--radius-control) bg-text px-2 py-1 text-sm text-bg"
                >
                  Done
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <div ref={scrollRef} className="mb-3 max-h-[28rem] overflow-auto">
        <table
          className={`w-full text-sm text-text whitespace-nowrap [&_td]:overflow-hidden [&_td]:text-ellipsis ${hasManualWidths ? "table-fixed" : "table-auto"}`}
        >
          <caption className="sr-only">Market Watch indices</caption>
          <thead className="sticky top-0 z-10 bg-surface">
            <tr className="border-b border-border text-xs text-text-muted">
              {[
                { id: "index", label: "Index", align: "left" as const },
                { id: "price", label: "Price", align: "right" as const },
                ...OPTIONAL_COLUMNS.filter((column) => columns.includes(column.id)).map((column) => ({
                  id: column.id,
                  label: column.label,
                  align: "right" as const,
                })),
              ].map((column) => (
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
            {SEGMENT_NAMES.map((section) => (
              <SectionGroup key={section} label={section} names={segmentIndices(section)} ticks={ticks} columns={columns} />
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
