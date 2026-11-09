import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import {
  columnVisibilityFeature,
  createColumnHelper,
  rowSortingFeature,
  tableFeatures,
  useTable,
  type SortingState,
  type ColumnVisibilityState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { fetchResults, ResultsError, type Row, type SortOrder } from "../api/results";
import { formatInr, formatPercentWithArrow } from "../lib/format";
import {
  hasActiveFilters,
  readFilterValues,
  writeFilterValues,
  type FilterState,
} from "../filters/filterState";
import { LIVE_SYMBOL_LIMIT, useLiveTicks, type LiveTick } from "../live/useLiveTicks";
import { StateView } from "../shell/StateView";
import { ColumnFilter, type ColumnFilterKind } from "./ColumnFilter";
import { ColumnChooser } from "./ColumnChooser";
import { ColumnResizeHandle, useColumnWidths } from "./columnWidths";
import { Sparkline } from "./Sparkline";
import { fetchRecentCloses } from "./recentCloses";
import { usePrefersReducedMotion } from "./reducedMotion";

export interface ScreenerTableProps {
  runId: string;
  /** Opens the stock tab. Called from the symbol or company cell (click, Enter or Space). */
  onOpenStock?: (symbol: string, company: string | null) => void;
  /** Filters sent with every results request. Pass a stable object; a new object refetches. */
  filters?: FilterState;
  /** Clears the filters. Offered from the no-results state. */
  onClearFilters?: () => void;
  /** Streams live last-traded prices into the LTP column. Off outside market hours. */
  live?: boolean;
  /**
   * Called when a header filter or the Bucket select changes. Omit it to hide the filter controls.
   * It receives the full next filter state.
   */
  onFiltersChange?: (next: FilterState) => void;
  /** Bucket values offered by the server. */
  bucketOptions?: readonly string[];
  /** Stance values offered by the server. */
  stanceOptions?: readonly string[];
}

const NO_OPTIONS: readonly string[] = [];

interface ColumnFilterSpec {
  label: string;
  kind: ColumnFilterKind;
  align: "left" | "right";
  keys: readonly (keyof FilterState)[];
  numeric: boolean;
  options?: readonly string[];
}

/** Header filters. Columns without an entry have no funnel. Company is covered by the Symbol filter. */
function columnFilterSpecs(stanceOptions: readonly string[]): Partial<Record<ColumnId, ColumnFilterSpec>> {
  return {
    symbol: { label: "Symbol or company", kind: "text", align: "left", keys: ["search"], numeric: false },
    industry: { label: "Sector", kind: "text", align: "left", keys: ["industry"], numeric: false },
    ltp: { label: "LTP", kind: "range", align: "right", keys: ["ltpMin", "ltpMax"], numeric: true },
    distance_pct: {
      label: "From ATH (%)",
      kind: "range",
      align: "right",
      keys: ["distanceMin", "distanceMax"],
      numeric: true,
    },
    ath_date: { label: "ATH date", kind: "dates", align: "right", keys: ["athFrom", "athTo"], numeric: false },
    stance: { label: "Stance", kind: "select", align: "left", keys: ["stance"], numeric: false, options: stanceOptions },
  };
}

const NO_FILTERS: FilterState = {};
const NO_TICKS: ReadonlyMap<string, LiveTick> = new Map();
/**
 * Live ticks for the table body. The LTP cell reads them from here, not from the column
 * definitions, so the columns stay the same object on every tick.
 */
const LiveTicksContext = createContext<ReadonlyMap<string, LiveTick>>(NO_TICKS);
const NO_CLOSES: ReadonlyMap<string, readonly number[]> = new Map();
/** Recent closes per symbol for the sparkline column. Read here, like the live ticks, so columns stay stable. */
const ClosesContext = createContext<ReadonlyMap<string, readonly number[]>>(NO_CLOSES);
const PAGE_SIZE = 50;
const ROW_HEIGHT_ESTIMATE = 40;
const FLASH_MS = 700;

/** Column ids double as the server sort keys. "industry" is not in the API sort whitelist. */
const COLUMN_IDS = [
  "symbol",
  "company",
  "ltp",
  "day_chg_abs",
  "day_chg",
  "one_year_return_pct",
  "distance_pct",
  "ath_date",
  "sparkline",
  "industry",
  "stance",
] as const;
type ColumnId = (typeof COLUMN_IDS)[number];

const COLUMN_LABELS: Record<ColumnId, string> = {
  symbol: "Symbol",
  company: "Company",
  ltp: "LTP",
  one_year_return_pct: "1Y return",
  distance_pct: "From ATH",
  ath_date: "ATH date",
  sparkline: "Trend",
  industry: "Sector",
  stance: "Stance",
  day_chg: "Chg %",
  day_chg_abs: "Chg",
};

const NUMERIC_COLUMNS: ReadonlySet<ColumnId> = new Set<ColumnId>([
  "ltp",
  "one_year_return_pct",
  "distance_pct",
  "day_chg",
  "day_chg_abs",
]);

/**
 * Columns the API can sort on. "industry" is not in the sort whitelist; the day change columns are
 * computed client-side; the sparkline is not sortable.
 */
const SERVER_SORTABLE: ReadonlySet<ColumnId> = new Set<ColumnId>(
  COLUMN_IDS.filter(
    (id) => id !== "industry" && id !== "day_chg" && id !== "day_chg_abs" && id !== "sparkline",
  ),
);

const features = tableFeatures({ rowSortingFeature, columnVisibilityFeature });
const helper = createColumnHelper<typeof features, Row>();

const EMPTY_TEXT = "—";

function textOrDash(value: string | null): string {
  return value ?? EMPTY_TEXT;
}

/** Gain, loss and flat colour. The sign and arrow in the text carry the meaning too. */
function trendClass(value: number | null): string {
  if (value === null || Math.round(value * 100) === 0) {
    return "text-neutral";
  }
  return value > 0 ? "text-gain" : "text-loss";
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error.";
}

interface OpenStockCellProps {
  text: string;
  onOpen?: () => void;
  className: string;
}

/**
 * Chevron on a sortable header. It is always shown, dimmed when the column is not sorted. An
 * ascending sort turns it up and a descending sort points it down.
 */
function SortChevron({ direction }: { direction: "asc" | "desc" | null }) {
  const turn = direction === "asc" ? "rotate-180" : "";
  const tone = direction ? "text-accent" : "text-text-muted opacity-60";
  return (
    <svg
      viewBox="0 0 24 24"
      width="12"
      height="12"
      aria-hidden="true"
      focusable="false"
      className={`shrink-0 transition-transform ${turn} ${tone}`}
    >
      <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** A cell that opens the stock tab on click, Enter or Space. */
function OpenStockCell({ text, onOpen, className }: OpenStockCellProps) {
  const onKeyDown = (event: KeyboardEvent<HTMLSpanElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen?.();
    }
  };

  return (
    <span
      role="button"
      tabIndex={0}
      onClick={() => onOpen?.()}
      onKeyDown={onKeyDown}
      className={`cursor-pointer text-accent hover:underline ${className}`}
    >
      {text}
    </span>
  );
}

/**
 * LTP cell. A changed price gets a short gain or loss tint for about 700 ms. The tint is a colour
 * change with no animation, so it stays on under reduced motion. Tabular numerals keep the width fixed.
 */
/**
 * LTP cell. A changed price gets a short gain or loss tint for about 700 ms. Under
 * prefers-reduced-motion the tint is replaced by a static 2px bar on the left edge, shown for the
 * same time. The bar is absolutely positioned, so the cell does not move. Tabular numerals keep
 * the width fixed.
 */
function LtpCell({ symbol, fallback }: { symbol: string; fallback: number | null }) {
  const ticks = useContext(LiveTicksContext);
  const value = ticks.get(symbol)?.ltp ?? fallback;
  const previous = useRef(value);
  const [direction, setDirection] = useState<"up" | "down" | null>(null);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    const before = previous.current;
    previous.current = value;
    if (value === null || before === null || value === before) {
      return;
    }
    setDirection(value > before ? "up" : "down");
    const timer = setTimeout(() => setDirection(null), FLASH_MS);
    return () => clearTimeout(timer);
  }, [value]);

  const tint =
    reducedMotion || direction === null
      ? ""
      : direction === "up"
        ? "bg-gain/15"
        : "bg-loss/15";
  return (
    <span
      data-flash={direction ?? undefined}
      data-motion={reducedMotion ? "reduced" : undefined}
      className={`relative tabular-nums rounded-sm px-1 transition-colors motion-reduce:transition-none ${tint}`}
    >
      {reducedMotion && direction ? (
        <span
          aria-hidden="true"
          data-change-bar={direction}
          className={`absolute inset-y-0 left-0 w-[2px] rounded-l-sm ${direction === "up" ? "bg-gain" : "bg-loss"}`}
        />
      ) : null}
      {formatInr(value)}
    </span>
  );
}

