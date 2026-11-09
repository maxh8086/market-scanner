import { useEffect, useId, useRef, useState } from "react";

export interface ChooserColumn {
  id: string;
  label: string;
  visible: boolean;
  onToggle: (event: unknown) => void;
}

export interface ColumnChooserProps {
  columns: readonly ChooserColumn[];
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        d="M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Pencil button that opens a checklist of table columns. Unchecking a column hides it. Escape
 * and a click outside close the list.
 */
export function ColumnChooser({ columns }: ColumnChooserProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const listId = useId();

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

  return (
    <span ref={wrapRef} className="relative inline-flex">
      <button
        type="button"
        aria-label="Add or remove columns"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        title="Add or remove columns"
        onClick={() => setOpen((current) => !current)}
        className="inline-flex size-8 items-center justify-center rounded-(--radius-control) border border-border-ui text-text-muted hover:text-text"
      >
        <PencilIcon />
      </button>
      {open ? (
        <div
          id={listId}
          role="group"
          aria-label="Columns"
          className="absolute right-0 top-full z-50 mt-1 flex w-52 flex-col gap-2 rounded-md border border-border-ui bg-surface p-3 text-sm text-text shadow-lg"
        >
          <span className="font-semibold">Columns</span>
          {columns.map((column) => (
            <label key={column.id} className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={column.visible}
                onChange={column.onToggle}
                className="size-4 accent-accent"
              />
              {column.label}
            </label>
          ))}
        </div>
      ) : null}
    </span>
  );
}
