/** Pure helpers for the sector heatmap and table. No React, no network. */

import type { SectorSummaryRow } from "../api/sectorSummary";

export type SortKey = "sector" | "avgChangePct" | "count" | "ratio";
export type SortDir = "asc" | "desc";

export interface SortState {
  key: SortKey;
  dir: SortDir;
}

/** Changes smaller than this (in percent) are shown as flat. */
const FLAT_BAND_PCT = 0.005;
/** Changes at or beyond this (in percent) get the strong tone. Smaller ones get the light tone. */
const STRONG_BAND_PCT = 1;

export type Tone = "strong_gain" | "light_gain" | "flat" | "light_loss" | "strong_loss";

/** Tone band for a change in percent. The arrow and sign in the text carry the meaning too. */
export function toneOf(value: number): Tone {
  if (Math.abs(value) < FLAT_BAND_PCT) {
    return "flat";
  }
  if (value > 0) {
    return value >= STRONG_BAND_PCT ? "strong_gain" : "light_gain";
  }
  return value <= -STRONG_BAND_PCT ? "strong_loss" : "light_loss";
}

/** Advancers divided by decliners. Infinity when there are advancers and no decliners. 0 when neither. */
export function advDecRatio(row: SectorSummaryRow): number {
  if (row.decliners === 0) {
    return row.advancers > 0 ? Number.POSITIVE_INFINITY : 0;
  }
  return row.advancers / row.decliners;
}

/** Share of the sector's stocks that advanced and declined, as percentages of count. */
export function breadthShares(row: SectorSummaryRow): { up: number; down: number } {
  if (row.count <= 0) {
    return { up: 0, down: 0 };
  }
  return {
    up: (row.advancers / row.count) * 100,
    down: (row.decliners / row.count) * 100,
  };
}

/** Returns a new array sorted by the key. Ties fall back to sector name, so the order is stable. */
export function sortSectors(rows: readonly SectorSummaryRow[], sort: SortState): SectorSummaryRow[] {
  const direction = sort.dir === "asc" ? 1 : -1;
  const valueOf = (row: SectorSummaryRow): number | string => {
    switch (sort.key) {
      case "sector":
        return row.sector;
      case "avgChangePct":
        return row.avgChangePct;
      case "count":
        return row.count;
      case "ratio":
        return advDecRatio(row);
    }
  };
  return [...rows].sort((a, b) => {
    const left = valueOf(a);
    const right = valueOf(b);
    if (left !== right) {
      if (typeof left === "string" && typeof right === "string") {
        return left.localeCompare(right) * direction;
      }
      return ((left as number) - (right as number)) * direction;
    }
    return a.sector.localeCompare(b.sector);
  });
}

/**
 * The n best and n worst sectors by change, best first. The worst list never repeats a sector
 * that is already in the best list, so a short input gives fewer than 2n items in total.
 */
export function topAndBottom(
  rows: readonly SectorSummaryRow[],
  n: number,
): { top: SectorSummaryRow[]; bottom: SectorSummaryRow[] } {
  const sorted = sortSectors(rows, { key: "avgChangePct", dir: "desc" });
  const top = sorted.slice(0, n);
  const bottomStart = Math.max(n, sorted.length - n);
  const bottom = sorted.slice(bottomStart).reverse();
  return { top, bottom };
}

/** "1 stock" or "12 stocks". */
export function stockCountLabel(count: number): string {
  return count === 1 ? "1 stock" : `${count} stocks`;
}