/** Sparkline cell. Reads the closes for its symbol from the context. Shows a dash until they arrive. */
function SparklineCell({ symbol }: { symbol: string }) {
  const closes = useContext(ClosesContext);
  return <Sparkline closes={closes.get(symbol)} />;
}

/**
 * Day change from the live feed: last traded price against the previous close the feed sends
 * with each tick. Shows a dash when the table is not streaming or the tick has no previous close.
 */
function DayChgCell({ symbol, mode }: { symbol: string; mode: "points" | "percent" }) {
  const ticks = useContext(LiveTicksContext);
  const tick = ticks.get(symbol);
  if (!tick || tick.cp === null || tick.cp <= 0) {
    return <span className="tabular-nums text-text-muted">{EMPTY_TEXT}</span>;
  }
  const points = tick.ltp - tick.cp;
  if (mode === "percent") {
    const pct = (points / tick.cp) * 100;
    return <span className={`tabular-nums ${trendClass(pct)}`}>{formatPercentWithArrow(pct)}</span>;
  }
  if (points === 0) {
    return <span className="tabular-nums text-text-muted">0.00</span>;
  }
  const arrow = points > 0 ? "▲ " : "▼ ";
  return (
    <span className={`tabular-nums ${trendClass(points)}`}>
      {arrow}
      {SIGNED_INR.format(points)}
    </span>
  );
}

