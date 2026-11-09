import { useTheme } from "../theme/ThemeProvider";
import { DataAgeStamp, type DataAgeStampProps } from "./DataAgeStamp";

export function TopBar(props: DataAgeStampProps) {
  const { theme, toggleTheme } = useTheme();
  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <header className="flex min-h-12 flex-wrap items-center gap-x-4 gap-y-2 border-b border-border bg-surface px-4 py-2 text-text">
      <span className="whitespace-nowrap text-base font-semibold">Market Scanner</span>

      <button
        type="button"
        className="whitespace-nowrap inline-flex items-center gap-2 rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text-muted"
      >
        <span>Search symbols</span>
        <kbd className="hidden sm:inline font-mono text-xs text-text">Ctrl K</kbd>
      </button>

      <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-4">
        <DataAgeStamp {...props} />
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={`Switch to ${nextTheme} theme`}
          className="whitespace-nowrap rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text"
        >
          {nextTheme === "light" ? "Light" : "Dark"}
        </button>
      </div>
    </header>
  );
}
