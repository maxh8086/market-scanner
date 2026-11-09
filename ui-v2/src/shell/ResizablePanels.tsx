import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

export interface ResizablePanelsProps {
  left: ReactNode;
  children: ReactNode;
  storageKey?: string;
  defaultWidth?: number;
  minWidth?: number;
  maxWidth?: number;
}

const KEYBOARD_STEP = 16;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function readStoredWidth(key: string, fallback: number, min: number, max: number): number {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) return fallback;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < min || value > max) return fallback;
    return value;
  } catch {
    return fallback;
  }
}

function saveWidth(key: string, width: number): void {
  try {
    window.localStorage.setItem(key, String(width));
  } catch {
    // Storage can be blocked or full. Resizing still works without it.
  }
}

export function ResizablePanels({
  left,
  children,
  storageKey = "ms-watchlist-width",
  defaultWidth = 240,
  minWidth = 200,
  maxWidth = 480,
}: ResizablePanelsProps) {
  const [width, setWidth] = useState(() =>
    readStoredWidth(storageKey, defaultWidth, minWidth, maxWidth),
  );
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef<{ pointerX: number; startWidth: number } | null>(null);

  useEffect(() => {
    if (!dragging) return;

    const onMove = (event: PointerEvent) => {
      const start = dragStart.current;
      if (!start) return;
      const next = clamp(start.startWidth + event.clientX - start.pointerX, minWidth, maxWidth);
      setWidth(next);
      saveWidth(storageKey, next);
    };
    const onUp = () => {
      dragStart.current = null;
      setDragging(false);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [dragging, minWidth, maxWidth, storageKey]);

  const applyWidth = (next: number) => {
    const clamped = clamp(next, minWidth, maxWidth);
    setWidth(clamped);
    saveWidth(storageKey, clamped);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      applyWidth(width - KEYBOARD_STEP);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      applyWidth(width + KEYBOARD_STEP);
    }
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    dragStart.current = { pointerX: event.clientX, startWidth: width };
    setDragging(true);
  };

  const panelStyle = { "--panel-width": `${width}px` } as CSSProperties;

  return (
    <div className="flex min-w-0 flex-col md:flex-row">
      <div
        className="w-full min-w-0 md:w-[var(--panel-width)] md:shrink-0"
        style={panelStyle}
      >
        {left}
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize watchlist panel"
        aria-valuenow={width}
        aria-valuemin={minWidth}
        aria-valuemax={maxWidth}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        className="hidden w-2 shrink-0 cursor-col-resize bg-border md:block"
      />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
