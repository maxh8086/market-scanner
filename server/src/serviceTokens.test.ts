import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { loadServiceTokens } from "./serviceTokens.js";

const DIR = "/run/app-keys";

/** Builds a readText seam from a map of file name to content. A missing name throws, like ENOENT. */
function fakeReader(files: Record<string, string>): { readText: (p: string) => string; paths: string[] } {
  const paths: string[] = [];
  const readText = (p: string): string => {
    paths.push(p);
    const name = p.split(/[\\/]/).pop() ?? "";
    if (!(name in files)) {
      throw new Error("ENOENT");
    }
    return files[name];
  };
  return { readText, paths };
}

describe("loadServiceTokens", () => {
  it("loads each role whose file exists and trims whitespace and newlines", () => {
    const { readText, paths } = fakeReader({
      "ingest_token": "  abc123\n",
      "collector_token": "\tdef456\r\n",
    });
    const tokens = loadServiceTokens(DIR, ["ingest", "collector"], readText);
    expect(tokens).toEqual({ ingest: "abc123", collector: "def456" });
    expect(paths).toEqual([join(DIR, "ingest_token"), join(DIR, "collector_token")]);
  });

  it("omits a role whose file is missing or unreadable, without throwing", () => {
    const { readText } = fakeReader({ "collector_token": "def456\n" });
    const tokens = loadServiceTokens(DIR, ["ingest", "collector"], readText);
    expect(tokens).toEqual({ collector: "def456" });
    expect("ingest" in tokens).toBe(false);
  });

  it("omits a role whose file is empty or whitespace only", () => {
    const { readText } = fakeReader({
      "ingest_token": "",
      "collector_token": " \n\t \r\n",
      "scanner_token": "ghi789",
    });
    const tokens = loadServiceTokens(DIR, ["ingest", "collector", "scanner"], readText);
    expect(tokens).toEqual({ scanner: "ghi789" });
  });
});
