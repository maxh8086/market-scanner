import type { QueryFn } from "../app.js";
import type { Holding } from "../holdings/kiteHoldings.js";
import type { PortfolioTx } from "../portfolioTx.js";
import type { BrokerId } from "./names.js";

/**
 * Stored portfolio snapshots (migration 058). A sync writes one `ok` portfolio_sync row and all of its holdings
 * in one transaction. A failed sync writes nothing, so the previous snapshot stays. The server only uses the
 * INSERT and SELECT grants on these tables.
 */

/** Holdings per INSERT statement. All chunks still run inside the one transaction. */
export const HOLDING_CHUNK_ROWS = 500;

/** The holding shape the browser receives. The exchange and the raw row stay in the database. */
export interface PublicHolding {
  symbol: string;
  isin: string | null;
  quantity: number;
  averagePrice: number;
  lastPrice: number;
  pnl: number;
  dayChange: number | null;
  dayChangePct: number | null;
}

export interface SnapshotView {
  holdings: PublicHolding[];
  syncedAt: string | null;
  broker: BrokerId | null;
}

export interface OkSnapshot {
  syncId: string;
  profile: string;
  broker: BrokerId;
  syncedAt: string;
  holdings: Holding[];
}

const SYNC_INSERT_SQL =
  "INSERT INTO portfolio_sync (sync_id, profile_id, broker, synced_at, status, row_count) VALUES ($1, $2, $3, $4, $5, $6)";
const HOLDING_COLUMNS = [
  "sync_id",
  "profile_id",
  "broker",
  "symbol",
  "isin",
  "exchange",
  "quantity",
  "average_price",
  "last_price",
  "pnl",
  "day_change",
  "day_change_pct",
  "raw",
];
const LATEST_SYNC_SQL =
  "SELECT sync_id, synced_at FROM portfolio_sync WHERE profile_id = $1 AND broker = $2 AND status = 'ok' ORDER BY synced_at DESC LIMIT 1";
const SNAPSHOT_HOLDINGS_SQL =
  "SELECT symbol, isin, quantity, average_price, last_price, pnl, day_change, day_change_pct FROM portfolio_holding WHERE sync_id = $1 ORDER BY symbol";

/** One multi-row INSERT for a list of holdings. The raw column stores the parsed holding object only. */
export function buildHoldingInsert(
  syncId: string,
  profile: string,
  broker: BrokerId,
  rows: Holding[],
): { text: string; values: unknown[] } {
  const values: unknown[] = [];
  const groups: string[] = [];
  for (const holding of rows) {
    const base = values.length;
    values.push(
      syncId,
      profile,
      broker,
      holding.symbol,
      holding.isin,
      holding.exchange,
      holding.quantity,
      holding.averagePrice,
      holding.lastPrice,
      holding.pnl,
      holding.dayChange,
      holding.dayChangePct,
      JSON.stringify(holding),
    );
    const marks = HOLDING_COLUMNS.map((_, i) => `$${base + i + 1}`);
    marks[marks.length - 1] = `${marks[marks.length - 1]}::jsonb`;
    groups.push(`(${marks.join(", ")})`);
  }
  return {
    text: `INSERT INTO portfolio_holding (${HOLDING_COLUMNS.join(", ")}) VALUES ${groups.join(", ")}`,
    values,
  };
}

/**
 * Quantity-weighted average of the non-null values: sum(q_i * v_i) / sum(q_i) over rows with v_i !== null. When the
 * weights sum to 0, the first non-null value. Null when every value is null.
 */
function weightedAverage(group: Holding[], pick: (row: Holding) => number | null): number | null {
  let weighted = 0;
  let weight = 0;
  let firstValue: number | null = null;
  for (const row of group) {
    const value = pick(row);
    if (value === null) continue;
    if (firstValue === null) firstValue = value;
    weighted += row.quantity * value;
    weight += row.quantity;
  }
  if (firstValue === null) return null;
  return weight === 0 ? firstValue : weighted / weight;
}

