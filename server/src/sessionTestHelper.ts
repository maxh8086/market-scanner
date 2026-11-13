import type { FastifyInstance } from "fastify";

/**
 * Opens a browser-style session on the given app: calls GET /api/session and returns the
 * cookie pair and the CSRF token for use in later write requests.
 */
export async function browserSession(app: FastifyInstance): Promise<{ cookie: string; csrf: string }> {
  const res = await app.inject({ method: "GET", url: "/api/session" });
  const setCookie = res.headers["set-cookie"];
  const header = Array.isArray(setCookie) ? setCookie[0] : setCookie;
  if (!header) {
    throw new Error("GET /api/session did not set a cookie");
  }
  const cookie = header.split(";")[0];
  const { csrfToken } = res.json() as { csrfToken: string };
  return { cookie, csrf: csrfToken };
}
