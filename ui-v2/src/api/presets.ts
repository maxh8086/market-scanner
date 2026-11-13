/** Client for /api/presets. Shape mirrors the server presets endpoints. */

import type { FilterState } from "../filters/filterState";
import { apiGet, CSRF_HEADER, getCsrfToken, invalidateCsrfToken } from "./session";

export interface Preset {
  preset_id: string;
  name: string;
  filters: FilterState;
  created_at: string;
  updated_at: string;
}

export interface ListPresetsOptions {
  signal?: AbortSignal;
}

/** Failure from the presets API: a non-OK status, a network error or a bad body. */
export class PresetsError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "PresetsError";
    this.status = status;
  }
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

interface FailureBody {
  /** The server's error field, or a generic message when the body has none. */
  message: string;
  /** The server's error field alone, or undefined when the body has none. */
  code: string | undefined;
}

async function readFailure(response: Response): Promise<FailureBody> {
  try {
    const body = (await response.json()) as { error?: unknown };
    if (typeof body.error === "string" && body.error.length > 0) {
      return { message: body.error, code: body.error };
    }
  } catch {
    // Body is not JSON; fall through to the generic message.
  }
  return { message: `Request failed with status ${response.status}.`, code: undefined };
}

/** Error codes the CSRF gate returns when a write needs a fresh session or token. */
const GATE_RETRY_CODES = new Set(["session_required", "csrf_required"]);

/**
 * Sends one request. A write awaits the CSRF token promise it was given, so a retry can pass a fresh one.
 * A failure to start the session is reported as a network error.
 */
async function dispatch(url: string, init: RequestInit, tokenPromise: Promise<string> | null): Promise<Response> {
  let request: RequestInit = init;
  if (tokenPromise !== null) {
    let csrfToken: string;
    try {
      csrfToken = await tokenPromise;
    } catch {
      throw new PresetsError("Could not reach the presets service.", null);
    }
    request = {
      ...init,
      headers: { ...(init.headers as Record<string, string> | undefined), [CSRF_HEADER]: csrfToken },
    };
  }
  try {
    // A GET (no token) goes through apiGet for the session cookie and one retry; writes keep the plain fetch.
    return tokenPromise === null ? await apiGet(url, init) : await fetch(url, request);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new PresetsError("Could not reach the presets service.", null);
  }
}

async function send(url: string, init: RequestInit): Promise<Response> {
  const isWrite = (init.method ?? "GET") !== "GET";
  let tokenPromise: Promise<string> | null = isWrite ? getCsrfToken() : null;
  let response = await dispatch(url, init, tokenPromise);
  if (response.ok) {
    return response;
  }
  let failure = await readFailure(response);
  // A gate rejection means the cached session or token is stale. A write retries exactly once.
  if (
    tokenPromise !== null &&
    (response.status === 401 || response.status === 403) &&
    failure.code !== undefined &&
    GATE_RETRY_CODES.has(failure.code)
  ) {
    invalidateCsrfToken(tokenPromise);
    tokenPromise = getCsrfToken();
    response = await dispatch(url, init, tokenPromise);
    if (response.ok) {
      return response;
    }
    failure = await readFailure(response);
  }
  throw new PresetsError(failure.message, response.status);
}

function isPreset(value: unknown): value is Preset {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const preset = value as Partial<Preset>;
  return typeof preset.preset_id === "string" && typeof preset.name === "string";
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new PresetsError("The presets response was not valid JSON.", response.status);
  }
}

export async function listPresets(options: ListPresetsOptions = {}): Promise<Preset[]> {
  const response = await send("/api/presets", {
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  const body = (await readJson(response)) as { presets?: unknown } | null;
  if (typeof body !== "object" || body === null || !Array.isArray(body.presets) || !body.presets.every(isPreset)) {
    throw new PresetsError("The presets response had an unexpected shape.", response.status);
  }
  return body.presets;
}

export async function createPreset(name: string, filters: FilterState): Promise<Preset> {
  const response = await send("/api/presets", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ name, filters }),
  });
  const body = await readJson(response);
  if (!isPreset(body)) {
    throw new PresetsError("The presets response had an unexpected shape.", response.status);
  }
  return body;
}

export async function deletePreset(presetId: string): Promise<void> {
  await send(`/api/presets/${encodeURIComponent(presetId)}`, { method: "DELETE" });
}
