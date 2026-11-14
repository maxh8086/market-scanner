import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { config as loadDotenv } from "dotenv";
import pg from "pg";
import { buildApp } from "./app.js";
import { eventsPoolConfig, loadPoolConfig } from "./config.js";
import { createSecretsClient } from "./secretsClient.js";
import { createUiClient } from "./uiClient.js";
import { loadServiceTokens } from "./serviceTokens.js";
import { checkIngestToken } from "./homeEventsAuth.js";
import { makeEventsTx } from "./eventsTx.js";
import { makePortfolioTx } from "./portfolioTx.js";
import { loadServerHost } from "./serverHost.js";
import { parseServicesFile } from "./collectorDue.js";

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
// Home events live in the events database, so their transactions use this pool, not the main one.
const eventsPool = new Pool(eventsPoolConfig());
eventsPool.on("error", () => console.warn("events pool error"));
const serviceTokens = loadServiceTokens(process.env.SERVICE_TOKEN_DIR ?? "/run/service-tokens", ["home_events_ingest", "collector_watchdog"]);
// Collector services file, read on every /internal/due poll (not at startup).
const collectorServicesFile = process.env.COLLECTOR_SERVICES_FILE ?? resolve(here, "../../config/collector_services.json");

// App secrets and broker login calls go to the ui's internal API, authorised by a bearer token read from a file
// on every fetch. The server holds no master key and never reads data/secrets.env.
const secretsTokenFile = process.env.SECRETS_TOKEN_FILE ?? "/run/app-keys/server_secrets_token";
const secretsApiUrl = process.env.SECRETS_API_URL ?? "http://ui:8080";
const secrets = createSecretsClient({
  tokenFile: secretsTokenFile,
  baseUrl: secretsApiUrl,
  warn: (m) => console.warn(m),
});
const uiClient = createUiClient({ tokenFile: secretsTokenFile, baseUrl: secretsApiUrl });

const app = buildApp({
  query: (sql, values) => pool.query(sql, values),
  eventsQuery: (sql, values) => eventsPool.query(sql, values),
  logger: true,
  live: { getAccessToken: () => secrets.get("upstox_analytics_token") },
  // Broker login: the browser is sent back here after the Kite login (see broker/brokerRoutes.ts).
  broker: {
    secrets,
    uiClient,
    returnUrl: process.env.BROKER_RETURN_URL?.trim() || "http://127.0.0.1:5173/",
  },
  portfolioTx: makePortfolioTx(pool),
  checkToken: (authorization, role) => checkIngestToken(authorization, role, serviceTokens),
  eventsTx: makeEventsTx(eventsPool),
  eventsPing: () => eventsPool.query("SELECT 1").then(() => undefined),
  collectorDue: {
    checkToken: (authorization, role) => checkIngestToken(authorization, role, serviceTokens),
    loadServices: () => parseServicesFile(readFileSync(collectorServicesFile, "utf8")),
  },
});

app.addHook("onClose", async () => {
  try {
    await pool.end();
  } finally {
    await eventsPool.end();
  }
});

// Loopback by default. In the container SERVER_HOST=0.0.0.0; compose publishes the port on the host's 127.0.0.1 only.
await app.listen({ host: loadServerHost(), port });
