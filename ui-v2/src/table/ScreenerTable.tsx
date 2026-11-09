import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
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
import { StateView } from "../shell/StateView";

export interface ScreenerTableProps {
  runId: string;
  /** Opens the stock tab. Called from the symbol or company cell (click, Enter or Space). */
  onOpenStock?: (symbol: string, company: string | null) => void;
  /** Filters sent with every results request. Pass a stable object; a new object refetches. */
  filters?: FilterState;
  /** Clears the filters. Offered from the no-results state. */
  onClearFilters?: () => void;
}

const NO_FILTERS: FilterState = {};
const PAGE_SIZE = 50;
const ROW_HEIGHT_ESTIMATE = 40;

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

function buildColumns(onOpenStock?: (symbol: string, company: string | null) => void) {
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
      cell: (info) => <span className="tabular-nums">{formatInr(info.getValue())}</span>,
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

export function ScreenerTable({ runId, onOpenStock, filters = NO_FILTERS, onClearFilters }: ScreenerTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnVisibility, setColumnVisibility] = useState<ColumnVisibilityState>({});
  const [view, setView] = useState<ViewState>(INITIAL_VIEW);
  // Bumped on every reset so a stale "load more" response is discarded.
  const generation = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

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
  }, [runId, sortId, sortOrder, filters]);

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
      return <StateView kind="error" message={`Could not load results. ${view.error ?? ""}`.trim()} />;
    }
    if (hasActiveFilters(filters)) {
      return (
        <div className="space-y-3">
          <StateView kind="empty" message="No results match these filters." />
          {onClearFilters ? (
            <button
              type="button"
              onClick={onClearFilters}
              className="rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text"
            >
              Clear filters
            </button>
          ) : null}
        </div>
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
      </p>
      {view.status === "error" ? (
        <p role="alert" className="text-sm text-loss">
          Could not update results. {view.error}
        </p>
      ) : null}

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
