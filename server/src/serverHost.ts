/** Listen host. Defaults to loopback so local development is unchanged; the container sets SERVER_HOST=0.0.0.0. */
export function loadServerHost(env: NodeJS.ProcessEnv = process.env): string {
  const host = env.SERVER_HOST?.trim();
  return host ? host : "127.0.0.1";
}
