/** Market Watch sections, in display order. Each section is a divider header plus its rows. */
export const INDEX_SEGMENTS = {
  "Key Indices": [
    "India VIX",
    "NIFTY 50",
    "NIFTY BANK",
    "NIFTY Midcap 100",
    "NIFTY NEXT 50",
    "NIFTY 100",
    "Nifty 200",
    "NIFTY 500",
    "NIFTY Smallcap 100",
    "NIFTY MIDCAP 50",
    "NIFTY SMLCAP 50",
    "NIFTY 750 TOTAL MKT",
  ],
  "Sectoral Indices": [
    "NIFTY Auto",
    "NIFTY IT",
    "NIFTY PSU Bank",
    "NIFTY Fin Service",
    "NIFTY Pharma",
    "NIFTY FMCG",
    "NIFTY Metal",
    "NIFTY Realty",
    "NIFTY Media",
    "NIFTY Energy",
    "Nifty Pvt Bank",
    "NIFTY Infra",
    "NIFTY Commodities",
    "NIFTY Consumption",
    "NIFTY PSE",
    "NIFTY Services",
    "Nifty FinSrv25/50",
    "Nifty Cons Durbl",
    "Nifty Healthcare",
    "Nifty Oil & Gas",
    "NIFTY India Mfg",
    "Nifty India Defence",
  ],
  "Other Indices": [
    "NIFTY MIDCAP 150",
    "NIFTY MIDSML 400",
    "NIFTY SMLCAP 250",
    "NIFTY MNC",
    "NIFTY AlphaLowVol 30",
    "Nifty200 Momentum 30",
    "Nifty LargeMid250",
    "Nifty500 Mul50:25:25",
    "NIFTY CPSE",
    "NIFTY MID SELECT",
    "NIFTY IND DIGITAL",
    "NIFTY M150 QLTY50",
    "Nifty Microcap 250",
    "Nifty Capital Market",
    "Nifty India FPI 150",
  ],
} as const;

export type IndexSegment = keyof typeof INDEX_SEGMENTS;
export const SEGMENT_NAMES = Object.keys(INDEX_SEGMENTS) as IndexSegment[];
export const DEFAULT_SEGMENT: IndexSegment = "Key Indices";

/** Key Indices rows. Kept under the old name for existing callers. */
export const DEFAULT_INDICES: readonly string[] = INDEX_SEGMENTS["Key Indices"];

/** Every index in any section, each once. Used to refuse custom symbols that duplicate an index. */
export const ALL_INDICES: readonly string[] = [...new Set<string>(Object.values(INDEX_SEGMENTS).flat())];
/** Upper-cased index names. Custom symbols are upper-cased before the duplicate check, so compare against this. */
const ALL_INDICES_UPPER: readonly string[] = ALL_INDICES.map((name) => name.toUpperCase());

/** Rows for one section. */
export function segmentIndices(segment: IndexSegment): readonly string[] {
  return INDEX_SEGMENTS[segment];
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
      if (symbol && !clean.includes(symbol) && !ALL_INDICES_UPPER.includes(symbol)) {
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
  if (ALL_INDICES_UPPER.includes(symbol)) {
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
