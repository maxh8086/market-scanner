import { randomUUID } from "node:crypto";
import type { FastifyInstance, FastifyReply } from "fastify";
import type { QueryFn } from "../app.js";
import { fetchKiteHoldings, type KiteFetch } from "../holdings/kiteHoldings.js";
import type { PortfolioTx } from "../portfolioTx.js";
import type { SecretsClient } from "../secretsClient.js";
import type { UiClient } from "../uiClient.js";
import { readKiteAccessToken, readKiteApiKey } from "./credentials.js";
import { brokerSecretName, parseProfile, PROFILE_RE } from "./names.js";
import { loadLatestSnapshot, saveOkSnapshot } from "./portfolioStore.js";

/**
 * Broker login and holdings routes. The browser never sees a broker token or API key. Login goes through the
 * ui (login URL, code exchange); the Kite callback is a top-level redirect from the broker, protected by the
 * single-use state that the ui holds. Holdings are read from the stored snapshot. A sync is the only path that
 * calls Kite, and it writes a new snapshot only when every step succeeds.
 */

export interface BrokerAppDeps {
  secrets: Pick<SecretsClient, "get" | "invalidate">;
  uiClient: UiClient;
  /** Where the callback sends the browser after login (BROKER_RETURN_URL). */
  returnUrl: string;
  /** Test seam for the Kite holdings call. Production uses the global fetch. */
  fetch?: KiteFetch;
}

export interface BrokerRouteDeps extends BrokerAppDeps {
  query: QueryFn;
  portfolioTx: PortfolioTx;
  now?: () => Date;
}

const KITE = "kite";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStatusBody(value: unknown): value is { connected: boolean; expires_at?: string | null } {
  if (!isObject(value) || typeof value.connected !== "boolean") return false;
  return value.expires_at === undefined || value.expires_at === null || typeof value.expires_at === "string";
}

export function registerBrokerRoutes(app: FastifyInstance, deps: BrokerRouteDeps): void {
  const kiteFetch: KiteFetch = deps.fetch ?? ((url, init) => fetch(url, init));
  const now = deps.now ?? (() => new Date());
  // Parsed once, so a bad BROKER_RETURN_URL fails at startup instead of on the first callback.
  const returnBase = new URL(deps.returnUrl);

  function loginRedirect(reply: FastifyReply, outcome: "ok" | "failed"): FastifyReply {
    const target = new URL(returnBase.toString());
    target.searchParams.set("broker", KITE);
    target.searchParams.set("login", outcome);
    return reply.code(302).header("Cache-Control", "no-store").header("Location", target.toString()).send();
  }

  app.get<{ Params: { broker: string }; Querystring: { profile?: unknown } }>(
    "/api/broker/:broker/status",
    async (request, reply) => {
      if (request.params.broker !== KITE) return reply.code(404).send({ error: "broker not supported" });
      const profile = parseProfile(request.query.profile);
      if (!profile.ok) return reply.code(400).send({ error: "invalid profile" });

      const ui = await deps.uiClient.request(
        "GET",
        `/internal/broker/${KITE}/status?profile_id=${encodeURIComponent(profile.profile)}`,
      );
      if (ui.status !== 200 || !isStatusBody(ui.body)) {
        return reply.code(502).send({ error: "broker service unavailable" });
      }
      return { connected: ui.body.connected, expiresAt: ui.body.expires_at ?? null };
    },
  );

  app.post<{ Params: { broker: string }; Body: unknown }>(
    "/api/broker/:broker/login-url",
    async (request, reply) => {
      if (request.params.broker !== KITE) return reply.code(404).send({ error: "broker not supported" });
      const body = isObject(request.body) ? request.body : {};
      const profile = parseProfile(body.profile);
      if (!profile.ok) return reply.code(400).send({ error: "invalid profile" });

      const ui = await deps.uiClient.request("POST", `/internal/broker/${KITE}/login-url`, {
        profile_id: profile.profile,
      });
      if (ui.status === 409) return reply.code(409).send({ error: "api key not configured" });
      if (ui.status === 400) return reply.code(400).send({ error: "invalid profile" });
      if (ui.status === 200 && isObject(ui.body) && typeof ui.body.url === "string") {
        return { url: ui.body.url };
      }
      return reply.code(502).send({ error: "broker service unavailable" });
    },
  );

  // Exempt from the session gate (session.ts). Always redirects; never puts the request_token in a
  // redirect, a log or an error. A failed or cancelled login redirects with login=failed and calls nothing.
  app.get<{ Querystring: Record<string, unknown> }>("/api/broker/kite/callback", async (request, reply) => {
    const query = request.query;
    const status = query.status;
    if (status !== undefined && status !== "success") return loginRedirect(reply, "failed");

    const requestToken = query.request_token;
    const state = query.state;
    if (typeof requestToken !== "string" || requestToken === "" || typeof state !== "string" || state === "") {
      return loginRedirect(reply, "failed");
    }

    const ui = await deps.uiClient.request("POST", `/internal/broker/${KITE}/exchange`, {
      request_token: requestToken,
      state,
    });
    if (ui.status !== 200 || !isObject(ui.body)) return loginRedirect(reply, "failed");
    const profileId = ui.body.profile_id;
    if (typeof profileId !== "string" || !PROFILE_RE.test(profileId)) return loginRedirect(reply, "failed");

    deps.secrets.invalidate(brokerSecretName(profileId, KITE, "access_token"));
    return loginRedirect(reply, "ok");
  });

  app.post<{ Body: unknown }>("/api/holdings/sync", async (request, reply) => {
    const body = isObject(request.body) ? request.body : {};
    if (body.broker !== undefined && body.broker !== KITE) {
      return reply.code(400).send({ error: "broker not supported" });
    }
    const parsed = parseProfile(body.profile);
    if (!parsed.ok) return reply.code(400).send({ error: "invalid profile" });
    const profile = parsed.profile;

    const accessToken = await readKiteAccessToken(deps.secrets, profile);
    if (!accessToken) return reply.code(401).send({ error: "login required" });
    const apiKey = await readKiteApiKey(deps.secrets, profile);
    if (!apiKey) return reply.code(409).send({ error: "api key not configured" });

    const result = await fetchKiteHoldings({ apiKey, accessToken, fetch: kiteFetch });
    if (!result.ok) return reply.code(result.status).send({ error: result.error });

    const syncedAt = now().toISOString();
    let rowCount: number;
    try {
      rowCount = await saveOkSnapshot(deps.portfolioTx, {
        syncId: randomUUID(),
        profile,
        broker: KITE,
        syncedAt,
        holdings: result.holdings,
      });
    } catch {
      return reply.code(500).send({ error: "portfolio save failed" });
    }
    return { syncedAt, broker: KITE, rowCount };
  });

  app.get<{ Querystring: { profile?: unknown } }>("/api/holdings", async (request, reply) => {
    const parsed = parseProfile(request.query.profile);
    if (!parsed.ok) return reply.code(400).send({ error: "invalid profile" });
    try {
      return await loadLatestSnapshot(deps.query, parsed.profile, KITE);
    } catch {
      return reply.code(500).send({ error: "holdings unavailable" });
    }
  });
}
