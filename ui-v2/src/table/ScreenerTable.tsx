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
import { hasActiveFilters, type FilterState } from "../filters/filterState";
import { LIVE_SYMBOL_LIMIT, useLiveTicks, type LiveTick } from "../live/useLiveTicks";
import { StateView } from "../shell/StateView";

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
}

const NO_FILTERS: FilterState = {};
const NO_TICKS: ReadonlyMap<string, LiveTick> = new Map();
/**
 * Live ticks for the table body. The LTP cell reads them from here, not from the column
 * definitions, so the columns stay the same object on every tick.
 */
const LiveTicksContext = createContext<ReadonlyMap<string, LiveTick>>(NO_TICKS);
const PAGE_SIZE = 50;
const ROW_HEIGHT_ESTIMATE = 40;
const FLASH_MS = 700;

/** Column ids double as the server sort keys. "industry" is not in the API sort whitelist. */
const COLUMN_IDS = [
  "symbol",
  "company",
  "ltp",
  "one_year_return_pct",
  "distance_pct",
  "ath_date",
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
  industry: "Sector",
  stance: "Stance",
};

const NUMERIC_COLUMNS: ReadonlySet<ColumnId> = new Set<ColumnId>([
  "ltp",
  "one_year_return_pct",
  "distance_pct",
]);

const SERVER_SORTABLE: ReadonlySet<ColumnId> = new Set<ColumnId>(
  COLUMN_IDS.filter((id) => id !== "industry"),
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
function LtpCell({ symbol, fallback }: { symbol: string; fallback: number | null }) {
  const ticks = useContext(LiveTicksContext);
  const value = ticks.get(symbol)?.ltp ?? fallback;
  const previous = useRef(value);
  const [direction, setDirection] = useState<"up" | "down" | null>(null);

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

  const tint = direction === "up" ? "bg-gain/15" : direction === "down" ? "bg-loss/15" : "";
  return (
    <span
      data-flash={direction ?? undefined}
      className={`tabular-nums rounded-sm px-1 transition-colors motion-reduce:transition-none ${tint}`}
    >
      {formatInr(value)}
    </span>
  );
}

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
}: ScreenerTableProps) {
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

  const visibleColumnCount = table.getVisibleLeafColumns().length;
  const virtualRows = virtualizer.getVirtualItems();
  const paddingTop = virtualRows.length > 0 ? virtualRows[0].start : 0;
  const paddingBottom =
    virtualRows.length > 0 ? virtualizer.getTotalSize() - virtualRows[virtualRows.length - 1].end : 0;
  const remaining = view.total - view.rows.length;

  return (
    <section aria-label="Scan results" className="space-y-3">
      <fieldset className="text-sm text-text">
        <legend className="mb-2 text-text-muted">Show columns</legend>
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {table.getAllLeafColumns().map((column) => (
            <label key={column.id} className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={column.getIsVisible()}
                onChange={column.getToggleVisibilityHandler()}
                className="size-4 accent-accent"
              />
              {COLUMN_LABELS[column.id as ColumnId]}
            </label>
          ))}
        </div>
      </fieldset>

      <p className="text-sm text-text-muted" aria-live="polite">
        Showing {view.rows.length} of {view.total}
        {view.status === "loading" ? " · Updating…" : ""}
        {live && liveState.status === "live" ? " · Live prices" : ""}
        {live && liveState.status === "unavailable" ? " · Live prices unavailable" : ""}
      </p>
      {live && liveState.status === "reconnecting" ? (
        <StateView kind="reconnecting" message="Live prices reconnecting. Showing the last saved prices." />
      ) : null}
      {view.status === "error" ? (
        <p role="alert" className="text-sm text-loss">
          Could not update results. {view.error}
        </p>
      ) : null}

      <LiveTicksContext.Provider value={liveTicks}>
        <div
          ref={scrollRef}
          className="max-h-[60vh] overflow-auto rounded-md border border-border bg-surface"
        >
          <table className="w-full border-collapse text-sm text-text">
            <thead>
              {table.getHeaderGroups().map((group) => (
                <tr key={group.id}>
                  {group.headers.map((header) => {
                    const id = header.column.id as ColumnId;
                    const sorted = header.column.getIsSorted();
                    const ariaSort = sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none";
                    const indicator = sorted === "asc" ? "↑" : sorted === "desc" ? "↓" : "";
                    const align = NUMERIC_COLUMNS.has(id) ? "text-right" : "text-left";
                    const stick = id === "symbol" ? "left-0 z-30" : "z-20";
                    return (
                      <th
                        key={header.id}
                        scope="col"
                        aria-sort={header.column.getCanSort() ? ariaSort : undefined}
                        className={`sticky top-0 whitespace-nowrap bg-surface-2 px-3 py-2 font-semibold ${align} ${stick}`}
                      >
                        {header.column.getCanSort() && SERVER_SORTABLE.has(id) ? (
                          <button
                            type="button"
                            onClick={header.column.getToggleSortingHandler()}
                            className="inline-flex items-center gap-1 font-semibold text-text"
                          >
                            {COLUMN_LABELS[id]}
                            <span aria-hidden="true" className="text-text-muted">
                              {indicator}
                            </span>
                          </button>
                        ) : (
                          COLUMN_LABELS[id]
                        )}
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
                    className="border-t border-border"
                  >
                    {row.getVisibleCells().map((cell) => {
                      const id = cell.column.id as ColumnId;
                      const align = NUMERIC_COLUMNS.has(id) ? "text-right" : "text-left";
                      const stick = id === "symbol" ? "sticky left-0 z-10 bg-surface" : "";
                      return (
                        <td key={cell.id} className={`px-3 py-2 ${align} ${stick}`}>
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
