import { useCallback, useEffect, useState } from "react";
import { fetchFilterOptions, type FilterOptions } from "./api/filterOptions";
import { fetchLatestRun, LatestRunError, type LatestRun } from "./api/latestRun";
import { type FilterState } from "./filters/filterState";
import { PresetsMenu } from "./filters/PresetsMenu";
import { getMarketSession, runAgeDays } from "./lib/marketSession";
import { AppShell } from "./shell/AppShell";
import { StateView, type StateKind } from "./shell/StateView";
import type { TabItem } from "./shell/TabStrip";
import { StockPage } from "./stock/StockPage";
import { SectorHeatmap } from "./sectors/SectorHeatmap";
import { ScreenerTable } from "./table/ScreenerTable";
import { ThemeProvider } from "./theme/ThemeProvider";

const TABS: TabItem[] = [
  { id: "home", label: "Home" },
  { id: "sectors", label: "Sectors" },
];

/** An open stock tab. The id is the symbol, so opening the same stock twice focuses the existing tab. */
interface StockTab {
  id: string;
  label: string;
  company: string | null;
}

const NO_OPTIONS: readonly string[] = [];

type LatestRunState =
  | { status: "loading" }
  | { status: "ready"; run: LatestRun }
  | { status: "empty" }
  | { status: "error"; message: string };

type FilterOptionsState =
  | { status: "loading" }
  | { status: "ready"; options: FilterOptions }
  | { status: "error" };

const CLOCK_REFRESH_MS = 60_000;

interface SessionBanner {
  kind: Extract<StateKind, "market_closed" | "pre_open" | "stale">;
  message: string;
}

/**
 * The one banner above the Home table. Market closed wins. Otherwise stale wins over the
 * pre-open notice, so a stale run is still flagged during pre-open and open hours.
 */
function sessionBanner(runDate: string, now: Date): SessionBanner | null {
  const session = getMarketSession(now);
  if (session.status === "closed") {
    return { kind: "market_closed", message: `Market closed. Last close: ${session.lastCloseLabel}` };
  }
  const age = runAgeDays(runDate, now);
  if (age > 0) {
    return { kind: "stale", message: `Data is ${age} trading day(s) old (run date ${runDate})` };
  }
  if (session.status === "pre_open") {
    return { kind: "pre_open", message: "Pre-open session, 09:00 to 09:15 IST" };
  }
  return null;
}

export default function App() {
  const [activeTabId, setActiveTabId] = useState("home");
  // Only re-renders the clock; the time itself is read on each render below.
  const [, setClockTick] = useState(0);
  const [stockTabs, setStockTabs] = useState<StockTab[]>([]);
  const [latest, setLatest] = useState<LatestRunState>({ status: "loading" });
  // Bumped by the Retry action so the latest-run request runs again.
  const [latestRetryNonce, setLatestRetryNonce] = useState(0);
  const retryLatestRun = () => {
    setLatest({ status: "loading" });
    setLatestRetryNonce((count) => count + 1);
  };
  const [filterOptions, setFilterOptions] = useState<FilterOptionsState>({ status: "loading" });
  const [filters, setFilters] = useState<FilterState>({});
  const clearFilters = () => setFilters({});

  const tabs: TabItem[] = [...TABS, ...stockTabs.map((tab) => ({ id: tab.id, label: tab.label, closable: true }))];
  const activeStock = stockTabs.find((tab) => tab.id === activeTabId) ?? null;

  const openStock = useCallback((symbol: string, company: string | null) => {
    setStockTabs((current) =>
      current.some((tab) => tab.id === symbol) ? current : [...current, { id: symbol, label: symbol, company }],
    );
    setActiveTabId(symbol);
  }, []);

  const closeStock = useCallback((id: string) => {
    setStockTabs((current) => current.filter((tab) => tab.id !== id));
    setActiveTabId((current) => (current === id ? "home" : current));
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setClockTick((tick) => tick + 1), CLOCK_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  const now = new Date();
  const banner = latest.status === "ready" ? sessionBanner(latest.run.runDate, now) : null;
  // Live prices stream only in the open session (09:15 to 15:30 IST) with a run loaded.
  const liveEnabled = latest.status === "ready" && getMarketSession(now).status === "open";

  const readyRunId = latest.status === "ready" ? latest.run.runId : null;

  useEffect(() => {
    if (readyRunId === null) {
      return;
    }
    const controller = new AbortController();
    setFilterOptions({ status: "loading" });

    fetchFilterOptions(readyRunId, { signal: controller.signal })
      .then((options) => {
        setFilterOptions({ status: "ready", options });
      })
      .catch(() => {
        if (controller.signal.aborted) {
          return;
        }
        // Filter options are optional: the table still works with only "All" in the dropdowns.
        setFilterOptions({ status: "error" });
      });

    return () => {
      controller.abort();
    };
  }, [readyRunId]);

  const bucketOptions = filterOptions.status === "ready" ? filterOptions.options.bucket : NO_OPTIONS;
  const stanceOptions = filterOptions.status === "ready" ? filterOptions.options.stance : NO_OPTIONS;

  useEffect(() => {
    const controller = new AbortController();

    fetchLatestRun({ signal: controller.signal })
      .then((run) => {
        setLatest({ status: "ready", run });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        if (error instanceof LatestRunError && error.status === 404) {
          setLatest({ status: "empty" });
          return;
        }
        const message = error instanceof Error ? error.message : "Could not load the current run.";
        setLatest({ status: "error", message });
      });

    return () => {
      controller.abort();
    };
  }, [latestRetryNonce]);

  const retryAction = { label: "Retry", onClick: retryLatestRun };

  return (
    <ThemeProvider>
      <AppShell
        tabs={tabs}
        activeTabId={activeTabId}
        onSelectTab={setActiveTabId}
        onCloseTab={closeStock}
      >
        {activeTabId === "sectors" ? (
          latest.status === "ready" ? (
            <SectorHeatmap runId={latest.run.runId} />
          ) : (
            <>
              {latest.status === "loading" && <StateView kind="loading" message="Loading the current run." />}
              {latest.status === "empty" && <StateView kind="empty" message="No current run." />}
              {latest.status === "error" && <StateView kind="error" message={latest.message} action={retryAction} />}
            </>
          )
        ) : activeStock ? (
          <StockPage key={activeStock.id} symbol={activeStock.id} company={activeStock.company} />
        ) : (
          <>
            {latest.status === "loading" && <StateView kind="loading" message="Loading the current run." />}
            {latest.status === "empty" && <StateView kind="empty" message="No current run." />}
            {latest.status === "error" && <StateView kind="error" message={latest.message} action={retryAction} />}
            {latest.status === "ready" && (
              <div className="flex flex-col gap-3">
                <p className="text-sm text-text-muted">Run date: {latest.run.runDate}</p>
                {banner ? <StateView kind={banner.kind} message={banner.message} /> : null}
                <PresetsMenu filters={filters} onApply={setFilters} />
                <ScreenerTable
                  runId={latest.run.runId}
                  filters={filters}
                  onFiltersChange={setFilters}
                  bucketOptions={bucketOptions}
                  stanceOptions={stanceOptions}
                  onClearFilters={clearFilters}
                  onOpenStock={openStock}
                  live={liveEnabled}
                />
              </div>
            )}
          </>
        )}
      </AppShell>
    </ThemeProvider>
  );
}
