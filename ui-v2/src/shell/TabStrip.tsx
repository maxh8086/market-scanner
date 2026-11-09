export interface TabItem {
  id: string;
  label: string;
}

export interface TabStripProps {
  tabs: TabItem[];
  activeId: string;
  onSelect: (id: string) => void;
}

export function TabStrip({ tabs, activeId, onSelect }: TabStripProps) {
  return (
    <div className="border-b border-border bg-surface-2">
      <div role="tablist" className="flex overflow-x-auto">
        {tabs.map((tab) => {
          const selected = tab.id === activeId;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => onSelect(tab.id)}
              className={`whitespace-nowrap border-b-2 px-4 py-2 text-sm ${
                selected
                  ? "border-accent font-semibold text-text"
                  : "border-transparent text-text-muted"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
