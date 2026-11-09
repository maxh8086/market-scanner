import { useCallback, useState, type PointerEvent as ReactPointerEvent } from "react";

/** Narrowest a column can be dragged to. Below this the header and values are unreadable. */
export const MIN_COLUMN_WIDTH = 48;

export interface ColumnWidthsState {
  /** Pixel widths set by dragging. Empty until the user drags, so the table keeps its autofit layout. */
  widths: Readonly<Record<string, number>>;
  /** Start a drag from a resize handle inside the header cell of `columnId`. */
  startResize: (event: ReactPointerEvent<HTMLElement>, columnId: string) => void;
  /** Drop manual widths and return to autofit. */
  reset: () => void;
}

/**
 * Drag-to-resize column widths for a plain HTML table. The first drag measures every header cell
 * (`th[data-col]`) and fixes its current width, so the drag starts from what the user sees. Cells
 * then shrink with an ellipsis, so a column can go below its autofit width.
 */
export function useColumnWidths(): ColumnWidthsState {
  const [widths, setWidths] = useState<Record<string, number>>({});

  const startResize = useCallback((event: ReactPointerEvent<HTMLElement>, columnId: string) => {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const header = event.currentTarget.closest("th");
    const table = header?.closest("table");
    if (!header || !table) {
      return;
    }

    const measured: Record<string, number> = {};
    table.querySelectorAll<HTMLTableCellElement>("thead th[data-col]").forEach((cell) => {
      const id = cell.dataset.col;
      if (id) {
        measured[id] = cell.getBoundingClientRect().width;
      }
    });
    const startX = event.clientX;
    const startWidth = measured[columnId] ?? header.getBoundingClientRect().width;
    setWidths((current) => ({ ...measured, ...current }));

    const onMove = (move: PointerEvent) => {
      const next = Math.max(MIN_COLUMN_WIDTH, Math.round(startWidth + move.clientX - startX));
      setWidths((current) => ({ ...current, [columnId]: next }));
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      document.body.style.cursor = "";
    };
    document.body.style.cursor = "col-resize";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
  }, []);

  const reset = useCallback(() => setWidths({}), []);

  return { widths, startResize, reset };
}

/** Thin drag strip on the right edge of a header cell. Double-click returns the table to autofit. */
export function ColumnResizeHandle({
  label,
  onStart,
  onReset,
}: {
  label: string;
  onStart: (event: ReactPointerEvent<HTMLElement>) => void;
  onReset: () => void;
}) {
  return (
    <span
      aria-hidden="true"
      data-resize-for={label}
      title="Drag to resize. Double-click to reset widths."
      onPointerDown={onStart}
      onDoubleClick={onReset}
      className="absolute right-0 top-0 z-10 h-full w-2 cursor-col-resize touch-none select-none hover:bg-accent/40"
    />
  );
}