const SIGNED_INR = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "always",
});

/**
 * Column definitions. FlexRender renders each cell function as a component, so a new column
 * array remounts every cell. Keep this independent of the live ticks (see LiveTicksContext).
 */
function buildColumns(
  onOpenStock: ((symbol: string, company: string | null) => void) | undefined,
) {
  return helper.columns([
    helper.accessor("symbol", {
      id: "symbol",
      header: COLUMN_LABELS.symbol,
      sortDescFirst: false,
      cell: (info) => (
        <OpenStockCell
          text={info.getValue()}
          onOpen={() => onOpenStock?.(info.getValue(), info.row.original.company)}
          className="font-mono font-semibold"
        />
      ),
    }),
    helper.accessor("company", {
      id: "company",
      header: COLUMN_LABELS.company,
      sortDescFirst: false,
      cell: (info) => {
        const company = info.getValue();
        if (company === null) {
          return EMPTY_TEXT;
        }
        return (
          <OpenStockCell
            text={company}
            onOpen={() => onOpenStock?.(info.row.original.symbol, company)}
            className=""
          />
        );
      },
    }),
    helper.accessor("ltp", {
      id: "ltp",
      header: COLUMN_LABELS.ltp,
      sortDescFirst: false,
      cell: (info) => <LtpCell symbol={info.row.original.symbol} fallback={info.getValue()} />,
    }),
    helper.accessor("symbol", {
      id: "day_chg_abs",
      header: COLUMN_LABELS.day_chg_abs,
      enableSorting: false,
      cell: (info) => <DayChgCell symbol={info.row.original.symbol} mode="points" />,
    }),
    helper.accessor("symbol", {
      id: "day_chg",
      header: COLUMN_LABELS.day_chg,
      enableSorting: false,
      cell: (info) => <DayChgCell symbol={info.row.original.symbol} mode="percent" />,
    }),
    helper.accessor("one_year_return_pct", {
      id: "one_year_return_pct",
      header: COLUMN_LABELS.one_year_return_pct,
      sortDescFirst: false,
      cell: (info) => (
        <span className={`tabular-nums ${trendClass(info.getValue())}`}>
          {formatPercentWithArrow(info.getValue())}
        </span>
      ),
    }),
    helper.accessor("distance_pct", {
      id: "distance_pct",
      header: COLUMN_LABELS.distance_pct,
      sortDescFirst: false,
      cell: (info) => (
        <span className={`tabular-nums ${trendClass(info.getValue())}`}>
          {formatPercentWithArrow(info.getValue())}
        </span>
      ),
    }),
    helper.accessor("ath_date", {
      id: "ath_date",
      header: COLUMN_LABELS.ath_date,
      sortDescFirst: false,
      cell: (info) => textOrDash(info.getValue()),
    }),
    helper.accessor("symbol", {
      id: "sparkline",
      header: COLUMN_LABELS.sparkline,
      enableSorting: false,
      cell: (info) => <SparklineCell symbol={info.getValue()} />,
    }),
    helper.accessor("industry", {
      id: "industry",
      header: COLUMN_LABELS.industry,
      enableSorting: false,
      cell: (info) => textOrDash(info.getValue()),
    }),
    helper.accessor("stance", {
      id: "stance",
      header: COLUMN_LABELS.stance,
      sortDescFirst: false,
      cell: (info) => textOrDash(info.getValue()),
    }),
  ]);
}

