import type { PoolConfig } from "pg";

/**
 * Builds the pg pool config from environment variables.
 * POSTGRES_DSN, when set, overrides the individual POSTGRES_* parts.
 * No default password is ever supplied.
 */
export function loadPoolConfig(env: NodeJS.ProcessEnv = process.env): PoolConfig {
  const dsn = env.POSTGRES_DSN;
  if (dsn) {
    return { connectionString: dsn };
  }

  const port = Number(env.POSTGRES_PORT ?? 5433);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("POSTGRES_PORT must be an integer between 1 and 65535");
  }

  return {
    host: env.POSTGRES_HOST || "127.0.0.1",
    port,
    database: env.POSTGRES_DB,
    user: env.POSTGRES_USER,
    password: env.POSTGRES_PASSWORD,
  };
}

const DEFAULT_EVENTS_DB = "market_scanner_events";

/**
 * Builds the pg pool config for the events database.
 * Uses POSTGRES_EVENTS_DB (default market_scanner_events, same default as
 * scanner/pg/migrate.py _dbname). With POSTGRES_DSN set, only the database
 * path is replaced. The DSN is never echoed in errors.
 */
export function eventsPoolConfig(env: NodeJS.ProcessEnv = process.env): PoolConfig {
  const eventsDb = env.POSTGRES_EVENTS_DB || DEFAULT_EVENTS_DB;
  const dsn = env.POSTGRES_DSN;
  if (dsn) {
    let url: URL;
    try {
      url = new URL(dsn);
    } catch {
      throw new Error("POSTGRES_DSN is not a valid URL");
    }
    if (url.protocol !== "postgres:" && url.protocol !== "postgresql:") {
      throw new Error("POSTGRES_DSN is not a valid URL");
    }
    url.pathname = "/" + encodeURIComponent(eventsDb);
    return { connectionString: url.toString() };
  }

  return { ...loadPoolConfig(env), database: eventsDb };
}
