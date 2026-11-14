/**
 * Naming rules for per-profile broker secrets. The ui stores and checks these names; the server builds the
 * same names here. Phase 1 reads only the access token and the API key for Kite. Secret names cannot contain
 * dots, so the profile and broker are joined with underscores (the profile never contains one).
 */

export const DEFAULT_PROFILE = "default";
export const PROFILE_RE = /^[a-z][a-z0-9]{0,15}$/;

export type BrokerId = "kite" | "upstox";
export const BROKER_IDS: readonly BrokerId[] = ["kite", "upstox"];

/** True only for an exact broker id. Anything else (including a case variant) is not a broker. */
export function isBrokerId(raw: unknown): raw is BrokerId {
  return typeof raw === "string" && (BROKER_IDS as readonly string[]).includes(raw);
}
export type BrokerSecretKind = "access_token" | "api_key";

export type ParsedProfile = { ok: true; profile: string } | { ok: false };

/** A missing profile means the default profile. Any other value must match PROFILE_RE exactly. */
export function parseProfile(raw: unknown): ParsedProfile {
  if (raw === undefined || raw === null || raw === "") return { ok: true, profile: DEFAULT_PROFILE };
  if (typeof raw === "string" && PROFILE_RE.test(raw)) return { ok: true, profile: raw };
  return { ok: false };
}

/** Name of one stored broker secret, e.g. broker_default_kite_access_token. */
export function brokerSecretName(profile: string, broker: BrokerId, kind: BrokerSecretKind): string {
  if (!PROFILE_RE.test(profile)) throw new Error("invalid profile");
  return `broker_${profile}_${broker}_${kind}`;
}
