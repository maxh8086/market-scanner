import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { config as loadDotenv } from "dotenv";
import pg from "pg";
import { buildApp } from "./app.js";
import { loadPoolConfig } from "./config.js";
import { readSecret } from "./secrets.js";
import { loadServiceTokens } from "./serviceTokens.js";
import { checkIngestToken } from "./homeEventsAuth.js";
import { makeEventsTx } from "./eventsTx.js";
import { loadServerHost } from "./serverHost.js";

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
const serviceTokens = loadServiceTokens(process.env.SERVICE_TOKEN_DIR ?? "/run/service-tokens", ["home_events_ingest"]);

const app = buildApp({
  query: (sql, values) => pool.query(sql, values),
  logger: true,
  live: { accessToken: process.env.UPSTOX_ACCESS_TOKEN || process.env.UPSTOX_ANALYTICS_ACCESS_TOKEN || undefined },
  kite: {
    credentials: () => ({ apiKey: readSecret("KITE_API_KEY"), accessToken: readSecret("KITE_ACCESS_TOKEN") }),
  },
  checkToken: (authorization, role) => checkIngestToken(authorization, role, serviceTokens),
  eventsTx: makeEventsTx(pool),
});

app.addHook("onClose", async () => {
  await pool.end();
});

// Loopback by default. In the container SERVER_HOST=0.0.0.0; compose publishes the port on the host's 127.0.0.1 only.
await app.listen({ host: loadServerHost(), port });
