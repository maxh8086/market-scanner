import { randomBytes, timingSafeEqual } from "node:crypto";
import type { FastifyInstance } from "fastify";

export const SESSION_COOKIE = "ms_session";
export const SESSION_TTL_MS = 12 * 60 * 60 * 1000;
export const CSRF_HEADER = "x-csrf-token";

export interface Session {
  id: string;
  csrfToken: string;
  expiresAt: number;
}

export interface SessionStore {
  create(): Session;
  get(id: string | undefined): Session | undefined;
}

const DEFAULT_MAX_SESSIONS = 10_000;
const PRUNE_INTERVAL_MS = 60_000;

export function createSessionStore(
  options: { now?: () => number; maxSessions?: number } = {},
): SessionStore {
  const now = options.now ?? (() => Date.now());
  const maxSessions = options.maxSessions ?? DEFAULT_MAX_SESSIONS;
  const sessions = new Map<string, Session>();
  let lastPruneAt = Number.NEGATIVE_INFINITY;

  const pruneExpired = (at: number): void => {
    for (const [id, session] of sessions) {
      if (session.expiresAt <= at) sessions.delete(id);
    }
  };

  return {
    create(): Session {
      const at = now();
      // A full scan is O(n), so it runs at most once a minute. A full store is handled by the eviction loop below.
      if (at - lastPruneAt >= PRUNE_INTERVAL_MS) {
        pruneExpired(at);
        lastPruneAt = at;
      }
      // Map keeps insertion order, and sessions are created in time order, so the first key is the oldest.
      while (sessions.size >= maxSessions) {
        const oldest = sessions.keys().next().value;
        if (oldest === undefined) break;
        sessions.delete(oldest);
      }
      const session: Session = {
        id: randomBytes(32).toString("hex"),
        csrfToken: randomBytes(32).toString("hex"),
        expiresAt: at + SESSION_TTL_MS,
      };
      sessions.set(session.id, session);
      return session;
    },
    get(id: string | undefined): Session | undefined {
      if (id === undefined) return undefined;
      const session = sessions.get(id);
      if (!session) return undefined;
      if (session.expiresAt <= now()) {
        sessions.delete(id);
        return undefined;
      }
      return session;
    },
  };
}

/** Reads one cookie value from a Cookie header. Returns undefined when the name is absent. */
export function readCookie(header: string | undefined, name: string): string | undefined {
  if (header === undefined) return undefined;
  for (const part of header.split(";")) {
    const trimmed = part.trim();
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    if (trimmed.slice(0, eq).trim() === name) {
      return trimmed.slice(eq + 1).trim();
    }
  }
  return undefined;
}

/** Compares a presented CSRF token with the expected one in constant time. */
export function csrfMatches(presented: string | undefined, expected: string): boolean {
  if (presented === undefined) return false;
  const a = Buffer.from(presented, "utf8");
  const b = Buffer.from(expected, "utf8");
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

/** GET /api/session: issues a session cookie on first visit and returns the CSRF token. */
export function registerSessionRoutes(app: FastifyInstance, store: SessionStore): void {
  app.get("/api/session", async (request, reply) => {
    const live = store.get(readCookie(request.headers.cookie, SESSION_COOKIE));
    if (live) {
      return { csrfToken: live.csrfToken };
    }
    const session = store.create();
    const maxAgeSeconds = Math.floor(SESSION_TTL_MS / 1000);
    reply.header(
      "Set-Cookie",
      `${SESSION_COOKIE}=${session.id}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${maxAgeSeconds}`,
    );
    return { csrfToken: session.csrfToken };
  });
}

/**
 * Methods that never change state. Safe methods need a live session, but skip the cross-site and
 * CSRF checks. Every other method is gated in full (fail-closed).
 */
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/**
 * Exact paths a safe-method request may reach without a session. /api/session is listed because
 * it issues the session cookie and so cannot require one. /api/health is listed because the
 * Docker healthcheck and the watchdog poll it without a browser session. It returns only the
 * static body {ok: true}. /api/broker/kite/callback and /api/broker/upstox/callback are the brokers' top-level
 * redirects, which may not carry the session cookie; they are protected by the single-use login state instead.
 * Nothing else is exempt.
 */
const SESSION_EXEMPT_SAFE_PATHS = new Set([
  "/api/session",
  "/api/health",
  "/api/broker/kite/callback",
  "/api/broker/upstox/callback",
]);

/** Matches an absolute-form request target such as "http://host:port" at the start of a URL. */
const ABSOLUTE_FORM_PREFIX = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\/[^/?#]*/;

/**
 * Returns the path of a raw request target. The result is not percent-decoded, normalised or
 * lowercased, so the gate sees exactly what the client sent. The router decodes paths, so a
 * decoded comparison here would be a different check from the one the router runs.
 */
function requestPath(url: string): string {
  let target = url;
  const prefix = ABSOLUTE_FORM_PREFIX.exec(target);
  if (prefix) {
    target = target.slice(prefix[0].length);
    if (target === "") target = "/";
  }
  const cut = target.search(/[?#]/);
  return cut === -1 ? target : target.slice(0, cut);
}

/**
 * Requires a live session on every request. The literal prefix "/internal/" is the only
 * exemption, and it uses service tokens instead of sessions. Safe methods (GET, HEAD, OPTIONS)
 * then need only that session. The one safe-method exemption is the exact path /api/session,
 * which issues the cookie, and the exact path /api/health (see SESSION_EXEMPT_SAFE_PATHS). Every other method also needs a non-cross-site Sec-Fetch-Site and a
 * matching CSRF header, checked after the session. Any other path, including encoded, odd-slash
 * and cased variants, is gated. This is deliberately fail-closed: it does not rely on Fastify's
 * routing defaults to decide which paths are protected.
 */
export function registerCsrfGate(app: FastifyInstance, store: SessionStore): void {
  app.addHook("onRequest", async (request, reply) => {
    const path = requestPath(request.url);
    if (path.startsWith("/internal/")) return;

    const safe = SAFE_METHODS.has(request.method);
    if (safe && SESSION_EXEMPT_SAFE_PATHS.has(path)) return;

    const session = store.get(readCookie(request.headers.cookie, SESSION_COOKIE));
    if (!session) {
      return reply.code(401).send({ error: "session_required" });
    }
    if (safe) return;

    const fetchSiteValues = [request.headers["sec-fetch-site"] ?? []].flat().join(",").split(",");
    if (fetchSiteValues.some((value) => value.trim().toLowerCase() === "cross-site")) {
      return reply.code(403).send({ error: "cross_site_request" });
    }
    const presented = request.headers[CSRF_HEADER] as string | undefined;
    if (!csrfMatches(presented, session.csrfToken)) {
      return reply.code(403).send({ error: "csrf_required" });
    }
  });
}