interface ViewState {
  status: "loading" | "ready" | "error";
  rows: Row[];
  total: number;
  page: number;
  error: string | null;
  loadingMore: boolean;
  moreError: string | null;
}

const INITIAL_VIEW: ViewState = {
  status: "loading",
  rows: [],
  total: 0,
  page: 1,
  error: null,
  loadingMore: false,
  moreError: null,
};

export function ScreenerTable({
  runId,
  onOpenStock,
  filters = NO_FILTERS,
  onClearFilters,
  live = false,
  onFiltersChange,
  bucketOptions = NO_OPTIONS,
  stanceOptions = NO_OPTIONS,
}: ScreenerTableProps) {
  const filterSpecs = useMemo(() => columnFilterSpecs(stanceOptions), [stanceOptions]);
  const columnWidths = useColumnWidths();
  const hasManualWidths = Object.keys(columnWidths.widths).length > 0;
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnVisibility, setColumnVisibility] = useState<ColumnVisibilityState>({});
  const [view, setView] = useState<ViewState>(INITIAL_VIEW);
  // Bumped by the Retry action so the same results request runs again.
  const [retryNonce, setRetryNonce] = useState(0);
  // Bumped on every reset so a stale "load more" response is discarded.
  const generation = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Streams the first LIVE_SYMBOL_LIMIT loaded rows. The symbol list only changes on a new
  // sort, filter or run, so the stream is not reopened on every "load more".
  const liveSymbols = useMemo(
    () => view.rows.slice(0, LIVE_SYMBOL_LIMIT).map((row) => row.symbol),
    [view.rows],
  );
  const liveState = useLiveTicks({ runId, symbols: liveSymbols, enabled: live });
  const liveTicks = live ? liveState.ticks : NO_TICKS;

  const activeSort = sorting[0];
  const sortId = activeSort?.id;
  const sortOrder: SortOrder = activeSort?.desc ? "desc" : "asc";

  useEffect(() => {
    if (!runId) {
      return;
    }
    const controller = new AbortController();
    generation.current += 1;
    setView((current) => ({ ...current, status: "loading", error: null, moreError: null }));

    fetchResults(
      runId,
      { ...filters, page: 1, perPage: PAGE_SIZE, sort: sortId, order: sortId ? sortOrder : undefined },
      { signal: controller.signal },
    )
      .then((page) => {
        setView({
          status: "ready",
          rows: page.results,
          total: page.total,
          page: page.page,
          error: null,
          loadingMore: false,
          moreError: null,
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setView((current) => ({
          ...current,
          status: "error",
          error: error instanceof ResultsError ? error.message : messageOf(error),
        }));
      });

    return () => controller.abort();
  }, [runId, sortId, sortOrder, filters, retryNonce]);

  // Closes for the sparklines. Each symbol is requested once. Symbols with no candles stay out of
  // the map and show the dash. A failed request frees its symbols, so the next rows change retries.
  const [closes, setCloses] = useState<ReadonlyMap<string, readonly number[]>>(NO_CLOSES);
  const requestedCloses = useRef<Set<string>>(new Set());
  useEffect(() => {
    const wanted = view.rows.map((row) => row.symbol).filter((symbol) => !requestedCloses.current.has(symbol));
    if (wanted.length === 0) {
      return;
    }
    wanted.forEach((symbol) => requestedCloses.current.add(symbol));
    fetchRecentCloses(wanted)
      .then((found) => {
        setCloses((current) => {
          const next = new Map(current);
          for (const [symbol, values] of Object.entries(found)) {
            next.set(symbol, values);
          }
          return next;
        });
      })
      .catch(() => {
        wanted.forEach((symbol) => requestedCloses.current.delete(symbol));
      });
  }, [view.rows]);

  const columns = useMemo(() => buildColumns(onOpenStock), [onOpenStock]);

  const table = useTable({
    features,
    columns,
    data: view.rows,
    state: { sorting, columnVisibility },
    onSortingChange: setSorting,
    onColumnVisibilityChange: setColumnVisibility,
    manualSorting: true,
    enableSortingRemoval: false,
  });

  const { rows: tableRows } = table.getRowModel();
  const virtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT_ESTIMATE,
    overscan: 8,
  });

  if (!runId) {
    return <StateView kind="idle" message="No run selected." />;
  }

  if (view.rows.length === 0) {
    if (view.status === "loading") {
      return <StateView kind="loading" message="Loading results…" />;
    }
    if (view.status === "error") {
      return (
        <StateView
          kind="error"
          message={`Could not load results. ${view.error ?? ""}`.trim()}
          action={{ label: "Retry", onClick: () => setRetryNonce((count) => count + 1) }}
        />
      );
    }
    if (hasActiveFilters(filters)) {
      return (
        <StateView
          kind="empty"
          message="No results match these filters."
          action={onClearFilters ? { label: "Clear filters", onClick: onClearFilters } : undefined}
        />
      );
    }
    return <StateView kind="empty" message="No results for this run." />;
  }

  const loadMore = async () => {
    const gen = generation.current;
    setView((current) => ({ ...current, loadingMore: true, moreError: null }));
    try {
      const next = await fetchResults(runId, {
        ...filters,
        page: view.page + 1,
        perPage: PAGE_SIZE,
        sort: sortId,
        order: sortId ? sortOrder : undefined,
      });
      if (gen !== generation.current) {
        return;
      }
      setView((current) => ({
        ...current,
        rows: [...current.rows, ...next.results],
        total: next.total,
        page: next.page,
        loadingMore: false,
      }));
    } catch (error: unknown) {
      if (gen !== generation.current) {
        return;
      }
      setView((current) => ({ ...current, loadingMore: false, moreError: messageOf(error) }));
    }
  };

  /**
   * Enter or Space on a focused row opens its stock, the same as the symbol control. Keys pressed on
   * a control inside the row are left to that control, so the stock opens once.
   */
  const openRowFromKey = (event: KeyboardEvent<HTMLTableRowElement>, row: Row) => {
    if (event.target !== event.currentTarget) {
      return;
    }
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    onOpenStock?.(row.symbol, row.company);
  };

  const visibleColumnCount = table.getVisibleLeafColumns().length;
  const virtualRows = virtualizer.getVirtualItems();
  const paddingTop = virtualRows.length > 0 ? virtualRows[0].start : 0;
  const paddingBottom =
    virtualRows.length > 0 ? virtualizer.getTotalSize() - virtualRows[virtualRows.length - 1].end : 0;
  const remaining = view.total - view.rows.length;

  return (
    <section aria-label="Scan results" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="text-sm text-text-muted" aria-live="polite">
          Showing {view.rows.length} of {view.total}
          {view.status === "loading" ? " · Updating…" : ""}
          {live && liveState.status === "live" ? " · Live prices" : ""}
          {live && liveState.status === "unavailable" ? " · Live prices unavailable" : ""}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          {onFiltersChange ? (
          <label className="inline-flex items-center gap-2 text-sm text-text-muted">
            Bucket
            <select
              value={filters.bucket ?? ""}
              onChange={(event) =>
                onFiltersChange(writeFilterValues(filters, ["bucket"], [event.target.value], false))
              }
              className="rounded-(--radius-control) border border-border-ui bg-surface px-2 py-1 text-sm text-text"
            >
              <option value="">All</option>
              {bucketOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          ) : null}
          <ColumnChooser
            columns={table.getAllLeafColumns().map((column) => ({
              id: column.id,
              label: COLUMN_LABELS[column.id as ColumnId],
              visible: column.getIsVisible(),
              onToggle: column.getToggleVisibilityHandler(),
            }))}
          />
        </div>
      </div>
      {live && liveState.status === "reconnecting" ? (
        <StateView kind="reconnecting" message="Live prices reconnecting. Showing the last saved prices." />
      ) : null}
      {view.status === "error" ? (
        <p role="alert" className="text-sm text-loss">
          <span aria-hidden="true">⚠ </span>
          Could not update results. {view.error}
        </p>
      ) : null}

      <LiveTicksContext.Provider value={liveTicks}>
        <ClosesContext.Provider value={closes}>
          <div
            ref={scrollRef}
            className="max-h-[60vh] overflow-auto rounded-md border border-border bg-surface"
          >
            <table
              className={`border-collapse text-sm text-text whitespace-nowrap ${hasManualWidths ? "table-fixed w-full" : "table-auto w-max"}`}
            >
              <thead>
                {table.getHeaderGroups().map((group) => (
                  <tr key={group.id}>
                    {group.headers.map((header) => {
                      const id = header.column.id as ColumnId;
                      const sorted = header.column.getIsSorted();
                      const ariaSort = sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none";
                      const align = NUMERIC_COLUMNS.has(id) ? "text-right" : "text-left";
                      const stick = id === "symbol" ? "left-0 z-30" : "z-20";
                      const spec = onFiltersChange ? filterSpecs[id] : undefined;
                      const currentValues = spec ? readFilterValues(filters, spec.keys) : [];
                      return (
                        <th
                          key={header.id}
                          data-col={id}
                          scope="col"
                          aria-sort={header.column.getCanSort() ? ariaSort : undefined}
                          style={columnWidths.widths[id] !== undefined ? { width: columnWidths.widths[id] } : undefined}
                          className={`sticky top-0 relative whitespace-nowrap bg-surface px-3 py-2 font-semibold ${align} ${stick}`}
                        >
                          {header.column.getCanSort() && SERVER_SORTABLE.has(id) ? (
                            <button
                              type="button"
                              onClick={header.column.getToggleSortingHandler()}
                              className="inline-flex items-center gap-1 font-semibold text-text"
                            >
                              <span className="min-w-0 truncate">{COLUMN_LABELS[id]}</span>
                              <SortChevron
                                direction={sorted === "asc" || sorted === "desc" ? sorted : null}
                              />
                            </button>
                          ) : (
                            <span className="block min-w-0 truncate">{COLUMN_LABELS[id]}</span>
                          )}
                          {spec && onFiltersChange ? (
                            <ColumnFilter
                              label={spec.label}
                              kind={spec.kind}
                              align={spec.align}
                              options={spec.options}
                              value={[currentValues[0] ?? "", currentValues[1] ?? ""]}
                              active={currentValues.some((value) => value !== "")}
                              onApply={(next) =>
                                onFiltersChange(writeFilterValues(filters, spec.keys, next, spec.numeric))
                              }
                            />
                          ) : null}
                          <ColumnResizeHandle
                            label={COLUMN_LABELS[id]}
                            onStart={(event) => columnWidths.startResize(event, id)}
                            onReset={columnWidths.reset}
                          />
                        </th>
                      );
                    })}
                  </tr>
                ))}
              </thead>
              <tbody>
                {paddingTop > 0 ? (
                  <tr aria-hidden="true">
                    <td colSpan={visibleColumnCount} style={{ height: paddingTop, padding: 0 }} />
                  </tr>
                ) : null}
                {virtualRows.map((virtualRow) => {
                  const row = tableRows[virtualRow.index];
                  return (
                    <tr
                      key={row.id}
                      data-index={virtualRow.index}
                      ref={virtualizer.measureElement}
                      tabIndex={0}
                      onKeyDown={(event) => openRowFromKey(event, row.original)}
                      className="border-t border-border focus-visible:-outline-offset-2 focus-visible:outline-2 focus-visible:outline-focus"
                    >
                      {row.getVisibleCells().map((cell) => {
                        const id = cell.column.id as ColumnId;
                        const align = NUMERIC_COLUMNS.has(id) ? "text-right" : "text-left";
                        const stick = id === "symbol" ? "sticky left-0 z-10 bg-surface" : "";
                        return (
                          <td key={cell.id} className={`overflow-hidden text-ellipsis px-3 py-2 ${align} ${stick}`}>
                            <table.FlexRender cell={cell} />
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
                {paddingBottom > 0 ? (
                  <tr aria-hidden="true">
                    <td colSpan={visibleColumnCount} style={{ height: paddingBottom, padding: 0 }} />
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </ClosesContext.Provider>
      </LiveTicksContext.Provider>

      {remaining > 0 ? (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={loadMore}
            disabled={view.loadingMore}
            className="rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text disabled:opacity-60"
          >
            Load more ({remaining} remaining)
          </button>
          {view.moreError ? (
            <span role="alert" className="text-sm text-loss">
              {view.moreError}
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
