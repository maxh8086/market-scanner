import type { ReactNode } from "react";
import { TabStrip, type TabItem } from "./TabStrip";
import { TopBar } from "./TopBar";
import { ResizablePanels } from "./ResizablePanels";
import { WatchlistPanel } from "./WatchlistPanel";
import { HoldingsPanel } from "./HoldingsPanel";

export interface AppShellProps {
  tabs: TabItem[];
  activeTabId: string;
  onSelectTab: (id: string) => void;
  onCloseTab?: (id: string) => void;
  /** Session notice shown in the top bar. */
  topBarStatus?: ReactNode;
  children: ReactNode;
}

export function AppShell({ tabs, activeTabId, onSelectTab, onCloseTab, topBarStatus, children }: AppShellProps) {
  return (
    <div className="flex min-h-screen flex-col bg-bg text-text">
      <TopBar status={topBarStatus} />
      <TabStrip tabs={tabs} activeId={activeTabId} onSelect={onSelectTab} onClose={onCloseTab} />
      <main id="main" className="min-w-0 flex-1 overflow-x-auto p-4">
        <ResizablePanels
          left={
            <div className="space-y-4">
              <WatchlistPanel />
              <HoldingsPanel />
            </div>
          }
        >
          {children}
        </ResizablePanels>
      </main>
    </div>
  );
}
