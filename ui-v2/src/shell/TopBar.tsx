import { useTheme } from "../theme/ThemeProvider";
import { DataAgeStamp, type DataAgeStampProps } from "./DataAgeStamp";

export function TopBar(props: DataAgeStampProps) {
  const { theme, toggleTheme } = useTheme();
  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <header className="flex h-12 items-center gap-4 border-b border-border bg-surface px-4 text-text">
      <span className="text-base font-semibold">Market Scanner</span>

      <button
        type="button"
        className="inline-flex items-center gap-2 rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text-muted"
      >
        <span>Search symbols</span>
        <kbd className="font-mono text-xs text-text">Ctrl K</kbd>
      </button>

      <div className="ml-auto flex min-w-0 items-center gap-4">
        <DataAgeStamp {...props} />
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={`Switch to ${nextTheme} theme`}
          className="rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text"
        >
          {nextTheme === "light" ? "Light" : "Dark"}
        </button>
      </div>
    </header>
  );
}
