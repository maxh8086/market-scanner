import { describe, expect, it } from "vitest";
import { eventsPoolConfig, loadPoolConfig } from "./config.js";

const FAKE_PW = "test-pw-aaa";

describe("eventsPoolConfig, parts form", () => {
  it("defaults the events database name to market_scanner_events", () => {
    const cfg = eventsPoolConfig({
      POSTGRES_HOST: "db.local",
      POSTGRES_PORT: "5999",
      POSTGRES_DB: "market_scanner",
      POSTGRES_USER: "u",
      POSTGRES_PASSWORD: FAKE_PW,
    });
    expect(cfg).toMatchObject({
      host: "db.local",
      port: 5999,
      database: "market_scanner_events",
      user: "u",
      password: FAKE_PW,
    });
  });

  it("uses POSTGRES_EVENTS_DB when it is set", () => {
    const cfg = eventsPoolConfig({
      POSTGRES_HOST: "db.local",
      POSTGRES_DB: "market_scanner",
      POSTGRES_EVENTS_DB: "ev_test_db",
      POSTGRES_USER: "u",
      POSTGRES_PASSWORD: FAKE_PW,
    });
    expect(cfg).toMatchObject({ database: "ev_test_db", host: "db.local" });
  });
});

describe("eventsPoolConfig, DSN form", () => {
  it("replaces the database and keeps user, host, port and query string", () => {
    const dsn = `postgres://u:${FAKE_PW}@db.local:5999/market_scanner?sslmode=require`;
    const cfg = eventsPoolConfig({ POSTGRES_DSN: dsn });
    expect(cfg).toHaveProperty("connectionString");
    const url = new URL((cfg as { connectionString: string }).connectionString);
    expect(url.pathname).toBe("/market_scanner_events");
    expect(url.username).toBe("u");
    expect(url.password).toBe(FAKE_PW);
    expect(url.hostname).toBe("db.local");
    expect(url.port).toBe("5999");
    expect(url.search).toBe("?sslmode=require");
  });

  it("applies POSTGRES_EVENTS_DB as the database override", () => {
    const cfg = eventsPoolConfig({
      POSTGRES_DSN: "postgresql://u@h/old",
      POSTGRES_EVENTS_DB: "ev_test_db",
    });
    expect(cfg).toEqual({ connectionString: "postgresql://u@h/ev_test_db" });
  });

  it("throws on an unparseable DSN without echoing the DSN text", () => {
    const badDsn = `not a url ${FAKE_PW}`;
    let message = "";
    try {
      eventsPoolConfig({ POSTGRES_DSN: badDsn });
    } catch (err) {
      message = err instanceof Error ? err.message : String(err);
    }
    expect(message).toBe("POSTGRES_DSN is not a valid URL");
    expect(message).not.toContain(FAKE_PW);
    expect(message).not.toContain("not a url");
  });
});

describe("loadPoolConfig regression", () => {
  it("still returns the parts form with the given database and default host and port", () => {
    const cfg = loadPoolConfig({ POSTGRES_DB: "market_scanner", POSTGRES_USER: "u" });
    expect(cfg).toMatchObject({ host: "127.0.0.1", port: 5433, database: "market_scanner", user: "u" });
  });
});

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
