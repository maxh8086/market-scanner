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
