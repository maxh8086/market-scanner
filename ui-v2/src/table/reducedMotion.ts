import { useSyncExternalStore } from "react";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/** The media query list, or null where matchMedia is missing or throws (old browsers, some test runners). */
function reducedMotionQuery(): MediaQueryList | null {
  try {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return null;
    }
    return window.matchMedia(REDUCED_MOTION_QUERY);
  } catch {
    return null;
  }
}

function subscribe(onChange: () => void): () => void {
  const query = reducedMotionQuery();
  if (!query) {
    return () => {};
  }
  query.addEventListener?.("change", onChange);
  return () => query.removeEventListener?.("change", onChange);
}

function snapshot(): boolean {
  return reducedMotionQuery()?.matches ?? false;
}

/** True while the user has asked the OS to reduce motion. Follows changes while mounted. */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false);
}
