import { describe, expect, it } from "vitest";
import { redactCallbackUrl } from "./requestLog.js";

describe("redactCallbackUrl", () => {
  it("drops the query string of the kite callback", () => {
    expect(redactCallbackUrl("/api/broker/kite/callback?request_token=x&state=y&status=success")).toBe(
      "/api/broker/kite/callback?redacted",
    );
  });

  it("drops the query string of the upstox callback", () => {
    expect(redactCallbackUrl("/api/broker/upstox/callback?code=x&state=y")).toBe("/api/broker/upstox/callback?redacted");
  });

  it("keeps a callback path without a query string as it is", () => {
    expect(redactCallbackUrl("/api/broker/kite/callback")).toBe("/api/broker/kite/callback");
    expect(redactCallbackUrl("/api/broker/upstox/callback")).toBe("/api/broker/upstox/callback");
  });

  it("also redacts a callback path with a trailing slash", () => {
    expect(redactCallbackUrl("/api/broker/kite/callback/?request_token=x")).toBe("/api/broker/kite/callback/?redacted");
    expect(redactCallbackUrl("/api/broker/upstox/callback/?code=x")).toBe("/api/broker/upstox/callback/?redacted");
  });

  it("leaves an unrelated url with a query string unchanged", () => {
    expect(redactCallbackUrl("/api/events?limit=5&state=y")).toBe("/api/events?limit=5&state=y");
  });

  it("leaves a path that only starts with a callback path unchanged", () => {
    expect(redactCallbackUrl("/api/broker/kite/callbackx?a=1")).toBe("/api/broker/kite/callbackx?a=1");
  });

  it("is case sensitive, as the router is", () => {
    expect(redactCallbackUrl("/API/broker/kite/callback?request_token=x")).toBe("/API/broker/kite/callback?request_token=x");
  });
});
