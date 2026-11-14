import { CronExpressionParser } from "cron-parser";

/**
 * Pure due-source rules for GET /internal/due (the watchdog poll). Same slot rule as the Python
 * due_sources (scanner/collect/scheduler.py), plus the retry gap, open requests and host cooldowns.
 * No database, clock or file access here: the route injects every input.
 *
 * Reasons: `slot` (latest missed slot is under 5 min old), `catchup` (older missed slot), `request`
 * (an open collector_requests row). `queue` and `stale` are never returned.
 */

export const DUE_TZ = "Asia/Kolkata";
const SLOT_FRESH_MS = 5 * 60_000;
const RETRY_GAP_MS = 15 * 60_000;
const IST_OFFSET_MS = (5 * 60 + 30) * 60_000;
const GAP_STATUSES: ReadonlySet<string> = new Set(["failed", "skipped", "running"]);
const CONNECTION_CODES: ReadonlySet<string> = new Set(["ECONNREFUSED", "ENOTFOUND", "ETIMEDOUT", "ECONNRESET"]);
const PRIORITY: readonly string[] = ["index_eod", "candles_eod"];

export type DueReason = "slot" | "catchup" | "request";

export interface ServiceEntry {
  service: string;
  host?: string;
}

export interface ServicesFile {
  sources: Record<string, ServiceEntry>;
}

export interface SettingRow {
  source: string;
  mode: string;
  cron: string | null;
}

export interface AttemptInput {
  startedAt: Date;
  status: string;
}

export interface DueInputs {
  settings: SettingRow[];
  /** Source -> started_at of its latest ok run. */
  lastOk: Map<string, Date>;
  /** Source -> latest attempt of any status. */
  lastAttempt: Map<string, AttemptInput>;
  /** Host -> cooldown_until. */
  cooldowns: Map<string, Date>;
  /** Source -> id of one open (unclaimed) request. */
  requests: Map<string, string>;
}

export interface ComputeDueInput extends DueInputs {
  now: Date;
  services: ServicesFile;
}

export interface DueSource {
  name: string;
  service: string;
  reason: DueReason;
  request_id: string | null;
  order: number;
}

export interface DueResult {
  sources: DueSource[];
  /** Sources whose cron could not be parsed. They are not due; the route logs a fixed message. */
  skipped: string[];
}

/** Raw rows as the five queries return them (driver values: Date or string for timestamps). */
export interface DueRawRows {
  settings: Array<Record<string, unknown>>;
  lastOk: Array<Record<string, unknown>>;
  lastAttempt: Array<Record<string, unknown>>;
  requests: Array<Record<string, unknown>>;
  cooldowns: Array<Record<string, unknown>>;
}

export interface DueQueries {
  settings: string;
  lastOk: string;
  lastAttempt: string;
  requests: string;
  cooldowns: string;
}

/** The five parameter-free statements the route runs. */
export function buildDueQueries(): DueQueries {
  return {
    settings: "SELECT source, mode, cron FROM collector_settings",
    lastOk:
      "SELECT DISTINCT ON (source) source, started_at FROM collector_runs WHERE status = 'ok' ORDER BY source, started_at DESC",
    lastAttempt:
      "SELECT DISTINCT ON (source) source, started_at, status FROM collector_runs ORDER BY source, started_at DESC",
    requests: "SELECT id, source FROM collector_requests WHERE claimed_at IS NULL",
    cooldowns: "SELECT host, cooldown_until FROM source_cooldown",
  };
}

function asDate(value: unknown): Date | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string" && typeof value !== "number" && !(value instanceof Date)) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Maps the raw query rows onto the injected inputs. Rows with unusable values are dropped. */
export function mapDueRows(raw: DueRawRows): DueInputs {
  const settings: SettingRow[] = [];
  for (const row of raw.settings) {
    if (typeof row.source !== "string" || typeof row.mode !== "string") continue;
    settings.push({
      source: row.source,
      mode: row.mode,
      cron: typeof row.cron === "string" ? row.cron : null,
    });
  }

  const lastOk = new Map<string, Date>();
  for (const row of raw.lastOk) {
    const at = asDate(row.started_at);
    if (typeof row.source === "string" && at) lastOk.set(row.source, at);
  }

  const lastAttempt = new Map<string, AttemptInput>();
  for (const row of raw.lastAttempt) {
    const at = asDate(row.started_at);
    if (typeof row.source === "string" && at && typeof row.status === "string") {
      lastAttempt.set(row.source, { startedAt: at, status: row.status });
    }
  }

  const cooldowns = new Map<string, Date>();
  for (const row of raw.cooldowns) {
    const until = asDate(row.cooldown_until);
    if (typeof row.host === "string" && until) cooldowns.set(row.host, until);
  }

  const requests = new Map<string, string>();
  for (const row of raw.requests) {
    if (typeof row.source === "string" && row.id !== null && row.id !== undefined && !requests.has(row.source)) {
      requests.set(row.source, String(row.id));
    }
  }

  return { settings, lastOk, lastAttempt, cooldowns, requests };
}

