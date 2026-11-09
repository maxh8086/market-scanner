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
