/** Reconnect backoff for the live feed socket. Pure, so it is unit-tested without timers. */

export const BACKOFF_STEPS_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000] as const;

/** Delay before reconnect attempt number `attempt` (0-based). Caps at the last step. */
export function backoffDelayMs(attempt: number): number {
  const index = Math.min(Math.max(0, Math.floor(attempt)), BACKOFF_STEPS_MS.length - 1);
  return BACKOFF_STEPS_MS[index];
}
