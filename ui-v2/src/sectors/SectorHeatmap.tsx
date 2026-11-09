import { useEffect, useState, type CSSProperties } from "react";
import { fetchSectorSummary, SectorSummaryError, type SectorPeriod, type SectorSummaryRow } from "../api/sectorSummary";
import { formatPercentWithArrow } from "../lib/format";
import { StateView } from "../shell/StateView";

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

type SectorState =
  | { status: "loading" }
  | { status: "ready"; sectors: SectorSummaryRow[] }
  | { status: "error"; message: string };

function messageOf(error: unknown): string {
  if (error instanceof SectorSummaryError) {
    return error.message;
  }
  return error instanceof Error ? error.message : "Could not load sector data.";
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

/** Tile tone from the average change. The sign and arrow in the text carry the meaning too. */
function toneOf(value: number): { box: string; text: string } {
  if (Math.round(value * 100) === 0) {
    return { box: "border-neutral/40 bg-neutral/10", text: "text-neutral" };
  }
  return value > 0
    ? { box: "border-gain/40 bg-gain/15", text: "text-gain" }
    : { box: "border-loss/40 bg-loss/15", text: "text-loss" };
}

export function SectorHeatmap({ runId }: SectorHeatmapProps) {
  const [period, setPeriod] = useState<SectorPeriod>("1d");
  const [state, setState] = useState<SectorState>({ status: "loading" });

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

  return (
    <section aria-label="Sector heatmap" className="flex flex-col gap-3">
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
        <ul aria-label="Sector tiles" className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          {state.sectors.map((row) => {
            const tone = toneOf(row.avgChangePct);
            // On wider screens the tile's flex-grow follows its stock count. Below 640px tiles stack in one column.
            const weight = { "--weight": row.count } as CSSProperties;
            return (
              <li
                key={row.sector}
                style={weight}
                className={`min-w-0 rounded-md border p-3 sm:[flex:var(--weight)_1_160px] ${tone.box}`}
              >
                <p className="truncate text-sm font-semibold text-text">{row.sector}</p>
                <p className={`tabular-nums text-lg font-semibold ${tone.text}`}>
                  {formatPercentWithArrow(row.avgChangePct)}
                </p>
                <p className="text-xs text-text-muted">
                  {row.count} stocks · {row.advancers} up, {row.decliners} down
                </p>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
