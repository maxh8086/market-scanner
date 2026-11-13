/**
 * Browser session for write requests. GET /api/session sets an HttpOnly session cookie and returns
 * the CSRF token that every POST, PUT and DELETE under /api/ must send in CSRF_HEADER.
 */

export const SESSION_URL = "/api/session";
export const CSRF_HEADER = "X-CSRF-Token";

const SESSION_ERROR = "Could not start a session.";

let csrfPromise: Promise<string> | null = null;

async function fetchCsrfToken(): Promise<string> {
  const response = await fetch(SESSION_URL, { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(SESSION_ERROR);
  }
  const body = (await response.json()) as { csrfToken?: unknown };
  if (typeof body.csrfToken !== "string" || body.csrfToken.length === 0) {
    throw new Error(SESSION_ERROR);
  }
  return body.csrfToken;
}

/** Returns the CSRF token for this browser session. The first call fetches it; later calls reuse it. */
export function getCsrfToken(): Promise<string> {
  if (csrfPromise === null) {
    const pending: Promise<string> = fetchCsrfToken().catch((error: unknown) => {
      // Drop the failed attempt so the next write tries to start a session again.
      if (csrfPromise === pending) {
        csrfPromise = null;
      }
      throw error;
    });
    csrfPromise = pending;
  }
  return csrfPromise;
}

/** Forgets the cached token only if it is still the one that was rejected. A newer token is left alone. */
export function invalidateCsrfToken(stale: Promise<string>): void {
  if (csrfPromise === stale) {
    csrfPromise = null;
  }
}

const SESSION_REQUIRED = "session_required";

/** True when the response is a 401 with error session_required. Reads a clone, so the caller can still read the body. */
async function isSessionRequired(response: Response): Promise<boolean> {
  if (response.status !== 401) {
    return false;
  }
  try {
    const body = (await response.clone().json()) as { error?: unknown };
    return body.error === SESSION_REQUIRED;
  } catch {
    return false;
  }
}

/**
 * GET under /api/. Starts a session first so the read carries the session cookie. A 401 session_required
 * drops the cached session, starts a new one and retries the read once. A second failure goes to the caller.
 */
export async function apiGet(url: string, init: RequestInit = {}): Promise<Response> {
  let tokenPromise = getCsrfToken();
  await tokenPromise;
  let response = await fetch(url, { credentials: "same-origin", ...init });
  if (await isSessionRequired(response)) {
    invalidateCsrfToken(tokenPromise);
    tokenPromise = getCsrfToken();
    await tokenPromise;
    response = await fetch(url, { credentials: "same-origin", ...init });
  }
  return response;
}

/** Test helper: forgets the cached token so the next write fetches a new session. */
export function resetCsrfTokenForTests(): void {
  csrfPromise = null;
}
