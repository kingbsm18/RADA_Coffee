/** Display formatting. Money arrives as decimal strings and is never parsed to float for math. */

const TZ = "Africa/Casablanca";

export function formatTime(iso: string, timeZone: string = TZ): string {
  return new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone }).format(new Date(iso));
}

export function formatDateTime(iso: string, timeZone: string = TZ): string {
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short", timeZone }).format(new Date(iso));
}

/** Calendar day (YYYY-MM-DD) of `date` in the given time zone. */
export function dayInZone(date: Date, timeZone: string = TZ): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone }).format(date);
}

/**
 * Money display from a backend decimal string ("12.50"). Digit grouping is done on the
 * string; the amount is not converted to a number.
 */
export function formatMoney(amount: string, currency = "MAD"): string {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(amount.trim());
  if (!match) return `${amount} ${currency}`;
  const [, sign = "", whole = "0", fraction = ""] = match;
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, "\u202f");
  const cents = fraction.padEnd(2, "0").slice(0, 2);
  return `${sign}${grouped},${cents}\u00a0${currency}`;
}

export function formatConfidence(confidence: number): string {
  return `${Math.round(confidence * 100)} %`;
}

export function relativeAge(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `il y a ${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `il y a ${hours} h`;
  return `il y a ${Math.floor(hours / 24)} j`;
}
