import { describe, expect, it, vi } from "vitest";
import { createUiClient } from "./uiClient.js";

const TOKEN = "tok-SENTINEL-UI-1234";

type FetchImpl = (url: string, init: RequestInit) => Promise<Response>;

function make(fetchImpl: FetchImpl, readText: (path: string) => string = () => `${TOKEN}\n`) {
  const fetchFn = vi.fn(fetchImpl);
  const client = createUiClient({
    tokenFile: "/run/app-keys/server_secrets_token",
    baseUrl: "http://ui:8080/",
    fetch: fetchFn as unknown as typeof fetch,
    readText,
  });
  return { client, fetchFn };
}

function jsonRes(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("createUiClient", () => {
  it("sends a GET with the bearer token to the base URL without a trailing slash", async () => {
    const { client, fetchFn } = make(async () => jsonRes({ connected: true }));

    const res = await client.request("GET", "/internal/broker/kite/status?profile_id=default");

    expect(res).toEqual({ status: 200, body: { connected: true } });
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://ui:8080/internal/broker/kite/status?profile_id=default");
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${TOKEN}`);
    expect(init.body).toBeUndefined();
    expect(init.signal).toBeDefined();
  });

  it("sends a JSON body with a content type on POST", async () => {
    const { client, fetchFn } = make(async () => jsonRes({ url: "https://kite.example/login" }));

    const res = await client.request("POST", "/internal/broker/kite/login-url", { profile_id: "default" });

    expect(res.status).toBe(200);
    const [, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ profile_id: "default" }));
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("returns the status with a null body when the response is not JSON", async () => {
    const { client } = make(async () => new Response("<html>oops</html>", { status: 500 }));
    expect(await client.request("GET", "/x")).toEqual({ status: 500, body: null });
  });

  it("returns status 0 and a null body on a transport error, without echoing it", async () => {
    const { client } = make(async () => {
      throw new Error(`connect refused with ${TOKEN}`);
    });

    const res = await client.request("GET", "/x");
    expect(res).toEqual({ status: 0, body: null });
    expect(JSON.stringify(res)).not.toContain(TOKEN);
  });

  it("does not call fetch when the token file is blank or unreadable", async () => {
    const blank = make(async () => jsonRes({}), () => "  \n");
    expect(await blank.client.request("GET", "/x")).toEqual({ status: 0, body: null });
    expect(blank.fetchFn).not.toHaveBeenCalled();

    const missing = make(async () => jsonRes({}), () => {
      throw new Error("ENOENT");
    });
    expect(await missing.client.request("GET", "/x")).toEqual({ status: 0, body: null });
    expect(missing.fetchFn).not.toHaveBeenCalled();
  });

  it("reads the token file on every request", async () => {
    let token = "tok-A";
    const { client, fetchFn } = make(async () => jsonRes({}), () => token);

    await client.request("GET", "/x");
    token = "tok-B";
    await client.request("GET", "/x");

    const [, second] = fetchFn.mock.calls[1] as unknown as [string, RequestInit];
    expect((second.headers as Record<string, string>).Authorization).toBe("Bearer tok-B");
  });
});
