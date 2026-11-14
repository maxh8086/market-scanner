import type { SecretsClient } from "../secretsClient.js";
import { brokerSecretName, DEFAULT_PROFILE } from "./names.js";

export type SecretReader = Pick<SecretsClient, "get">;

/**
 * Kite API key for a profile. The default profile falls back to the global kite_api_key when its own
 * per-profile name is not stored. Other profiles never fall back.
 */
export async function readKiteApiKey(secrets: SecretReader, profile: string): Promise<string | undefined> {
  const own = await secrets.get(brokerSecretName(profile, "kite", "api_key"));
  if (own) return own;
  return profile === DEFAULT_PROFILE ? secrets.get("kite_api_key") : undefined;
}

/** Kite access token for a profile. The ui returns nothing for an expired token. */
export function readKiteAccessToken(secrets: SecretReader, profile: string): Promise<string | undefined> {
  return secrets.get(brokerSecretName(profile, "kite", "access_token"));
}
