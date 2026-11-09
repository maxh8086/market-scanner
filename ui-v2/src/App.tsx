import { useState } from "react";
import { AppShell } from "./shell/AppShell";
import type { TabItem } from "./shell/TabStrip";
import { ThemeProvider } from "./theme/ThemeProvider";

const TABS: TabItem[] = [{ id: "home", label: "Home" }];

export default function App() {
  const [activeTabId, setActiveTabId] = useState("home");

  return (
    <ThemeProvider>
      <AppShell tabs={TABS} activeTabId={activeTabId} onSelectTab={setActiveTabId}>
        <p className="text-text-muted">Scanner table arrives in slice 2.</p>
      </AppShell>
    </ThemeProvider>
  );
}
