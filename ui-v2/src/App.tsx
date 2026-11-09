import { useState } from "react";
import { AppShell } from "./shell/AppShell";
import { StateView } from "./shell/StateView";
import type { TabItem } from "./shell/TabStrip";
import { ScreenerTable } from "./table/ScreenerTable";
import { ThemeProvider } from "./theme/ThemeProvider";

const TABS: TabItem[] = [{ id: "home", label: "Home" }];
const RUN_ID: string = import.meta.env.VITE_RUN_ID ?? "";

export default function App() {
  const [activeTabId, setActiveTabId] = useState("home");

  return (
    <ThemeProvider>
      <AppShell tabs={TABS} activeTabId={activeTabId} onSelectTab={setActiveTabId}>
        {RUN_ID ? (
          <ScreenerTable runId={RUN_ID} />
        ) : (
          <StateView kind="idle" message="No run selected." />
        )}
      </AppShell>
    </ThemeProvider>
  );
}
