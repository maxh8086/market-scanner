import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "dotenv";

/**
 * The UI saves keys to data/secrets.env (see scanner/secrets_store.py). This server reads the same
 * file. An environment variable wins over the file, matching the Python side's precedence.
 * SECRETS_FILE overrides the path, as in secrets_store.py.
 */
const here = dirname(fileURLToPath(import.meta.url));
const DEFAULT_SECRETS_FILE = resolve(here, "../../data/secrets.env");

export function secretsFilePath(): string {
  const override = process.env.SECRETS_FILE;
  return override ? resolve(override) : DEFAULT_SECRETS_FILE;
}

function readSecretsFile(): Record<string, string> {
  try {
    return parse(readFileSync(secretsFilePath(), "utf-8"));
  } catch {
    // Missing or unreadable file: the variable is simply unset.
    return {};
  }
}

/** Current value of a secret, or undefined when neither the environment nor the file has it. */
export function readSecret(name: string): string | undefined {
  const fromEnv = process.env[name]?.trim();
  if (fromEnv) return fromEnv;
  const fromFile = readSecretsFile()[name]?.trim();
  return fromFile || undefined;
}
