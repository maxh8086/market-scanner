import { describe, expect, it, vi } from "vitest";
import { createSecretsClient, type SecretsClientOptions } from "./secretsClient.js";

const TOKEN = "tok-SENTINEL-1234";
const VALUE = "val-SENTINEL-5678";

function okResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

type FetchImpl = (url: string, init: RequestInit) => Promise<Response>;

function make(fetchImpl: FetchImpl, extra: Partial<SecretsClientOptions> = {}) {
  const warnings: string[] = [];
  const fetchFn = vi.fn(fetchImpl);
  let clock = 0;
  const client = createSecretsClient({
    tokenFile: "/run/app-keys/server_secrets_token",
    baseUrl: "http://ui:8080/",
    fetch: fetchFn as unknown as typeof fetch,
    readText: () => `${TOKEN}\n`,
    now: () => clock,
    warn: (message) => warnings.push(message),
    ...extra,
  });
  return {
    client,
    fetchFn,
    warnings,
    setClock: (ms: number) => {
      clock = ms;
    },
  };
}

const succeed: FetchImpl = async () => okResponse({ name: "upstox_analytics_token", value: VALUE });

describe("createSecretsClient", () => {
  it("sends the bearer token to the encoded internal URL and returns the value", async () => {
    const { client, fetchFn } = make(async () => okResponse({ name: "a b/c", value: VALUE }));

    expect(await client.get("a b/c")).toBe(VALUE);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://ui:8080/internal/secrets/a%20b%2Fc");
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${TOKEN}`);
    expect(init.signal).toBeDefined();
  });

  it.each([404, 401, 403, 503])("returns undefined and warns with only the status %i", async (status) => {
    const { client, warnings } = make(async () => okResponse({ name: "kite_api_key", value: VALUE }, status));

    expect(await client.get("kite_api_key")).toBeUndefined();
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain(String(status));
    expect(warnings[0]).toContain("kite_api_key");
    expect(warnings[0]).not.toContain(TOKEN);
    expect(warnings[0]).not.toContain(VALUE);
  });

  it("returns undefined on a network error and never echoes the thrown message", async () => {
    const { client, warnings } = make(async () => {
      throw new Error(`connect failed for ${TOKEN} ${VALUE}`);
    });

    await expect(client.get("kite_api_key")).resolves.toBeUndefined();
    expect(warnings.join("\n")).not.toContain(TOKEN);
    expect(warnings.join("\n")).not.toContain(VALUE);
  });

  it("returns undefined for an empty, missing or unreadable value", async () => {
    const bodies: Array<() => Promise<Response>> = [
      async () => okResponse({ name: "n", value: "" }),
      async () => okResponse({ name: "n" }),
      async () => new Response(`<html>${VALUE}</html>`, { status: 200 }),
    ];
    for (const body of bodies) {
      const { client, warnings } = make(body);
      expect(await client.get("n")).toBeUndefined();
      expect(warnings.join("\n")).not.toContain(VALUE);
    }
  });

  it("does not call fetch when the token file is missing or blank", async () => {
    const missing = make(succeed, {
      readText: () => {
        throw Object.assign(new Error("ENOENT: /run/app-keys/server_secrets_token"), { code: "ENOENT" });
      },
    });
    expect(await missing.client.get("upstox_analytics_token")).toBeUndefined();
    expect(missing.fetchFn).not.toHaveBeenCalled();
    expect(missing.warnings).toEqual(["secrets token file not configured"]);

    const blank = make(succeed, { readText: () => "  \n" });
    expect(await blank.client.get("upstox_analytics_token")).toBeUndefined();
    expect(blank.fetchFn).not.toHaveBeenCalled();
    expect(blank.warnings).toEqual(["secrets token file not configured"]);
  });

  it("caches a success for ttlMs and refetches after it", async () => {
    const { client, fetchFn, setClock } = make(succeed);

    expect(await client.get("upstox_analytics_token")).toBe(VALUE);
    expect(await client.get("upstox_analytics_token")).toBe(VALUE);
    expect(fetchFn).toHaveBeenCalledTimes(1);

    setClock(59_999);
    await client.get("upstox_analytics_token");
    expect(fetchFn).toHaveBeenCalledTimes(1);

    setClock(60_000);
    await client.get("upstox_analytics_token");
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  it("caches a failure for failTtlMs, then retries", async () => {
    const { client, fetchFn, setClock } = make(succeed);
    fetchFn.mockResolvedValueOnce(new Response("", { status: 503 }));

    expect(await client.get("upstox_analytics_token")).toBeUndefined();
    setClock(9_999);
    expect(await client.get("upstox_analytics_token")).toBeUndefined();
    expect(fetchFn).toHaveBeenCalledTimes(1);

    setClock(10_000);
    expect(await client.get("upstox_analytics_token")).toBe(VALUE);
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  it("reads the token file on every network fetch", async () => {
    let token = "tok-A";
    const { client, fetchFn, setClock } = make(succeed, { readText: () => token });

    await client.get("upstox_analytics_token");
    token = "tok-B";
    setClock(60_000);
    await client.get("upstox_analytics_token");

    expect(fetchFn).toHaveBeenCalledTimes(2);
    const [, init] = fetchFn.mock.calls[1] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-B");
  });

  it("shares one in-flight request between concurrent calls for the same name", async () => {
    const { client, fetchFn } = make(
      () => new Promise<Response>((resolve) => setTimeout(() => resolve(okResponse({ name: "n", value: VALUE })), 5)),
    );

    const results = await Promise.all([client.get("n"), client.get("n"), client.get("n")]);
    expect(results).toEqual([VALUE, VALUE, VALUE]);
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it("never rejects and keeps the token and value out of every warning", async () => {
    const failures: FetchImpl[] = [
      async () => new Response(`leaked ${TOKEN} ${VALUE}`, { status: 500 }),
      async () => new Response(`not json ${VALUE}`, { status: 200 }),
      async () => {
        throw new Error(`boom ${TOKEN}`);
      },
    ];
    const warnings: string[] = [];
    for (const impl of failures) {
      const made = make(impl);
      await expect(made.client.get("n")).resolves.toBeUndefined();
      warnings.push(...made.warnings);
    }
    expect(warnings.length).toBeGreaterThan(0);
    for (const message of warnings) {
      expect(message).not.toContain(TOKEN);
      expect(message).not.toContain(VALUE);
    }
  });
});
