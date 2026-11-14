import { readFileSync } from "node:fs";

/**
 * Client for the ui's internal broker API (POST and GET under /internal/broker/...). Same bearer-token pattern as
 * secretsClient.ts: the token file is read on every call. Transport failures and timeouts come back as
 * status 0, and nothing (token, request body or response body) is ever logged or thrown.
 */

export type UiMethod = "GET" | "POST";

export interface UiResponse {
  status: number;
  body: unknown;
}

export interface UiClient {
  request(method: UiMethod, path: string, body?: unknown): Promise<UiResponse>;
}

export interface UiClientOptions {
  tokenFile: string;
  baseUrl: string;
  fetch?: typeof fetch;
  readText?: (path: string) => string;
}

const REQUEST_TIMEOUT_MS = 5_000;

export function createUiClient(opts: UiClientOptions): UiClient {
  const doFetch: typeof fetch = opts.fetch ?? ((url, init) => fetch(url, init));
  const readText = opts.readText ?? ((path: string) => readFileSync(path, "utf-8"));
  const baseUrl = opts.baseUrl.replace(/\/+$/, "");

  function readToken(): string {
    try {
      return readText(opts.tokenFile).trim();
    } catch {
      return "";
    }
  }

  return {
    async request(method: UiMethod, path: string, body?: unknown): Promise<UiResponse> {
      const token = readToken();
      if (!token) return { status: 0, body: null };

      const headers: Record<string, string> = { Authorization: `Bearer ${token}`, Accept: "application/json" };
      const init: RequestInit = { method, headers, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) };
      if (body !== undefined) {
        headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(body);
      }

      let res: Response;
      try {
        res = await doFetch(`${baseUrl}${path}`, init);
      } catch {
        return { status: 0, body: null };
      }

      let parsed: unknown = null;
      try {
        parsed = await res.json();
      } catch {
        parsed = null;
      }
      return { status: res.status, body: parsed };
    },
  };
}