/**
 * Parses the services file text. Throws on bad JSON or shape; the route turns that into a fixed 500.
 * Shape: {"sources": {"<name>": {"service": "<compose service>", "host": "<cooldown host, optional>"}}}
 */
export function parseServicesFile(text: string): ServicesFile {
  const parsed: unknown = JSON.parse(text);
  if (!isRecord(parsed) || !isRecord(parsed.sources)) {
    throw new Error("collector services file: bad shape");
  }
  const sources: Record<string, ServiceEntry> = {};
  for (const [name, value] of Object.entries(parsed.sources)) {
    if (!isRecord(value) || typeof value.service !== "string" || value.service === "") {
      throw new Error("collector services file: bad source entry");
    }
    if (value.host !== undefined && typeof value.host !== "string") {
      throw new Error("collector services file: bad host");
    }
    sources[name] = value.host === undefined ? { service: value.service } : { service: value.service, host: value.host };
  }
  return { sources };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** True for errors that mean the database is unreachable (503), not a failed query (500). */
export function isConnectionError(err: unknown): boolean {
  const code = isRecord(err) ? err.code : undefined;
  if (typeof code === "string" && (code.startsWith("08") || CONNECTION_CODES.has(code))) return true;
  return err instanceof Error && err.message.includes("Connection terminated");
}

/** The ISO instant in IST (+05:30), used for generated_at. */
export function toIstIso(instant: Date): string {
  return new Date(instant.getTime() + IST_OFFSET_MS).toISOString().slice(0, -1) + "+05:30";
}

/** IST calendar date (YYYY-MM-DD) of an instant. */
function istDate(instant: Date): string {
  return new Date(instant.getTime() + IST_OFFSET_MS).toISOString().slice(0, 10);
}

/**
 * Latest cron slot at or before now, in Asia/Kolkata. cron-parser's prev() is strictly before its
 * currentDate, so the search starts 1 ms after now: a slot exactly at now counts as the latest.
 * Throws on an invalid cron expression.
 */
function latestSlotAtOrBefore(cron: string, now: Date): Date {
  const expression = CronExpressionParser.parse(cron, {
    currentDate: new Date(now.getTime() + 1),
    tz: DUE_TZ,
  });
  return expression.prev().toDate();
}

function rank(name: string): number {
  const index = PRIORITY.indexOf(name);
  return index === -1 ? PRIORITY.length : index;
}

/**
 * The sources due now, in poll order: index_eod, candles_eod, then the rest by name ascending.
 * An invalid cron skips that source (listed in `skipped`); it never throws.
 */
export function computeDue(input: ComputeDueInput): DueResult {
  const { now, services } = input;
  const nowMs = now.getTime();

  const settingBySource = new Map<string, SettingRow>();
  for (const row of input.settings) {
    if (!settingBySource.has(row.source)) settingBySource.set(row.source, row);
  }

  const candidates: Array<Omit<DueSource, "order">> = [];
  const skipped: string[] = [];

  for (const name of Object.keys(services.sources)) {
    const entry = services.sources[name];
    if (!entry) continue;

    // A host in cooldown omits the source, even with an open request.
    const cooldownUntil = entry.host ? input.cooldowns.get(entry.host) : undefined;
    if (cooldownUntil !== undefined && cooldownUntil.getTime() > nowMs) continue;

    // An open request bypasses the slot rule and the retry gap.
    const requestId = input.requests.get(name);
    if (requestId !== undefined) {
      candidates.push({ name, service: entry.service, reason: "request", request_id: requestId });
      continue;
    }

    const setting = settingBySource.get(name);
    if (!setting || setting.mode !== "scheduled" || !setting.cron || setting.cron.trim() === "") continue;

    let slot: Date;
    try {
      slot = latestSlotAtOrBefore(setting.cron, now);
    } catch {
      skipped.push(name);
      continue;
    }

    // Retry gap: a failed, skipped or running last attempt blocks re-run for 15 min,
    // unless a newer slot has arrived since that attempt started.
    const attempt = input.lastAttempt.get(name);
    if (
      attempt &&
      GAP_STATUSES.has(attempt.status) &&
      attempt.startedAt.getTime() + RETRY_GAP_MS > nowMs &&
      slot.getTime() <= attempt.startedAt.getTime()
    ) {
      continue;
    }

    // Slot rule (same as scanner/collect/scheduler.py due_sources).
    const lastOk = input.lastOk.get(name);
    const due =
      lastOk === undefined ? istDate(slot) >= istDate(now) : slot.getTime() > lastOk.getTime();
    if (!due) continue;

    const reason: DueReason = nowMs - slot.getTime() < SLOT_FRESH_MS ? "slot" : "catchup";
    candidates.push({ name, service: entry.service, reason, request_id: null });
  }

  candidates.sort((a, b) => rank(a.name) - rank(b.name) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return {
    sources: candidates.map((candidate, index) => ({ ...candidate, order: index + 1 })),
    skipped,
  };
}
