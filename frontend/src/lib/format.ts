/** Human-friendly date/time formatting helpers. */

export function toDate(v: unknown): Date | null {
  if (v === null || v === undefined || v === "") return null;
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? null : d;
}

/** e.g. "Aug 30, 2026" */
export function formatDate(v: unknown): string {
  const d = toDate(v);
  if (!d) return v ? String(v) : "—";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** e.g. "Aug 30, 2026, 2:24 PM" */
export function formatDateTime(v: unknown): string {
  const d = toDate(v);
  if (!d) return v ? String(v) : "—";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Detect an ISO-like date/datetime string value. */
export function looksLikeDate(v: unknown): boolean {
  if (typeof v !== "string") return false;
  return /^\d{4}-\d{2}-\d{2}([T ]|$)/.test(v);
}

/** Format a value as a date if it looks like one, otherwise leave it unchanged. */
export function autoFormatDate(v: unknown): string {
  if (!looksLikeDate(v)) return v === null || v === undefined || v === "" ? "—" : String(v);
  const s = String(v);
  const hasTime = /[T ]\d{2}:\d{2}/.test(s);
  return hasTime ? formatDateTime(s) : formatDate(s);
}
