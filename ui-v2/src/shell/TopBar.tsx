import type { ReactNode } from "react";
import { useTheme } from "../theme/ThemeProvider";
import { DataAgeStamp, type DataAgeStampProps } from "./DataAgeStamp";
import { EodRefreshButton } from "./EodRefreshButton";
import { openCommandPalette } from "./CommandPalette";

export interface TopBarProps extends DataAgeStampProps {
  /** Session notice (market closed, pre-open, stale) shown beside the search button. */
  status?: ReactNode;
}

export function TopBar({ status, ...stampProps }: TopBarProps) {
  // The stamp renders only when a run date or timestamp exists, so no empty "Data as of —" shows.
  const hasStamp = Boolean(stampProps.runDate || stampProps.runTimestamp);
  const { theme, toggleTheme } = useTheme();
  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <header className="flex min-h-12 flex-wrap items-center gap-x-4 gap-y-2 border-b border-border bg-surface px-4 py-2 text-text">
      <span className="whitespace-nowrap text-base font-semibold">Market Scanner</span>

      <button
        type="button"
        aria-haspopup="dialog"
        onClick={(event) => openCommandPalette({ returnFocusTo: event.currentTarget })}
        className="whitespace-nowrap inline-flex items-center gap-2 rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--focus)"
      >
        <span>Search symbols</span>
        <kbd className="hidden sm:inline font-mono text-xs text-text">Ctrl K</kbd>
      </button>

      {status || hasStamp ? (
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {status}
          {hasStamp ? <DataAgeStamp {...stampProps} /> : null}
        </div>
      ) : null}

      <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-4">
        <EodRefreshButton />
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
