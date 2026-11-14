import { describe, expect, it, vi } from "vitest";
import { readKiteAccessToken, readKiteApiKey, readUpstoxAccessToken, type SecretReader } from "./credentials.js";

function fakeSecrets(values: Record<string, string | undefined>) {
  const get = vi.fn(async (name: string): Promise<string | undefined> => values[name]);
  const secrets: SecretReader = { get };
  return { secrets, get };
}

describe("readKiteApiKey", () => {
  it("reads the per-profile api key when it is stored", async () => {
    const { secrets, get } = fakeSecrets({ broker_default_kite_api_key: "own-key", kite_api_key: "global-key" });
    expect(await readKiteApiKey(secrets, "default")).toBe("own-key");
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("falls back to the global kite_api_key for the default profile only", async () => {
    const { secrets } = fakeSecrets({ kite_api_key: "global-key" });
    expect(await readKiteApiKey(secrets, "default")).toBe("global-key");
  });

  it("never falls back to the global key for a named profile", async () => {
    const { secrets, get } = fakeSecrets({ kite_api_key: "global-key" });
    expect(await readKiteApiKey(secrets, "main")).toBeUndefined();
    expect(get).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith("broker_main_kite_api_key");
  });

  it("returns undefined when nothing is stored", async () => {
    const { secrets } = fakeSecrets({});
    expect(await readKiteApiKey(secrets, "default")).toBeUndefined();
  });
});

describe("readUpstoxAccessToken", () => {
  it("reads the per-profile upstox access token name", async () => {
    const { secrets, get } = fakeSecrets({ broker_main_upstox_access_token: "tok" });
    expect(await readUpstoxAccessToken(secrets, "main")).toBe("tok");
    expect(get).toHaveBeenCalledWith("broker_main_upstox_access_token");
  });

  it("never falls back to a global or kite name, even for the default profile", async () => {
    const { secrets, get } = fakeSecrets({ upstox_access_token: "tok", broker_default_kite_access_token: "k" });
    expect(await readUpstoxAccessToken(secrets, "default")).toBeUndefined();
    expect(get).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith("broker_default_upstox_access_token");
  });
});

describe("readKiteAccessToken", () => {
  it("reads the per-profile access token name", async () => {
    const { secrets, get } = fakeSecrets({ broker_main_kite_access_token: "tok" });
    expect(await readKiteAccessToken(secrets, "main")).toBe("tok");
    expect(get).toHaveBeenCalledWith("broker_main_kite_access_token");
  });

  it("never reads the global kite_access_token name", async () => {
    const { secrets, get } = fakeSecrets({ kite_access_token: "tok" });
    expect(await readKiteAccessToken(secrets, "default")).toBeUndefined();
    expect(get).not.toHaveBeenCalledWith("kite_access_token");
  });
});
