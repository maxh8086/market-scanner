import { useEffect, useMemo, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { fetchSectorSummary, SectorSummaryError, type SectorPeriod, type SectorSummaryRow } from "../api/sectorSummary";
import { formatPercentWithArrow } from "../lib/format";
import { ColumnResizeHandle, useColumnWidths } from "../table/columnWidths";
import { StateView } from "../shell/StateView";
import {
  advDecRatio,
  breadthShares,
  sortSectors,
  stockCountLabel,
  toneOf,
  topAndBottom,
  type SortKey,
  type SortState,
  type Tone,
} from "./sectorView";

export interface SectorHeatmapProps {
  runId: string;
}

const PERIOD_OPTIONS: { value: SectorPeriod; label: string }[] = [
  { value: "1d", label: "1D" },
  { value: "1w", label: "1W" },
  { value: "1m", label: "1M" },
  { value: "3m", label: "3M" },
  { value: "6m", label: "6M" },
  { value: "12m", label: "12M" },
];

const EMPTY_MESSAGE = "No sector data for this period";
const SUMMARY_COUNT = 3;
const DEFAULT_SORT: SortState = { key: "avgChangePct", dir: "desc" };

type SectorState =
  | { status: "loading" }
  | { status: "ready"; sectors: SectorSummaryRow[] }
  | { status: "error"; message: string };

const TONE_CLASSES: Record<Tone, { box: string; text: string }> = {
  strong_gain: { box: "border-gain/60 bg-gain/35", text: "text-gain" },
  light_gain: { box: "border-gain/40 bg-gain/15", text: "text-gain" },
  flat: { box: "border-neutral/40 bg-neutral/10", text: "text-neutral" },
  light_loss: { box: "border-loss/40 bg-loss/15", text: "text-loss" },
  strong_loss: { box: "border-loss/60 bg-loss/35", text: "text-loss" },
};

const SWATCH_CLASSES: Record<Tone, string> = {
  strong_gain: "bg-gain/35",
  light_gain: "bg-gain/15",
  flat: "bg-neutral/10",
  light_loss: "bg-loss/15",
  strong_loss: "bg-loss/35",
};

const LEGEND: { tone: Tone; label: string }[] = [
  { tone: "strong_loss", label: "≤ −1%" },
  { tone: "light_loss", label: "−1% to 0" },
  { tone: "flat", label: "flat" },
  { tone: "light_gain", label: "0 to +1%" },
  { tone: "strong_gain", label: "≥ +1%" },
];

function messageOf(error: unknown): string {
  if (error instanceof SectorSummaryError) {
    return error.message;
  }
  return error instanceof Error ? error.message : "Could not load sector data.";
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

function formatRatio(row: SectorSummaryRow): string {
  const ratio = advDecRatio(row);
  if (ratio === 0 && row.advancers === 0 && row.decliners === 0) {
    return "—";
  }
  if (!Number.isFinite(ratio)) {
    return "No declines";
  }
  return ratio.toFixed(2);
}

/** Split bar: advancing share in green, declining share in red. The rest of the bar is unchanged stocks. */
function BreadthBar({ row }: { row: SectorSummaryRow }) {
  const { up, down } = breadthShares(row);
  return (
    <div
      role="img"
      aria-label={`${row.advancers} up, ${row.decliners} down of ${row.count}`}
      className="flex h-1.5 w-full overflow-hidden rounded-full bg-border"
    >
      <span className="h-full bg-gain" style={{ width: `${up}%` }} />
      <span className="h-full bg-loss" style={{ width: `${down}%` }} />
    </div>
  );
}

function SummaryList({ title, rows }: { title: string; rows: SectorSummaryRow[] }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">{title}</p>
      <ul className="flex flex-col gap-1">
        {rows.map((row) => (
          <li key={row.sector} className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 text-text">{row.sector}</span>
            <span className={`tabular-nums font-semibold whitespace-nowrap ${TONE_CLASSES[toneOf(row.avgChangePct)].text}`}>
              {formatPercentWithArrow(row.avgChangePct)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Column resize wiring for one header cell. Omit it for a fixed-width table. */
interface HeaderResize {
  width?: number;
  onStart: (event: ReactPointerEvent<HTMLElement>) => void;
  onReset: () => void;
}

interface SortableHeaderProps {
  label: string;
  /** Omit for a column that does not sort; it renders as a plain label. */
  sortKey?: SortKey;
  sort: SortState;
  onSort: (key: SortKey) => void;
  align?: "left" | "right";
  resize?: HeaderResize;
}

function SortableHeader({ label, sortKey, sort, onSort, align = "right", resize }: SortableHeaderProps) {
  const active = sortKey !== undefined && sort.key === sortKey;
  const ariaSort = active ? (sort.dir === "asc" ? "ascending" : "descending") : "none";
  const arrow = active ? (sort.dir === "asc" ? " ▲" : " ▼") : "";
  return (
    <th
      scope="col"
      data-col={label}
      aria-sort={sortKey !== undefined ? ariaSort : undefined}
      style={resize?.width !== undefined ? { width: resize.width } : undefined}
      className={`relative px-2 py-2 font-semibold ${align === "right" ? "text-right" : "text-left"}`}
    >
      {sortKey !== undefined ? (
        <button type="button" onClick={() => onSort(sortKey)} className="block max-w-full truncate hover:text-text">
          {label}
          {arrow}
        </button>
      ) : (
        <span className="block max-w-full truncate">{label}</span>
      )}
      {resize ? <ColumnResizeHandle label={label} onStart={resize.onStart} onReset={resize.onReset} /> : null}
    </th>
  );
}

export function SectorHeatmap({ runId }: SectorHeatmapProps) {
  const [period, setPeriod] = useState<SectorPeriod>("1d");
  const [state, setState] = useState<SectorState>({ status: "loading" });
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const columnWidths = useColumnWidths();
  const hasManualWidths = Object.keys(columnWidths.widths).length > 0;
  const resizeFor = (columnId: string): HeaderResize => ({
    width: columnWidths.widths[columnId],
    onStart: (event) => columnWidths.startResize(event, columnId),
    onReset: columnWidths.reset,
  });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });

    fetchSectorSummary(runId, period, { signal: controller.signal })
      .then((body) => {
        setState({ status: "ready", sectors: body.sectors });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || isAbortError(error)) {
          return;
        }
        setState({ status: "error", message: messageOf(error) });
      });

    return () => controller.abort();
  }, [runId, period]);

  const sectors = state.status === "ready" ? state.sectors : [];
  const extremes = useMemo(() => topAndBottom(sectors, SUMMARY_COUNT), [sectors]);
  const tableRows = useMemo(() => sortSectors(sectors, sort), [sectors, sort]);
  const rankBySector = useMemo(() => {
    const ranked = sortSectors(sectors, DEFAULT_SORT);
    return new Map(ranked.map((row, index) => [row.sector, index + 1]));
  }, [sectors]);

  const onSort = (key: SortKey) => {
    setSort((current) => {
      if (current.key === key) {
        return { key, dir: current.dir === "asc" ? "desc" : "asc" };
      }
      return { key, dir: key === "sector" ? "asc" : "desc" };
    });
  };

  return (
    <section aria-label="Sector heatmap" className="flex flex-col gap-4">
      <div role="group" aria-label="Period" className="flex flex-wrap gap-1">
        {PERIOD_OPTIONS.map((option) => {
          const active = option.value === period;
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={active}
              onClick={() => setPeriod(option.value)}
              className={`rounded-md border px-3 py-1 text-sm ${
                active ? "border-accent font-semibold text-text" : "border-border text-text-muted"
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </div>

      {state.status === "loading" ? <StateView kind="loading" message="Loading sector data." /> : null}
      {state.status === "error" ? <StateView kind="error" message={state.message} /> : null}
      {state.status === "ready" && state.sectors.length === 0 ? (
        <StateView kind="empty" message={EMPTY_MESSAGE} />
      ) : null}

      {state.status === "ready" && state.sectors.length > 0 ? (
        <>
          <div className="flex flex-col gap-4 rounded-md border border-border p-3 sm:flex-row sm:gap-6">
            <SummaryList title="Top sectors" rows={extremes.top} />
            <SummaryList title="Bottom sectors" rows={extremes.bottom} />
          </div>

          <ul aria-label="Sector tiles" className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            {state.sectors.map((row) => {
              const tone = TONE_CLASSES[toneOf(row.avgChangePct)];
              // On wider screens the tile's flex-grow follows its stock count. Below 640px tiles stack in one column.
              const weight = { "--weight": row.count } as CSSProperties;
              return (
                <li
                  key={row.sector}
                  style={weight}
                  className={`flex min-w-0 flex-col gap-1 rounded-md border p-3 sm:[flex:var(--weight)_1_160px] ${tone.box}`}
                >
                  <p className="text-sm font-semibold leading-snug text-text">{row.sector}</p>
                  <p className={`tabular-nums text-lg font-semibold ${tone.text}`}>
                    {formatPercentWithArrow(row.avgChangePct)}
                  </p>
                  <p className="text-xs text-text-muted">
                    {stockCountLabel(row.count)} · {row.advancers} up, {row.decliners} down
                  </p>
                  <BreadthBar row={row} />
                </li>
              );
            })}
          </ul>

          <div aria-label="Colour legend" className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
            {LEGEND.map((entry) => (
              <span key={entry.tone} className="flex items-center gap-1">
                <span className={`inline-block h-3 w-5 rounded-sm border border-border ${SWATCH_CLASSES[entry.tone]}`} />
                {entry.label}
              </span>
            ))}
            <span className="ml-2">Bar: green = advancing share, red = declining share</span>
          </div>

          <div className="overflow-x-auto">
            <table aria-label="Sector performance" className={`w-full border-collapse text-sm whitespace-nowrap ${hasManualWidths ? "table-fixed" : "table-auto"}`}>
              <thead className="border-b border-border text-text-muted">
                <tr>
                  <SortableHeader label="#" sort={sort} onSort={onSort} align="right" resize={resizeFor("#")} />
                  <SortableHeader label="Sector" sortKey="sector" sort={sort} onSort={onSort} align="left" resize={resizeFor("Sector")} />
                  <SortableHeader label="Change" sortKey="avgChangePct" sort={sort} onSort={onSort} resize={resizeFor("Change")} />
                  <SortableHeader label="Stocks" sortKey="count" sort={sort} onSort={onSort} resize={resizeFor("Stocks")} />
                  <SortableHeader label="Adv / Dec" sort={sort} onSort={onSort} resize={resizeFor("Adv / Dec")} />
                  <SortableHeader label="Adv/Dec ratio" sortKey="ratio" sort={sort} onSort={onSort} resize={resizeFor("Adv/Dec ratio")} />
                  <SortableHeader label="Breadth" sort={sort} onSort={onSort} align="left" resize={resizeFor("Breadth")} />
                </tr>
              </thead>
              <tbody>
                {tableRows.map((row) => {
                  const tone = TONE_CLASSES[toneOf(row.avgChangePct)];
                  return (
                    <tr key={row.sector} className="border-b border-border/60">
                      <td className="px-2 py-2 text-right tabular-nums text-text-muted">{rankBySector.get(row.sector)}</td>
                      <td className="px-2 py-2 text-left font-medium text-text">{row.sector}</td>
                      <td className={`px-2 py-2 text-right tabular-nums font-semibold ${tone.text}`}>
                        {formatPercentWithArrow(row.avgChangePct)}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">{row.count}</td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        <span className="text-gain">{row.advancers}</span>
                        <span className="text-text-muted"> / </span>
                        <span className="text-loss">{row.decliners}</span>
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">{formatRatio(row)}</td>
                      <td className="w-40 px-2 py-2">
                        <BreadthBar row={row} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}
