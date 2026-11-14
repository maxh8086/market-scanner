import { readFileSync } from "node:fs";

/**
 * Client for the UI's internal secrets API. The server asks the UI for one app secret per call
 * with a bearer token read from a file on every network fetch, the same pattern as
 * scanner/service_client.py. Errors and warnings never include the token, the response body or the value.
 */
export type SecretsClientOptions = {
  tokenFile: string;
  baseUrl: string;
  fetch?: typeof fetch;
  readText?: (path: string) => string;
  now?: () => number;
  ttlMs?: number;
  failTtlMs?: number;
  warn?: (msg: string) => void;
};

export interface SecretsClient {
  get(name: string): Promise<string | undefined>;
}

const REQUEST_TIMEOUT_MS = 5_000;

type CacheEntry = { value: string | undefined; expiresAt: number };

export function createSecretsClient(opts: SecretsClientOptions): SecretsClient {
  const doFetch: typeof fetch = opts.fetch ?? ((url, init) => fetch(url, init));
  const readText = opts.readText ?? ((path: string) => readFileSync(path, "utf-8"));
  const now = opts.now ?? (() => Date.now());
  const ttlMs = opts.ttlMs ?? 60_000;
  const failTtlMs = opts.failTtlMs ?? 10_000;
  const warn = opts.warn ?? (() => {});
  const baseUrl = opts.baseUrl.replace(/\/+$/, "");

  const cache = new Map<string, CacheEntry>();
  const inflight = new Map<string, Promise<string | undefined>>();

  // Failures (missing token, transport error, non-200 such as 404 "not stored", bad body) are cached as
  // undefined for failTtlMs (10 s) and warned about the same way, so a missing secret is not re-fetched on every call.
  function remember(name: string, value: string | undefined, ttl: number): void {
    cache.set(name, { value, expiresAt: now() + ttl });
  }

  function readToken(): string | undefined {
    let text = "";
    try {
      text = readText(opts.tokenFile).trim();
    } catch {
      text = "";
    }
    if (!text) {
      warn("secrets token file not configured");
      return undefined;
    }
    return text;
  }

  async function load(name: string): Promise<string | undefined> {
    const token = readToken();
    if (!token) {
      remember(name, undefined, failTtlMs);
      return undefined;
    }

    const url = `${baseUrl}/internal/secrets/${encodeURIComponent(name)}`;
    let res: Response;
    try {
      res = await doFetch(url, {
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
    } catch {
      warn(`secrets API request failed for ${name}`);
      remember(name, undefined, failTtlMs);
      return undefined;
    }

    if (res.status !== 200) {
      warn(`secrets API returned HTTP ${res.status} for ${name}`);
      remember(name, undefined, failTtlMs);
      return undefined;
    }

    let value: unknown;
    try {
      const body: unknown = await res.json();
      value = body && typeof body === "object" ? (body as { value?: unknown }).value : undefined;
    } catch {
      warn(`secrets API returned an unreadable response for ${name}`);
      remember(name, undefined, failTtlMs);
      return undefined;
    }

    if (typeof value !== "string" || value.length === 0) {
      warn(`secrets API returned no value for ${name}`);
      remember(name, undefined, failTtlMs);
      return undefined;
    }

    remember(name, value, ttlMs);
    return value;
  }

  return {
    async get(name: string): Promise<string | undefined> {
      const hit = cache.get(name);
      if (hit && hit.expiresAt > now()) return hit.value;

      const pending = inflight.get(name);
      if (pending) return pending;

      const request = load(name).finally(() => {
        inflight.delete(name);
      });
      inflight.set(name, request);
      return request;
    },
  };
}
