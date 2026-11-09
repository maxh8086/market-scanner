import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

export type ColumnFilterKind = "text" | "range" | "dates" | "select";

export interface ColumnFilterProps {
  /** Column name shown in the popover title and the button's accessible name. */
  label: string;
  kind: ColumnFilterKind;
  /** Raw input strings. "text" and "select" use the first entry; "range" and "dates" use both. */
  value: readonly [string, string];
  /** Choices for "select". The first option is always "Any" (an empty value). */
  options?: readonly string[];
  /** Whether a filter on this column is set. Lights the funnel icon. */
  active: boolean;
  /** Which edge of the header cell the popover hangs from. */
  align?: "left" | "right";
  onApply: (next: readonly [string, string]) => void;
}

const POPOVER_CLASS =
  "absolute top-full z-50 mt-1 flex w-60 flex-col gap-2 rounded-md border border-border-ui bg-surface p-3 text-left text-sm font-normal text-text shadow-lg";
const INPUT_CLASS =
  "w-full min-w-0 rounded-(--radius-control) border border-border-ui bg-bg px-2 py-1 text-sm text-text";

function FunnelIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">
      <path d="M3 5h18l-7 8v6l-4 2v-8z" fill="currentColor" />
    </svg>
  );
}

/**
 * A funnel button in a table header. It opens a small popover with the inputs for one column,
 * the same pattern as the classic results table. Enter applies, Escape closes.
 */
export function ColumnFilter({ label, kind, value, options = [], active, align = "left", onApply }: ColumnFilterProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<readonly [string, string]>(value);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const popoverId = useId();

  useEffect(() => {
    if (!open) {
      return;
    }
    const onPointerDown = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const toggle = () => {
    if (!open) {
      setDraft(value);
    }
    setOpen((current) => !current);
  };

  const apply = (next: readonly [string, string]) => {
    onApply(next);
    setOpen(false);
  };

  const setDraftAt = (index: 0 | 1, text: string) => {
    setDraft(index === 0 ? [text, draft[1]] : [draft[0], text]);
  };

  const onKeyDownInput = (event: ReactKeyboardEvent<HTMLInputElement | HTMLSelectElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      apply(draft);
    }
  };

  return (
    <span ref={wrapRef} className="relative inline-flex align-middle">
      <button
        type="button"
        aria-label={`Filter ${label}`}
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        title={`Filter ${label}`}
        onClick={toggle}
        className={`ml-1.5 inline-flex size-6 items-center justify-center rounded-md border ${
          active ? "border-accent text-accent" : "border-transparent text-text-muted hover:border-border-ui"
        }`}
      >
        <FunnelIcon />
      </button>
      {open ? (
        <div
          id={popoverId}
          role="dialog"
          aria-label={`Filter ${label}`}
          className={`${POPOVER_CLASS} ${align === "right" ? "right-0" : "left-0"}`}
        >
          <div className="font-semibold">{label}</div>
          {kind === "text" ? (
            <input
              aria-label={label}
              type="text"
              value={draft[0]}
              placeholder="Type to match"
              onChange={(event) => setDraftAt(0, event.target.value)}
              onKeyDown={onKeyDownInput}
              className={INPUT_CLASS}
              autoFocus
            />
          ) : null}
          {kind === "select" ? (
            <select
              aria-label={label}
              value={draft[0]}
              onChange={(event) => setDraftAt(0, event.target.value)}
              onKeyDown={onKeyDownInput}
              className={INPUT_CLASS}
              autoFocus
            >
              <option value="">Any</option>
              {options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          ) : null}
          {kind === "range" || kind === "dates" ? (
            <div className="grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1 text-xs text-text-muted">
                {kind === "range" ? "Min" : "From"}
                <input
                  type={kind === "range" ? "number" : "date"}
                  inputMode={kind === "range" ? "decimal" : undefined}
                  step={kind === "range" ? "any" : undefined}
                  value={draft[0]}
                  onChange={(event) => setDraftAt(0, event.target.value)}
                  onKeyDown={onKeyDownInput}
                  className={INPUT_CLASS}
                  autoFocus
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-text-muted">
                {kind === "range" ? "Max" : "To"}
                <input
                  type={kind === "range" ? "number" : "date"}
                  inputMode={kind === "range" ? "decimal" : undefined}
                  step={kind === "range" ? "any" : undefined}
                  value={draft[1]}
                  onChange={(event) => setDraftAt(1, event.target.value)}
                  onKeyDown={onKeyDownInput}
                  className={INPUT_CLASS}
                />
              </label>
            </div>
          ) : null}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => apply(["", ""])}
              className="rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={() => apply(draft)}
              className="rounded-(--radius-control) bg-accent px-3 py-1 text-sm text-bg"
            >
              Apply
            </button>
          </div>
        </div>
      ) : null}
    </span>
  );
}
