import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { fetchResults, type Row } from "../api/results";

/** Window event the top bar fires to open the palette. Ctrl/Cmd+K also opens it. */
export const OPEN_COMMAND_PALETTE_EVENT = "market-scanner:open-command-palette";

const SEARCH_DEBOUNCE_MS = 150;
const RESULT_LIMIT = 8;

export interface OpenCommandPaletteDetail {
  /** Element that gets focus back when the palette closes (the trigger). */
  returnFocusTo?: HTMLElement | null;
}

/** Opens the palette from anywhere in the app, e.g. the top bar button. */
export function openCommandPalette(detail: OpenCommandPaletteDetail = {}): void {
  window.dispatchEvent(new CustomEvent<OpenCommandPaletteDetail>(OPEN_COMMAND_PALETTE_EVENT, { detail }));
}

export interface CommandPaletteProps {
  /** Current scan run whose symbols are searched. Null while no run is loaded. */
  runId: string | null;
  /** Same navigation the scan table uses for a company click. */
  onOpenStock: (symbol: string, company: string | null) => void;
}

type SearchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; rows: Row[]; total: number }
  | { status: "error"; message: string };

export function CommandPalette({ runId, onOpenStock }: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [search, setSearch] = useState<SearchState>({ status: "idle" });
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const listId = useId();
  const optionId = (index: number) => `${listId}-option-${index}`;

  // Global shortcut: Ctrl+K on Windows/Linux, Cmd+K on Mac. Toggles the palette.
  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === "k") {
        // Keep the shortcut from running the browser's own bar (Ctrl+K focuses search in some browsers).
        event.preventDefault();
        setOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  // Opening from the top bar button: remember the trigger so focus can return to it.
  useEffect(() => {
    const onOpenEvent = (event: Event) => {
      const detail = (event as CustomEvent<OpenCommandPaletteDetail>).detail;
      if (detail?.returnFocusTo !== undefined) {
        returnFocusRef.current = detail.returnFocusTo;
      }
      setOpen(true);
    };
    window.addEventListener(OPEN_COMMAND_PALETTE_EVENT, onOpenEvent);
    return () => window.removeEventListener(OPEN_COMMAND_PALETTE_EVENT, onOpenEvent);
  }, []);

  // On open: remember the focused element (fallback trigger) and move focus into the input.
  // On close: return focus to the trigger if it is still in the page.
  useEffect(() => {
    if (open) {
      if (returnFocusRef.current === null && document.activeElement instanceof HTMLElement) {
        returnFocusRef.current = document.activeElement;
      }
      inputRef.current?.focus();
      return;
    }
    const target = returnFocusRef.current;
    returnFocusRef.current = null;
    if (target && target.isConnected) {
      target.focus();
    }
    setQuery("");
    setDebouncedQuery("");
    setSearch({ status: "idle" });
    setHighlight(0);
  }, [open]);

  // Debounce typing so each keystroke does not send a request.
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [query]);

  // Search the current run's symbols and company names with the existing results endpoint.
  useEffect(() => {
    if (!open) {
      return;
    }
    if (runId === null || debouncedQuery === "") {
      setSearch({ status: "idle" });
      setHighlight(0);
      return;
    }
    const controller = new AbortController();
    setSearch({ status: "loading" });
    fetchResults(runId, { search: debouncedQuery, perPage: RESULT_LIMIT }, { signal: controller.signal })
      .then((page) => {
        setSearch({ status: "ready", rows: page.results, total: page.total });
        setHighlight(0);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        const message = error instanceof Error ? error.message : "Could not search symbols.";
        setSearch({ status: "error", message });
      });
    return () => controller.abort();
  }, [open, runId, debouncedQuery]);

  const close = () => setOpen(false);

  const choose = (row: Row) => {
    close();
    onOpenStock(row.symbol, row.company);
  };

  const rows = search.status === "ready" ? search.rows : [];

  const onDialogKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === "Tab") {
      // The input is the only focusable control, so Tab stays on it.
      event.preventDefault();
      return;
    }
    if (rows.length === 0) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlight((current) => (current + 1) % rows.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((current) => (current - 1 + rows.length) % rows.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const row = rows[highlight];
      if (row) {
        choose(row);
      }
    }
  };

  if (!open) {
    return null;
  }

  const activeIndex = rows.length > 0 ? Math.min(highlight, rows.length - 1) : -1;

  let body: ReactNode;
  if (runId === null) {
    body = <p className="px-3 py-2 text-sm text-text-muted">No current run to search.</p>;
  } else if (debouncedQuery === "") {
    body = <p className="px-3 py-2 text-sm text-text-muted">Type a symbol or company name.</p>;
  } else if (search.status === "loading") {
    body = <p className="px-3 py-2 text-sm text-text-muted">Searching…</p>;
  } else if (search.status === "error") {
    body = <p className="px-3 py-2 text-sm text-loss">{search.message}</p>;
  } else if (search.status === "ready" && rows.length === 0) {
    body = <p className="px-3 py-2 text-sm text-text-muted">No symbols match “{debouncedQuery}”.</p>;
  } else {
    body = null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-bg/70 px-4 pt-[12vh]">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search symbols"
        onKeyDown={onDialogKeyDown}
        className="flex w-full max-w-lg min-w-0 flex-col overflow-hidden rounded-(--radius-control) border border-border-ui bg-surface shadow-lg text-text"
      >
        <div className="border-b border-border p-2">
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded={rows.length > 0}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
            aria-label="Symbol or company"
            placeholder="Search symbols"
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="w-full min-w-0 rounded-(--radius-control) border border-border-ui bg-surface-2 px-3 py-2 text-sm text-text placeholder:text-text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--focus)"
          />
        </div>

        <ul
          id={listId}
          role="listbox"
          aria-label="Matching symbols"
          hidden={rows.length === 0}
          className="max-h-[60vh] overflow-y-auto py-1"
        >
          {rows.map((row, index) => {
            const active = index === activeIndex;
            return (
              <li
                key={row.symbol}
                id={optionId(index)}
                role="option"
                aria-selected={active}
                onMouseEnter={() => setHighlight(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(row)}
                className={`flex min-w-0 cursor-pointer items-baseline gap-3 px-3 py-2 text-sm ${active ? "bg-surface-2" : ""}`}
              >
                <span className="shrink-0 font-mono font-semibold">{row.symbol}</span>
                <span className="min-w-0 truncate text-text-muted">{row.company ?? ""}</span>
              </li>
            );
          })}
        </ul>

        {body}

        <p role="status" aria-live="polite" className="sr-only">
          {search.status === "ready" && rows.length > 0 ? `${search.total} matching symbols` : ""}
        </p>
      </div>
    </div>
  );
}
