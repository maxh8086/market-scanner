import { describe, expect, it } from "vitest";
import { loadServerHost } from "./serverHost.js";

describe("loadServerHost", () => {
  it("returns 127.0.0.1 when SERVER_HOST is undefined", () => {
    expect(loadServerHost({})).toBe("127.0.0.1");
  });

  it("returns 127.0.0.1 when SERVER_HOST is empty or whitespace only", () => {
    expect(loadServerHost({ SERVER_HOST: "" })).toBe("127.0.0.1");
    expect(loadServerHost({ SERVER_HOST: "   " })).toBe("127.0.0.1");
  });

  it("returns 0.0.0.0 when SERVER_HOST is 0.0.0.0", () => {
    expect(loadServerHost({ SERVER_HOST: "0.0.0.0" })).toBe("0.0.0.0");
  });

  it("trims surrounding whitespace and newlines from SERVER_HOST", () => {
    expect(loadServerHost({ SERVER_HOST: " 0.0.0.0 \n" })).toBe("0.0.0.0");
  });

  it("ignores unrelated environment variables and returns 127.0.0.1", () => {
    expect(loadServerHost({ SERVER_PORT: "9000" })).toBe("127.0.0.1");
  });
});
