import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { config as loadDotenv } from "dotenv";
import pg from "pg";
import { buildApp } from "./app.js";
import { loadPoolConfig } from "./config.js";

const here = dirname(fileURLToPath(import.meta.url));
// Repo-root .env. Existing process env vars win over file values.
loadDotenv({ path: resolve(here, "../../.env"), quiet: true });

const { Pool, types } = pg;

// Keep DATE columns as YYYY-MM-DD strings and NUMERIC as JS numbers in JSON output.
types.setTypeParser(1082, (value: string) => value);
types.setTypeParser(1700, (value: string) => Number(value));

const port = Number(process.env.SERVER_PORT ?? 8081);
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error("SERVER_PORT must be an integer between 1 and 65535");
}

const pool = new Pool(loadPoolConfig());

const app = buildApp({
  query: (sql, values) => pool.query(sql, values),
  logger: true,
});

app.addHook("onClose", async () => {
  await pool.end();
});

// Loopback only. Never bind 0.0.0.0.
await app.listen({ host: "127.0.0.1", port });
