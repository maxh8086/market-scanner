import { describe, expect, it } from "vitest";
import { loadPoolConfig } from "./config.js";

const SECRET_PATH = "/run/app-keys/server_db_password";

function fakeReader(content: string) {
  const calls: string[] = [];
  const readText = (path: string): string => {
    calls.push(path);
    return content;
  };
  return { readText, calls };
}

function throwingReader(message: string) {
  const calls: string[] = [];
  const readText = (path: string): string => {
    calls.push(path);
    throw new Error(message);
  };
  return { readText, calls };
}

describe("loadPoolConfig", () => {
  it("returns only connectionString when POSTGRES_DSN is set and never reads the password file", () => {
    const { readText, calls } = fakeReader("should-not-be-read");
    const config = loadPoolConfig(
      {
        POSTGRES_DSN: "postgres://user:fake-pw@127.0.0.1:5433/db",
        POSTGRES_PASSWORD_FILE: SECRET_PATH,
      },
      readText,
    );
    expect(config).toEqual({ connectionString: "postgres://user:fake-pw@127.0.0.1:5433/db" });
    expect(calls).toEqual([]);
  });

  it("uses POSTGRES_PASSWORD and defaults host and port when no file var is set", () => {
    const { readText, calls } = fakeReader("unused");
    const config = loadPoolConfig({ POSTGRES_PASSWORD: "fake-pw" }, readText);
    expect(config.password).toBe("fake-pw");
    expect(config.host).toBe("127.0.0.1");
    expect(config.port).toBe(5433);
    expect(calls).toEqual([]);
  });

  it("reads the password file once from the exact path", () => {
    const { readText, calls } = fakeReader("fake-pw\n");
    loadPoolConfig({ POSTGRES_PASSWORD_FILE: SECRET_PATH }, readText);
    expect(calls).toEqual([SECRET_PATH]);
  });

  it("removes exactly one trailing LF from the file content", () => {
    const { readText } = fakeReader("fake-pw\n");
    expect(loadPoolConfig({ POSTGRES_PASSWORD_FILE: SECRET_PATH }, readText).password).toBe("fake-pw");
  });

  it("removes exactly one trailing CRLF from the file content", () => {
    const { readText } = fakeReader("fake-pw\r\n");
    expect(loadPoolConfig({ POSTGRES_PASSWORD_FILE: SECRET_PATH }, readText).password).toBe("fake-pw");
  });

  it("removes only one newline when the file ends with two", () => {
    const { readText } = fakeReader("fake-pw\n\n");
    expect(loadPoolConfig({ POSTGRES_PASSWORD_FILE: SECRET_PATH }, readText).password).toBe("fake-pw\n");
  });

  it("preserves inner and leading spaces in the file content", () => {
    const { readText } = fakeReader(" a b\n");
    expect(loadPoolConfig({ POSTGRES_PASSWORD_FILE: SECRET_PATH }, readText).password).toBe(" a b");
  });

  it("prefers the file over POSTGRES_PASSWORD when both are set", () => {
    const { readText } = fakeReader("file-pw\n");
    const config = loadPoolConfig(
      { POSTGRES_PASSWORD_FILE: SECRET_PATH, POSTGRES_PASSWORD: "env-pw" },
      readText,
    );
    expect(config.password).toBe("file-pw");
  });

  it("throws a path-only error without the underlying read error message when the file is unreadable", () => {
    const { readText } = throwingReader("SECRET-LEAK-CHECK");
    let caught: unknown;
    try {
      loadPoolConfig({ POSTGRES_PASSWORD_FILE: SECRET_PATH }, readText);
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(Error);
    const message = (caught as Error).message;
    expect(message).toContain("POSTGRES_PASSWORD_FILE");
    expect(message).not.toContain("SECRET-LEAK-CHECK");
  });

  it.each(["", "\n", "\r\n"])("throws an empty-file error for file content %j without echoing it", (content) => {
    const { readText } = fakeReader(content);
    let caught: unknown;
    try {
      loadPoolConfig({ POSTGRES_PASSWORD_FILE: SECRET_PATH }, readText);
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(Error);
    const message = (caught as Error).message;
    expect(message).toContain("POSTGRES_PASSWORD_FILE");
    expect(message).toContain("empty");
    expect(message).not.toContain("fake-pw");
  });

  it.each(["", "   "])("treats POSTGRES_PASSWORD_FILE %j as unset and falls back to POSTGRES_PASSWORD", (fileVar) => {
    const { readText, calls } = fakeReader("should-not-be-read");
    const config = loadPoolConfig({ POSTGRES_PASSWORD_FILE: fileVar, POSTGRES_PASSWORD: "fake-pw" }, readText);
    expect(config.password).toBe("fake-pw");
    expect(calls).toEqual([]);
  });

  it("still rejects an out-of-range POSTGRES_PORT when the file form is used", () => {
    const { readText } = fakeReader("fake-pw\n");
    expect(() =>
      loadPoolConfig({ POSTGRES_PASSWORD_FILE: SECRET_PATH, POSTGRES_PORT: "70000" }, readText),
    ).toThrow("POSTGRES_PORT must be an integer between 1 and 65535");
  });

  it("passes host, port, user and database through with the file form", () => {
    const { readText } = fakeReader("fake-pw\n");
    const config = loadPoolConfig(
      {
        POSTGRES_PASSWORD_FILE: SECRET_PATH,
        POSTGRES_USER: "market_scanner_server",
        POSTGRES_DB: "market_scanner",
        POSTGRES_HOST: "scanner-postgres",
        POSTGRES_PORT: "5432",
      },
      readText,
    );
    expect(config).toEqual({
      host: "scanner-postgres",
      port: 5432,
      database: "market_scanner",
      user: "market_scanner_server",
      password: "fake-pw",
    });
  });
});
