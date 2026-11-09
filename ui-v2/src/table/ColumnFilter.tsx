import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { createPortal } from "react-dom";

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

// Rendered through a portal with fixed positioning, so the table's scroll container cannot clip it.
const POPOVER_CLASS =
  "fixed z-50 flex w-60 flex-col gap-2 rounded-md border border-border-ui bg-surface p-3 text-left text-sm font-normal text-text shadow-lg";
const POPOVER_WIDTH = 240;
const VIEWPORT_GUTTER = 8;

interface PopoverPosition {
  top: number;
  left: number;
}

/** Places the popover under the button, on the preferred edge, then keeps it inside the viewport. */
function popoverPosition(
  button: DOMRect,
  align: "left" | "right",
): PopoverPosition {
  const preferred =
    align === "right" ? button.right - POPOVER_WIDTH : button.left;
  const maxLeft = window.innerWidth - POPOVER_WIDTH - VIEWPORT_GUTTER;
  return {
    top: button.bottom + 4,
    left: Math.max(VIEWPORT_GUTTER, Math.min(preferred, maxLeft)),
  };
}
const INPUT_CLASS =
  "w-full min-w-0 rounded-(--radius-control) border border-border-ui bg-bg px-2 py-1 text-sm text-text";

function FunnelIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="14"
      height="14"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M3 5h18l-7 8v6l-4 2v-8z" fill="currentColor" />
    </svg>
  );
}

/**
 * A funnel button in a table header. It opens a small popover with the inputs for one column,
 * the same pattern as the classic results table. Enter applies, Escape closes.
 */
export function ColumnFilter({
  label,
  kind,
  value,
  options = [],
  active,
  align = "left",
  onApply,
}: ColumnFilterProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<readonly [string, string]>(value);
  const [position, setPosition] = useState<PopoverPosition | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const popoverId = useId();

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) {
      return;
    }
    const place = () => {
      if (buttonRef.current) {
        setPosition(
          popoverPosition(buttonRef.current.getBoundingClientRect(), align),
        );
      }
    };
    place();
    // Follow the header while the table scrolls, and recompute when the window resizes.
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, align]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        buttonRef.current?.contains(target) ||
        popoverRef.current?.contains(target)
      ) {
        return;
      }
      setOpen(false);
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

  const onKeyDownInput = (
    event: ReactKeyboardEvent<HTMLInputElement | HTMLSelectElement>,
  ) => {
    if (event.key === "Enter") {
      event.preventDefault();
      apply(draft);
    }
  };

  return (
    <span className="relative inline-flex align-middle">
      <button
        ref={buttonRef}
        type="button"
        aria-label={`Filter ${label}`}
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        title={`Filter ${label}`}
        onClick={toggle}
        className={`ml-1.5 inline-flex size-6 items-center justify-center rounded-md border ${
          active
            ? "border-accent text-accent"
            : "border-transparent text-text-muted hover:border-border-ui"
        }`}
      >
        <FunnelIcon />
      </button>
      {open && position
        ? createPortal(
            <div
              ref={popoverRef}
              id={popoverId}
              role="dialog"
              aria-label={`Filter ${label}`}
              style={{ top: position.top, left: position.left }}
              className={POPOVER_CLASS}
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
            </div>,
            document.body,
          )
        : null}
    </span>
  );
}
