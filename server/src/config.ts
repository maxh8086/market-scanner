import { readFileSync } from "node:fs";
import type { PoolConfig } from "pg";

/**
 * Builds the pg pool config from environment variables.
 * POSTGRES_DSN, when set, overrides the individual POSTGRES_* parts.
 * POSTGRES_PASSWORD_FILE, when set and non-blank, supplies the password and
 * wins over POSTGRES_PASSWORD; one trailing newline is stripped from the file.
 * The password value is never logged, and read errors do not echo file content.
 * No default password is ever supplied.
 */
export function loadPoolConfig(
  env: NodeJS.ProcessEnv = process.env,
  readText: (path: string) => string = (p) => readFileSync(p, "utf8"),
): PoolConfig {
  const dsn = env.POSTGRES_DSN;
  if (dsn) {
    return { connectionString: dsn };
  }

  const port = Number(env.POSTGRES_PORT ?? 5433);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("POSTGRES_PORT must be an integer between 1 and 65535");
  }

  let password = env.POSTGRES_PASSWORD;
  const passwordFile = env.POSTGRES_PASSWORD_FILE?.trim();
  if (passwordFile) {
    let content: string;
    try {
      content = readText(passwordFile);
    } catch {
      throw new Error(`POSTGRES_PASSWORD_FILE could not be read (${passwordFile})`);
    }
    password = content.replace(/\r?\n$/, "");
    if (password === "") {
      throw new Error(`POSTGRES_PASSWORD_FILE is empty (${passwordFile})`);
    }
  }

  return {
    host: env.POSTGRES_HOST || "127.0.0.1",
    port,
    database: env.POSTGRES_DB,
    user: env.POSTGRES_USER,
    password,
  };
}
