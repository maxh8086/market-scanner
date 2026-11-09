export const INDEX_SEGMENTS = {
  "Key Indices": ["SENSEX", "INDIA VIX", "GIFT NIFTY", "NIFTY 50", "NIFTY NEXT 50", "NIFTY 100", "NIFTY 200", "NIFTY 500"],
  "Sectoral Indices": [
    "NIFTY BANK",
    "NIFTY IT",
    "NIFTY AUTO",
    "NIFTY PHARMA",
    "NIFTY FMCG",
    "NIFTY METAL",
    "NIFTY REALTY",
    "NIFTY ENERGY",
    "NIFTY PSU BANK",
    "NIFTY PRIVATE BANK",
    "NIFTY FIN SERVICE",
    "NIFTY MEDIA",
    "NIFTY HEALTHCARE",
    "NIFTY CONSUMER DURABLES",
    "NIFTY OIL & GAS",
  ],
  "Other Indices": ["NIFTY MICROCAP 250"],
  "Large Cap": ["NIFTY 50", "NIFTY NEXT 50", "NIFTY 100"],
  "Mid Cap": ["NIFTY MIDCAP 150"],
  "Small Cap": ["NIFTY SMALLCAP 250"],
} as const;

export type IndexSegment = keyof typeof INDEX_SEGMENTS;
export const SEGMENT_NAMES = Object.keys(INDEX_SEGMENTS) as IndexSegment[];
export const DEFAULT_SEGMENT: IndexSegment = "Key Indices";

/** Indices shown when the segment is "Key Indices". Kept under the old name for existing callers. */
export const DEFAULT_INDICES: readonly string[] = INDEX_SEGMENTS["Key Indices"];

/** Every index in any segment, each once. Used to refuse custom symbols that duplicate an index. */
export const ALL_INDICES: readonly string[] = [...new Set<string>(Object.values(INDEX_SEGMENTS).flat())];

/** Rows for a segment. "All Indices" is the union of every segment. */
export function segmentIndices(segment: IndexSegment | "All Indices"): readonly string[] {
  return segment === "All Indices" ? ALL_INDICES : INDEX_SEGMENTS[segment];
}

/** Per-browser custom list. Stored locally; not shared between viewers. */
const STORAGE_KEY = "marketScanner.customWatchlist";
const MAX_CUSTOM = 50;
/** Letters, digits, space, & and hyphen. Upper-cased before the check. */
const SYMBOL_PATTERN = /^[A-Z0-9][A-Z0-9 &-]{0,29}$/;

export function normalizeSymbol(raw: string): string | null {
  const symbol = raw.trim().toUpperCase().replace(/\s+/g, " ");
  return SYMBOL_PATTERN.test(symbol) ? symbol : null;
}

export function loadCustomWatchlist(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const clean: string[] = [];
    for (const item of parsed) {
      if (typeof item !== "string") continue;
      const symbol = normalizeSymbol(item);
      if (symbol && !clean.includes(symbol) && !ALL_INDICES.includes(symbol)) {
        clean.push(symbol);
      }
    }
    return clean.slice(0, MAX_CUSTOM);
  } catch {
    return [];
  }
}

export function saveCustomWatchlist(symbols: readonly string[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(symbols));
  } catch {
    // Storage is blocked or full. The list still works for this session.
  }
}

/** Adds a symbol. Returns the new list, or the same list with an error message when the add is refused. */
export function addCustomSymbol(
  current: readonly string[],
  raw: string,
): { symbols: string[]; error: string | null } {
  const symbol = normalizeSymbol(raw);
  if (!symbol) {
    return { symbols: [...current], error: "Use letters, digits, spaces, & or -. Up to 30 characters." };
  }
  if (ALL_INDICES.includes(symbol)) {
    return { symbols: [...current], error: `${symbol} is already in the index list.` };
  }
  if (current.includes(symbol)) {
    return { symbols: [...current], error: `${symbol} is already on your watchlist.` };
  }
  if (current.length >= MAX_CUSTOM) {
    return { symbols: [...current], error: `The custom watchlist holds up to ${MAX_CUSTOM} symbols.` };
  }
  return { symbols: [...current, symbol], error: null };
}
