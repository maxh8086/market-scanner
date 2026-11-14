/** Client for GET /api/collector/status. Shape mirrors server/src/collectorStatus.ts. */

import { apiGet } from "./session";

export interface CollectorStatus {
  paused: boolean;
  since: string | null;
}

export interface FetchCollectorStatusOptions {
  signal?: AbortSignal;
}

/** Failure from the collector status API: a non-OK status, a network error or a bad body. */
export class CollectorStatusError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "CollectorStatusError";
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

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toCollectorStatus(body: unknown): CollectorStatus | null {
  if (!isPlainObject(body) || !isPlainObject(body.collector)) {
    return null;
  }
  const { paused, since } = body.collector;
  if (typeof paused !== "boolean") {
    return null;
  }
  if (since !== null && typeof since !== "string") {
    return null;
  }
  return { paused, since };
}

export async function fetchCollectorStatus(options: FetchCollectorStatusOptions = {}): Promise<CollectorStatus> {
  let response: Response;
  try {
    response = await apiGet("/api/collector/status", {
      headers: { Accept: "application/json" },
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new CollectorStatusError("Could not reach the collector status service.", null);
  }

  if (!response.ok) {
    throw new CollectorStatusError(await readErrorMessage(response), response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new CollectorStatusError("The collector status response was not valid JSON.", response.status);
  }

  const status = toCollectorStatus(body);
  if (status === null) {
    throw new CollectorStatusError("The collector status response had an unexpected shape.", response.status);
  }
  return status;
}
