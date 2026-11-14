import { describe, expect, it } from "vitest";
import { brokerSecretName, parseProfile } from "./names.js";

describe("parseProfile", () => {
  it.each([undefined, null, ""])("maps %j to the default profile", (raw) => {
    expect(parseProfile(raw)).toEqual({ ok: true, profile: "default" });
  });

  it.each(["a", "main", "abcdefghijklmnop"])("accepts %s", (raw) => {
    expect(parseProfile(raw)).toEqual({ ok: true, profile: raw });
  });

  it.each(["Main", "1main", "a-b", "a_b", "a b", "abcdefghijklmnopq", "a/b", 42, {}])("rejects %j", (raw) => {
    expect(parseProfile(raw)).toEqual({ ok: false });
  });
});

describe("brokerSecretName", () => {
  it("builds broker_<profile>_<broker>_<kind>", () => {
    expect(brokerSecretName("default", "kite", "access_token")).toBe("broker_default_kite_access_token");
    expect(brokerSecretName("main", "kite", "api_key")).toBe("broker_main_kite_api_key");
  });

  it("throws for an invalid profile instead of building a name", () => {
    expect(() => brokerSecretName("Bad Name", "kite", "api_key")).toThrow(/invalid profile/);
  });
});
