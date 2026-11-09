export interface TabItem {
  id: string;
  label: string;
  /** Shows a close control. Only stock tabs are closable; Home is not. */
  closable?: boolean;
}

export interface TabStripProps {
  tabs: TabItem[];
  activeId: string;
  onSelect: (id: string) => void;
  onClose?: (id: string) => void;
}

export function TabStrip({ tabs, activeId, onSelect, onClose }: TabStripProps) {
  return (
    <div className="border-b border-border bg-surface-2">
      <div role="tablist" className="flex overflow-x-auto">
        {tabs.map((tab) => {
          const selected = tab.id === activeId;
          const tabClass = `whitespace-nowrap border-b-2 px-4 py-2 text-sm ${
            selected ? "border-accent font-semibold text-text" : "border-transparent text-text-muted"
          }`;
          const tabButton = (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => onSelect(tab.id)}
              className={tabClass}
            >
              {tab.label}
            </button>
          );
          if (!tab.closable || !onClose) {
            return tabButton;
          }
          return (
            <div key={tab.id} role="none" className="flex whitespace-nowrap">
              {tabButton}
              <button
                type="button"
                aria-label={`Close ${tab.label} tab`}
                onClick={() => onClose(tab.id)}
                className="border-b-2 border-transparent px-2 py-2 text-sm text-text-muted"
              >
                ×
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
