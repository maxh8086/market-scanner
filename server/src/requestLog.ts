import type { FastifyRequest } from "fastify";

/**
 * The broker callbacks receive request_token, code and state in the query string. Those values must not reach
 * the request log, so the callback query string is replaced with a fixed marker.
 */
const CALLBACK_PATHS = new Set([
  "/api/broker/kite/callback",
  "/api/broker/kite/callback/",
  "/api/broker/upstox/callback",
  "/api/broker/upstox/callback/",
]);

/** Returns the url with the query string of a broker callback replaced by `?redacted`. Other urls are unchanged. */
export function redactCallbackUrl(url: string): string {
  const queryAt = url.indexOf("?");
  const path = queryAt === -1 ? url : url.slice(0, queryAt);
  if (!CALLBACK_PATHS.has(path)) return url;
  return queryAt === -1 ? path : `${path}?redacted`;
}

/** Request serializer for Fastify's logger: the fields Fastify logs by default, with the callback url redacted. */
export function requestLogSerializer(req: FastifyRequest) {
  return {
    method: req.method,
    url: redactCallbackUrl(req.url),
    host: req.host,
    remoteAddress: req.ip,
    remotePort: req.socket?.remotePort,
  };
}
