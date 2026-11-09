import type { ReactNode } from "react";
import { TabStrip, type TabItem } from "./TabStrip";
import { TopBar } from "./TopBar";
import { ResizablePanels } from "./ResizablePanels";
import { WatchlistPanel } from "./WatchlistPanel";

export interface AppShellProps {
  tabs: TabItem[];
  activeTabId: string;
  onSelectTab: (id: string) => void;
  watchlistSymbols?: string[];
  children: ReactNode;
}

export function AppShell({
  tabs,
  activeTabId,
  onSelectTab,
  watchlistSymbols = [],
  children,
}: AppShellProps) {
  return (
    <div className="flex min-h-screen flex-col bg-bg text-text">
      <TopBar />
      <TabStrip tabs={tabs} activeId={activeTabId} onSelect={onSelectTab} />
      <main id="main" className="min-w-0 flex-1 overflow-x-auto p-4">
        <ResizablePanels left={<WatchlistPanel symbols={watchlistSymbols} />}>
          {children}
        </ResizablePanels>
      </main>
    </div>
  );
}
