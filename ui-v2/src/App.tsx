import { useEffect, useState } from "react";
import { fetchLatestRun, LatestRunError, type LatestRun } from "./api/latestRun";
import { AppShell } from "./shell/AppShell";
import { StateView } from "./shell/StateView";
import type { TabItem } from "./shell/TabStrip";
import { ScreenerTable } from "./table/ScreenerTable";
import { ThemeProvider } from "./theme/ThemeProvider";

const TABS: TabItem[] = [{ id: "home", label: "Home" }];

type LatestRunState =
  | { status: "loading" }
  | { status: "ready"; run: LatestRun }
  | { status: "empty" }
  | { status: "error"; message: string };

export default function App() {
  const [activeTabId, setActiveTabId] = useState("home");
  const [latest, setLatest] = useState<LatestRunState>({ status: "loading" });

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
            <ScreenerTable runId={latest.run.runId} />
          </div>
        )}
      </AppShell>
    </ThemeProvider>
  );
}
