/**
 * Exact addition of decimal money strings ("12.50") using integer minor units (BigInt).
 * Used only to total figures the backend already computed (never floats, never recomputing
 * losses). Inputs with more than 2 decimals are truncated by rejecting them.
 */
const PATTERN = /^(-?)(\d+)(?:\.(\d{1,2}))?$/;

function toCents(value: string): bigint {
  const match = PATTERN.exec(value.trim());
  if (!match) throw new Error(`Invalid money amount: ${value}`);
  const [, sign = "", whole = "0", fraction = ""] = match;
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  return sign === "-" ? -cents : cents;
}

export function sumMoney(values: readonly string[]): string {
  const total = values.reduce((acc, v) => acc + toCents(v), 0n);
  const negative = total < 0n;
  const abs = negative ? -total : total;
  const whole = abs / 100n;
  const cents = (abs % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}${whole}.${cents}`;
}
