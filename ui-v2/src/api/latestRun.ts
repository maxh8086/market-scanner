/** Client for GET /api/runs/latest. Shape mirrors the server route that returns the current run. */

import { apiGet } from "./session";

export interface LatestRun {
  runId: string;
  runDate: string;
}

/** Failure from the latest-run API: no current run (404), a network error or a bad body. */
export class LatestRunError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "LatestRunError";
    this.status = status;
  }
}

export interface FetchLatestRunOptions {
  signal?: AbortSignal;
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

function isLatestRun(body: unknown): body is LatestRun {
  if (typeof body !== "object" || body === null) {
    return false;
  }
  const run = body as Partial<LatestRun>;
  return typeof run.runId === "string" && run.runId.length > 0 && typeof run.runDate === "string";
}

export async function fetchLatestRun(options: FetchLatestRunOptions = {}): Promise<LatestRun> {
  let response: Response;
  try {
    response = await apiGet("/api/runs/latest", {
      headers: { Accept: "application/json" },
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new LatestRunError("Could not reach the run service.", null);
  }

  if (response.status === 404) {
    throw new LatestRunError("No current run", 404);
  }

  if (!response.ok) {
    throw new LatestRunError(await readErrorMessage(response), response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new LatestRunError("The latest run response was not valid JSON.", response.status);
  }

  if (!isLatestRun(body)) {
    throw new LatestRunError("The latest run response had an unexpected shape.", response.status);
  }
  return body;
}
