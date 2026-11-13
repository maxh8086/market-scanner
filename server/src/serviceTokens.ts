import { readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * Reads one token file per role from dir (`<role>_token`). A role is included only when its file
 * reads and the trimmed content is non-empty. Missing or unreadable files are omitted, not thrown.
 * Token values are never logged.
 */
export function loadServiceTokens(
  dir: string,
  roles: readonly string[],
  readText: (path: string) => string = (p) => readFileSync(p, "utf8"),
): Record<string, string> {
  const tokens: Record<string, string> = {};
  for (const role of roles) {
    let value: string;
    try {
      value = readText(join(dir, `${role}_token`)).trim();
    } catch {
      continue;
    }
    if (value.length > 0) {
      tokens[role] = value;
    }
  }
  return tokens;
}
