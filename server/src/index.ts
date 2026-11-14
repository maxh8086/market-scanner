import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { config as loadDotenv } from "dotenv";
import pg from "pg";
import { buildApp } from "./app.js";
import { loadPoolConfig } from "./config.js";
import { createSecretsClient } from "./secretsClient.js";
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

// App secrets come from the ui's internal secrets API, authorised by a bearer token read from a file on
// every fetch. The server holds no master key and never reads data/secrets.env.
const secrets = createSecretsClient({
  tokenFile: process.env.SECRETS_TOKEN_FILE ?? "/run/app-keys/server_secrets_token",
  baseUrl: process.env.SECRETS_API_URL ?? "http://ui:8080",
  warn: (m) => console.warn(m),
});

const app = buildApp({
  query: (sql, values) => pool.query(sql, values),
  logger: true,
  live: { getAccessToken: () => secrets.get("upstox_analytics_token") },
  kite: {
    credentials: async () => ({
      apiKey: await secrets.get("kite_api_key"),
      // The Kite access token is runtime-only (docs/designs/secrets-and-roles.md Decision 16): it is never
      // fetched from the ui or shared with any service. The compose service does not set it, so holdings
      // report unconfigured in the container.
      accessToken: process.env.KITE_ACCESS_TOKEN?.trim() || undefined,
    }),
  },
  checkToken: (authorization, role) => checkIngestToken(authorization, role, serviceTokens),
  eventsTx: makeEventsTx(pool),
});

app.addHook("onClose", async () => {
  await pool.end();
});

// Loopback by default. In the container SERVER_HOST=0.0.0.0; compose publishes the port on the host's 127.0.0.1 only.
await app.listen({ host: loadServerHost(), port });
