import { timingSafeEqual } from "node:crypto";

/**
 * Bearer-token check for the home events ingest route. The expected tokens come from the caller
 * (server config), keyed by role. The token itself is never logged or returned.
 *
 * "ok"  the header is "Bearer <token>" and the token equals expected[role].
 * 401   no header, or not in the "Bearer <token>" shape.
 * 403   a token was presented, but it does not match, or the role has no expected token.
 */
export type IngestAuthResult = "ok" | 401 | 403;

const BEARER = /^Bearer ([^\s]+)$/i;

export function checkIngestToken(
  authorization: string | undefined,
  role: string,
  expected: Record<string, string>,
): IngestAuthResult {
  if (authorization === undefined) return 401;
  const match = BEARER.exec(authorization);
  if (!match) return 401;

  const expectedToken = Object.prototype.hasOwnProperty.call(expected, role) ? expected[role] : undefined;
  if (!expectedToken) return 403;

  const presented = Buffer.from(match[1], "utf8");
  const wanted = Buffer.from(expectedToken, "utf8");
  if (presented.length !== wanted.length) return 403;
  return timingSafeEqual(presented, wanted) ? "ok" : 403;
}
