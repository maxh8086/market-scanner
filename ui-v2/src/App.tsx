import { useEffect, useState } from "react";
import { fetchFilterOptions, type FilterOptions } from "./api/filterOptions";
import { fetchLatestRun, LatestRunError, type LatestRun } from "./api/latestRun";
import { FilterBar } from "./filters/FilterBar";
import { type FilterState } from "./filters/filterState";
import { PresetsMenu } from "./filters/PresetsMenu";
import { AppShell } from "./shell/AppShell";
import { StateView } from "./shell/StateView";
import type { TabItem } from "./shell/TabStrip";
import { ScreenerTable } from "./table/ScreenerTable";
import { ThemeProvider } from "./theme/ThemeProvider";

const TABS: TabItem[] = [{ id: "home", label: "Home" }];

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

export default function App() {
  const [activeTabId, setActiveTabId] = useState("home");
  const [latest, setLatest] = useState<LatestRunState>({ status: "loading" });
  const [filterOptions, setFilterOptions] = useState<FilterOptionsState>({ status: "loading" });
  const [filters, setFilters] = useState<FilterState>({});
  const clearFilters = () => setFilters({});

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
  }, []);

  return (
    <ThemeProvider>
      <AppShell tabs={TABS} activeTabId={activeTabId} onSelectTab={setActiveTabId}>
        {latest.status === "loading" && <StateView kind="loading" message="Loading the current run." />}
        {latest.status === "empty" && <StateView kind="empty" message="No current run." />}
        {latest.status === "error" && <StateView kind="error" message={latest.message} />}
        {latest.status === "ready" && (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-text-muted">Run date: {latest.run.runDate}</p>
            <FilterBar
              value={filters}
              onChange={setFilters}
              bucketOptions={bucketOptions}
              stanceOptions={stanceOptions}
            />
            <PresetsMenu filters={filters} onApply={setFilters} />
            <ScreenerTable runId={latest.run.runId} filters={filters} onClearFilters={clearFilters} />
          </div>
        )}
      </AppShell>
    </ThemeProvider>
  );
}
