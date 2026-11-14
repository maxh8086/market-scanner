import { describe, expect, it } from "vitest";
import { checkIngestToken } from "./homeEventsAuth.js";

const TOKEN = "test-token-aaa";
const expected = { home: TOKEN };

describe("checkIngestToken", () => {
  it("returns 401 when the header is missing", () => {
    expect(checkIngestToken(undefined, "home", expected)).toBe(401);
  });

  it("returns 401 for a non-Bearer scheme", () => {
    expect(checkIngestToken("Basic x", "home", expected)).toBe(401);
  });

  it("returns 401 when the Bearer token is absent", () => {
    expect(checkIngestToken("Bearer", "home", expected)).toBe(401);
  });

  it("returns ok for a matching token with a case-insensitive scheme", () => {
    expect(checkIngestToken(`bearer ${TOKEN}`, "home", expected)).toBe("ok");
  });

  it("returns 403 for a wrong token of the same length", () => {
    expect(checkIngestToken("Bearer test-token-bbb", "home", expected)).toBe(403);
  });

  it("returns 403 for a wrong token of a different length", () => {
    expect(checkIngestToken("Bearer test-token-aa", "home", expected)).toBe(403);
  });

  it("returns 403 when the role has no expected token", () => {
    expect(checkIngestToken(`Bearer ${TOKEN}`, "other", expected)).toBe(403);
  });

  it("returns 403 when the expected token is an empty string", () => {
    expect(checkIngestToken("Bearer test-token-aaa", "home", { home: "" })).toBe(403);
  });

  it("returns 403 for prototype-named roles (hasOwnProperty guard)", () => {
    expect(checkIngestToken(`Bearer ${TOKEN}`, "__proto__", expected)).toBe(403);
    expect(checkIngestToken(`Bearer ${TOKEN}`, "toString", expected)).toBe(403);
  });
});
