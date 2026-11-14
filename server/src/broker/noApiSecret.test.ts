import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The broker code never names an API secret: that value is not part of the design. The literal is built from
// two halves so this test file itself does not contain it.
const FORBIDDEN = ["api", "secret"].join("_");

const sources = readdirSync(new URL("./", import.meta.url))
  .filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))
  .map((name) => ({ name, text: readFileSync(new URL(name, import.meta.url), "utf-8") }));

describe("broker code never names an API secret", () => {
  it("reads at least the broker source files", () => {
    expect(sources.map((s) => s.name)).toEqual(expect.arrayContaining(["names.ts", "credentials.ts", "brokerRoutes.ts"]));
  });

  it.each(sources.map((s) => [s.name, s.text] as const))("%s does not contain the forbidden name", (_name, text) => {
    expect(text).not.toContain(FORBIDDEN);
  });
});
