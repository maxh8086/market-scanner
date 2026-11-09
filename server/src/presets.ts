/**
 * Pure validation and SQL builders for saved scan presets. No database access here.
 * Every user value is passed as a $N placeholder.
 */

import { isIsoDate } from "./results.js";

export interface Built {
  sql: string;
  values: unknown[];
}

export type PresetFilters = Record<string, string | number>;

export interface PresetInput {
  name: string;
  filters: PresetFilters;
}

export type ValidationResult<T> = { ok: true; value: T } | { ok: false; error: string };

export const NAME_MIN = 1;
export const NAME_MAX = 60;
export const MAX_FILTER_KEYS = 20;
export const MAX_FILTER_STRING = 200;

const ALLOWED_FILTER_KEYS: ReadonlySet<string> = new Set([
  "bucket",
  "stance",
  "search",
  "industry",
  "ltpMin",
  "ltpMax",
  "distanceMin",
  "distanceMax",
  "athFrom",
  "athTo",
]);

const DATE_KEYS: ReadonlySet<string> = new Set(["athFrom", "athTo"]);

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Length in Unicode code points, matching Postgres char_length. */
function charLength(text: string): number {
  return [...text].length;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function validateName(body: Record<string, unknown>): ValidationResult<string> {
  if (typeof body.name !== "string") {
    return { ok: false, error: "name must be a string" };
  }
  const name = body.name.trim();
  const length = charLength(name);
  if (length < NAME_MIN) {
    return { ok: false, error: "name is required" };
  }
  if (length > NAME_MAX) {
    return { ok: false, error: `name must be at most ${NAME_MAX} characters` };
  }
  return { ok: true, value: name };
}

function validateFilters(filters: unknown): ValidationResult<PresetFilters> {
  if (!isPlainObject(filters)) {
    return { ok: false, error: "filters must be an object" };
  }
  const keys = Object.keys(filters);
  if (keys.length > MAX_FILTER_KEYS) {
    return { ok: false, error: `filters may have at most ${MAX_FILTER_KEYS} keys` };
  }
  const out: PresetFilters = {};
  for (const key of keys) {
    if (!ALLOWED_FILTER_KEYS.has(key)) {
      return { ok: false, error: `Unknown filter key: ${key}` };
    }
    const value = filters[key];
    if (typeof value === "string") {
      if (charLength(value) > MAX_FILTER_STRING) {
        return { ok: false, error: `Filter ${key} must be at most ${MAX_FILTER_STRING} characters` };
      }
      if (DATE_KEYS.has(key) && !isIsoDate(value)) {
        return { ok: false, error: `Invalid ${key}` };
      }
      out[key] = value;
    } else if (typeof value === "number") {
      if (!Number.isFinite(value)) {
        return { ok: false, error: `Filter ${key} must be a finite number` };
      }
      if (DATE_KEYS.has(key)) {
        return { ok: false, error: `Invalid ${key}` };
      }
      out[key] = value;
    } else {
      return { ok: false, error: `Filter ${key} must be a string or number` };
    }
  }
  return { ok: true, value: out };
}

/** Validates a POST /api/presets body. Returns the trimmed name and cleaned filters. */
export function validatePresetInput(body: unknown): ValidationResult<PresetInput> {
  if (!isPlainObject(body)) {
    return { ok: false, error: "Body must be an object" };
  }
  const name = validateName(body);
  if (!name.ok) return name;
  const filters = validateFilters(body.filters);
  if (!filters.ok) return filters;
  return { ok: true, value: { name: name.value, filters: filters.value } };
}

export function isPresetId(id: string): boolean {
  return UUID_RE.test(id);
}

export function buildListPresetsQuery(): Built {
  return {
    sql: "SELECT preset_id, name, filters, created_at, updated_at FROM scan_presets ORDER BY name ASC, preset_id ASC",
    values: [],
  };
}

export function buildInsertPresetQuery(value: PresetInput): Built {
  return {
    sql: "INSERT INTO scan_presets (name, filters) VALUES ($1, $2::jsonb) RETURNING preset_id, name, filters, created_at, updated_at",
    values: [value.name, JSON.stringify(value.filters)],
  };
}

/** Returns a query only when the id is a UUID. Otherwise returns a validation error and no SQL. */
export function buildDeletePresetQuery(id: string): ValidationResult<Built> {
  if (!isPresetId(id)) {
    return { ok: false, error: "Invalid presetId" };
  }
  return {
    ok: true,
    value: {
      sql: "DELETE FROM scan_presets WHERE preset_id = $1 RETURNING preset_id",
      values: [id],
    },
  };
}
