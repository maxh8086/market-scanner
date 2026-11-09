/** Client for /api/presets. Shape mirrors the server presets endpoints. */

import type { FilterState } from "../filters/filterState";

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

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: unknown };
    if (typeof body.error === "string" && body.error.length > 0) {
      return body.error;
    }
  } catch {
    // Body is not JSON; fall through to the generic message.
  }
  return `Request failed with status ${response.status}.`;
}

async function send(url: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new PresetsError("Could not reach the presets service.", null);
  }
  if (!response.ok) {
    throw new PresetsError(await readErrorMessage(response), response.status);
  }
  return response;
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
