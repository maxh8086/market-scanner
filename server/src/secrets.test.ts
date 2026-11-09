import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { readSecret } from "./secrets.js";

const NAME = "KITE_TEST_SECRET_VALUE";
let dir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "secrets-"));
  process.env.SECRETS_FILE = join(dir, "secrets.env");
  delete process.env[NAME];
});

afterEach(() => {
  delete process.env.SECRETS_FILE;
  delete process.env[NAME];
  rmSync(dir, { recursive: true, force: true });
});

describe("readSecret", () => {
  it("reads a value saved by the UI from the secrets file", () => {
    writeFileSync(process.env.SECRETS_FILE!, `OTHER=1\n${NAME}=abc123\n`);
    expect(readSecret(NAME)).toBe("abc123");
  });

  it("prefers the environment over the file", () => {
    writeFileSync(process.env.SECRETS_FILE!, `${NAME}=from-file\n`);
    process.env[NAME] = "from-env";
    expect(readSecret(NAME)).toBe("from-env");
  });

  it("re-reads the file, so a token saved later is picked up without a restart", () => {
    expect(readSecret(NAME)).toBeUndefined();
    writeFileSync(process.env.SECRETS_FILE!, `${NAME}=new-token\n`);
    expect(readSecret(NAME)).toBe("new-token");
  });

  it("returns undefined when the file is missing", () => {
    expect(readSecret(NAME)).toBeUndefined();
  });
});