/**
 * Merges rows that share (symbol, exchange), because the table's primary key rejects duplicates. Keeps first-seen
 * order. The merge rule for each column:
 * - quantity: summed.
 * - averagePrice: quantity-weighted over all rows; the first row's value when the total quantity is 0.
 * - lastPrice: the first row's value.
 * - pnl: summed.
 * - dayChange: quantity-weighted average of the non-null values (per share, never summed).
 * - dayChangePct: same rule as dayChange.
 * - isin: the first non-null value.
 */
export function mergeDuplicateHoldings(rows: Holding[]): Holding[] {
  const groups = new Map<string, Holding[]>();
  for (const row of rows) {
    const key = `${row.symbol}\u0000${row.exchange}`;
    const group = groups.get(key);
    if (group) group.push(row);
    else groups.set(key, [row]);
  }

  const merged: Holding[] = [];
  for (const group of groups.values()) {
    if (group.length === 1) {
      merged.push(group[0]);
      continue;
    }
    const first = group[0];
    const quantity = group.reduce((sum, row) => sum + row.quantity, 0);
    const cost = group.reduce((sum, row) => sum + row.quantity * row.averagePrice, 0);
    merged.push({
      symbol: first.symbol,
      exchange: first.exchange,
      isin: group.find((row) => row.isin !== null)?.isin ?? null,
      quantity,
      averagePrice: quantity === 0 ? first.averagePrice : cost / quantity,
      lastPrice: first.lastPrice,
      pnl: group.reduce((sum, row) => sum + row.pnl, 0),
      dayChange: weightedAverage(group, (row) => row.dayChange),
      dayChangePct: weightedAverage(group, (row) => row.dayChangePct),
    });
  }
  return merged;
}

/**
 * Writes one ok sync and its holdings in a single transaction. Duplicate (symbol, exchange) rows are merged first.
 * Any error rejects and writes nothing. Resolves with the number of holdings saved.
 */
export async function saveOkSnapshot(tx: PortfolioTx, snapshot: OkSnapshot): Promise<number> {
  const holdings = mergeDuplicateHoldings(snapshot.holdings);
  await tx(async (query) => {
    await query(SYNC_INSERT_SQL, [
      snapshot.syncId,
      snapshot.profile,
      snapshot.broker,
      snapshot.syncedAt,
      "ok",
      holdings.length,
    ]);
    for (let start = 0; start < holdings.length; start += HOLDING_CHUNK_ROWS) {
      const built = buildHoldingInsert(
        snapshot.syncId,
        snapshot.profile,
        snapshot.broker,
        holdings.slice(start, start + HOLDING_CHUNK_ROWS),
      );
      await query(built.text, built.values);
    }
  });
  return holdings.length;
}

function toIso(value: unknown): string | null {
  const date = value instanceof Date ? value : typeof value === "string" ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

function optionalNumber(value: unknown): number | null {
  return value === null || value === undefined ? null : Number(value);
}

function toPublicHolding(row: Record<string, unknown>): PublicHolding {
  return {
    symbol: String(row.symbol),
    isin: row.isin === null || row.isin === undefined || row.isin === "" ? null : String(row.isin),
    quantity: Number(row.quantity),
    averagePrice: Number(row.average_price),
    lastPrice: Number(row.last_price),
    pnl: Number(row.pnl),
    dayChange: optionalNumber(row.day_change),
    dayChangePct: optionalNumber(row.day_change_pct),
  };
}

/** The latest ok snapshot for a profile and broker, or an empty view when none is stored. */
export async function loadLatestSnapshot(query: QueryFn, profile: string, broker: BrokerId): Promise<SnapshotView> {
  const latest = await query(LATEST_SYNC_SQL, [profile, broker]);
  const row = latest.rows[0];
  if (!row) return { holdings: [], syncedAt: null, broker: null };

  const holdings = await query(SNAPSHOT_HOLDINGS_SQL, [row.sync_id]);
  return {
    holdings: holdings.rows.map(toPublicHolding),
    syncedAt: toIso(row.synced_at),
    broker,
  };
}
