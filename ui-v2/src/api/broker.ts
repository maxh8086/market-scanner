/**
 * Client for the broker login and portfolio sync routes: GET /api/broker/:broker/status,
 * POST /api/broker/:broker/login-url and POST /api/holdings/sync. The browser never sees a broker token.
 */

import { apiGet, CSRF_HEADER, getCsrfToken, invalidateCsrfToken } from "./session";

export type BrokerName = "kite" | "upstox";

/** The brokers the UI can log in to, in the order the panel's tabs show them. */
export const BROKER_NAMES: readonly BrokerName[] = ["kite", "upstox"];

const BROKER_LABELS: Record<BrokerName, string> = { kite: "Kite", upstox: "Upstox" };

/** The name a user reads for a broker, e.g. "Kite" or "Upstox". */
export function brokerLabel(broker: BrokerName): string {
  return BROKER_LABELS[broker];
}

/** Whether a value is one of the supported broker names. */
export function isBrokerName(value: unknown): value is BrokerName {
  return value === "kite" || value === "upstox";
}

export const DEFAULT_PROFILE = "default";
/** Message for a sync that the server refused because no valid broker token is stored. */
export const LOGIN_REQUIRED_MESSAGE = "login required";

const UNREACHABLE_MESSAGE = "Could not reach the broker service.";
const GATE_RETRY_CODES = new Set(["session_required", "csrf_required"]);

/** Failure from a broker route: a network error, an unexpected status or a bad body. */
export class BrokerError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "BrokerError";
    this.status = status;
  }
}

export interface BrokerStatus {
  connected: boolean;
  /** ISO instant the stored token expires, or null when no token is stored. */
  expiresAt: string | null;
}

export interface SyncResult {
  /** ISO instant of the snapshot that was written. */
  syncedAt: string;
  broker: BrokerName;
  rowCount: number;
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

async function readJsonBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new BrokerError("The broker response was not valid JSON.", response.status);
  }
}

/** The error code of a failed response, read from a clone so the caller can still read the body. */
async function errorCode(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.clone().json()) as { error?: unknown };
    return typeof body.error === "string" ? body.error : undefined;
  } catch {
    return undefined;
  }
}

async function dispatchPost(
  url: string,
  body: unknown,
  tokenPromise: Promise<string>,
  signal?: AbortSignal,
): Promise<Response> {
  let csrfToken: string;
  try {
    csrfToken = await tokenPromise;
  } catch {
    throw new BrokerError(UNREACHABLE_MESSAGE, null);
  }
  try {
    return await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        [CSRF_HEADER]: csrfToken,
      },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new BrokerError(UNREACHABLE_MESSAGE, null);
  }
}

/**
 * POST with the CSRF token. A gate rejection (401 session_required or 403 csrf_required) drops the cached
 * token and retries the POST exactly once with a fresh one. Any other response goes back to the caller.
 */
async function sendPost(url: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  let tokenPromise = getCsrfToken();
  let response = await dispatchPost(url, body, tokenPromise, signal);
  if (response.status === 401 || response.status === 403) {
    const code = await errorCode(response);
    if (code !== undefined && GATE_RETRY_CODES.has(code)) {
      invalidateCsrfToken(tokenPromise);
      tokenPromise = getCsrfToken();
      response = await dispatchPost(url, body, tokenPromise, signal);
    }
  }
  return response;
}

function isBrokerStatus(value: unknown): value is BrokerStatus {
  if (typeof value !== "object" || value === null) return false;
  const { connected, expiresAt } = value as { connected?: unknown; expiresAt?: unknown };
  return typeof connected === "boolean" && (expiresAt === null || typeof expiresAt === "string");
}

/** Whether the broker has a usable (unexpired) token for the profile. */
export async function fetchBrokerStatus(broker: BrokerName, profile: string = DEFAULT_PROFILE): Promise<BrokerStatus> {
  let response: Response;
  try {
    response = await apiGet(`/api/broker/${broker}/status?profile=${encodeURIComponent(profile)}`, {
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new BrokerError(UNREACHABLE_MESSAGE, null);
  }
  if (!response.ok) {
    throw new BrokerError(await readErrorMessage(response), response.status);
  }
  const body = await readJsonBody(response);
  if (!isBrokerStatus(body)) {
    throw new BrokerError("The broker status response had an unexpected shape.", response.status);
  }
  return body;
}

function isHttpsUrl(value: string): boolean {
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

/** The broker's login page URL for the profile. The server holds the state value; the browser only gets the URL. */
export async function requestLoginUrl(broker: BrokerName, profile: string = DEFAULT_PROFILE): Promise<string> {
  const response = await sendPost(`/api/broker/${broker}/login-url`, { profile });
  if (!response.ok) {
    throw new BrokerError(await readErrorMessage(response), response.status);
  }
  const body = await readJsonBody(response);
  const url = typeof body === "object" && body !== null ? (body as { url?: unknown }).url : undefined;
  if (typeof url !== "string" || !isHttpsUrl(url)) {
    throw new BrokerError("The login response had an unexpected shape.", response.status);
  }
  return url;
}

function isSyncResult(value: unknown): value is SyncResult {
  if (typeof value !== "object" || value === null) return false;
  const { syncedAt, broker, rowCount } = value as { syncedAt?: unknown; broker?: unknown; rowCount?: unknown };
  return typeof syncedAt === "string" && isBrokerName(broker) && typeof rowCount === "number";
}

/**
 * Pulls the portfolio from the broker into the stored snapshot. A 401 means no valid login: the message is
 * "login required". A failed sync leaves the stored snapshot unchanged on the server.
 */
export async function syncPortfolio(broker: BrokerName, profile: string = DEFAULT_PROFILE): Promise<SyncResult> {
  const response = await sendPost("/api/holdings/sync", { profile, broker });
  if (!response.ok) {
    if (response.status === 401) {
      throw new BrokerError(LOGIN_REQUIRED_MESSAGE, 401);
    }
    throw new BrokerError(await readErrorMessage(response), response.status);
  }
  const body = await readJsonBody(response);
  if (!isSyncResult(body)) {
    throw new BrokerError("The sync response had an unexpected shape.", response.status);
  }
  return body;
}

/** Sends the browser to the broker's login page. The URL has already been checked by requestLoginUrl. */
export function redirectToBrokerLogin(url: string): void {
  window.location.assign(url);
}
