const MINUS = "−";
const EM_DASH = "—";
const RUPEE = "₹";

function isMissing(value: number | null | undefined): value is null | undefined {
  return value === null || value === undefined || !Number.isFinite(value);
}

/** Groups an integer digit string in Indian style: 12345678 -> 1,23,45,678. */
function groupIndian(intDigits: string): string {
  if (intDigits.length <= 3) {
    return intDigits;
  }
  const last3 = intDigits.slice(-3);
  const rest = intDigits.slice(0, -3);
  const groups: string[] = [];
  for (let end = rest.length; end > 0; end -= 2) {
    groups.unshift(rest.slice(Math.max(0, end - 2), end));
  }
  return `${groups.join(",")},${last3}`;
}

/** Fixed-point magnitude with Indian grouping, sign decided after rounding. */
function formatMagnitude(value: number, decimals: number): { negative: boolean; body: string } {
  const fixed = Math.abs(value).toFixed(decimals);
  const isZero = Number(fixed) === 0;
  const negative = value < 0 && !isZero;
  const [intPart, fracPart] = fixed.split(".");
  const grouped = groupIndian(intPart);
  return { negative, body: fracPart ? `${grouped}.${fracPart}` : grouped };
}

/** Signed number for changes: "+12.30", "−12.30", "0.00". */
function formatSignedNumber(value: number, decimals: number): string {
  const { negative, body } = formatMagnitude(value, decimals);
  if (negative) {
    return `${MINUS}${body}`;
  }
  const isZero = Number(Math.abs(value).toFixed(decimals)) === 0;
  return isZero ? body : `+${body}`;
}

/** Sign of a value after rounding to the given decimals: 1, -1 or 0. */
function roundedSign(value: number, decimals: number): number {
  const rounded = Number(value.toFixed(decimals));
  if (rounded > 0) return 1;
  if (rounded < 0) return -1;
  return 0;
}

export function formatInr(value: number | null | undefined, decimals = 2): string {
  if (isMissing(value)) {
    return EM_DASH;
  }
  const { negative, body } = formatMagnitude(value, decimals);
  return `${negative ? MINUS : ""}${RUPEE}${body}`;
}

export function formatPercent(value: number | null | undefined, decimals = 2): string {
  if (isMissing(value)) {
    return EM_DASH;
  }
  const sign = roundedSign(value, decimals);
  const body = Math.abs(value).toFixed(decimals);
  if (sign > 0) return `+${body}%`;
  if (sign < 0) return `${MINUS}${body}%`;
  return `${body}%`;
}

export function formatChange(
  value: number | null | undefined,
  percent: number | null | undefined,
): string {
  if (isMissing(value) || isMissing(percent)) {
    return EM_DASH;
  }
  const direction = roundedSign(value, 2) || roundedSign(percent, 2);
  if (direction === 0) {
    return "● 0.00%";
  }
  const arrow = direction > 0 ? "▲" : "▼";
  return `${arrow} ${formatSignedNumber(value, 2)} (${formatPercent(percent, 2)})`;
}

export function formatCrore(valueInCr: number | null | undefined): string {
  if (isMissing(valueInCr)) {
    return EM_DASH;
  }
  const { negative, body } = formatMagnitude(valueInCr, 0);
  return `${negative ? MINUS : ""}${RUPEE}${body} Cr`;
}
