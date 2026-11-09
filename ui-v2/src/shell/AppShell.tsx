import type { ReactNode } from "react";
import { TabStrip, type TabItem } from "./TabStrip";
import { TopBar } from "./TopBar";

export interface AppShellProps {
  tabs: TabItem[];
  activeTabId: string;
  onSelectTab: (id: string) => void;
  children: ReactNode;
}

export function AppShell({ tabs, activeTabId, onSelectTab, children }: AppShellProps) {
  return (
    <div className="flex min-h-screen flex-col bg-bg text-text">
      <TopBar />
      <TabStrip tabs={tabs} activeId={activeTabId} onSelect={onSelectTab} />
      <main id="main" className="min-w-0 flex-1 overflow-x-auto p-4">
        {children}
      </main>
    </div>
  );
}
