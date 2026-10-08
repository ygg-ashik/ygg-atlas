// src/lib/freshness.ts
// Provenance `freshness` is the newest-data timestamp a source reports
// (str(timestamp) from the connector). Stale = older than the source SLA.
export const STALE_AFTER_HOURS = 24;

export function parseFreshness(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = /^\d{4}-\d{2}-\d{2} \d/.test(value) ? value.replace(' ', 'T') : value;
  if (!/^\d{4}-\d{2}-\d{2}/.test(normalized)) return null;
  const date = new Date(normalized);
  return isNaN(date.getTime()) ? null : date;
}

export function freshnessLabel(value: string | null | undefined, now = new Date()): string {
  const date = parseFreshness(value);
  if (!date) return value ?? '';
  const minutes = Math.floor((now.getTime() - date.getTime()) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function isStale(value: string | null | undefined, now = new Date()): boolean {
  const date = parseFreshness(value);
  if (!date) return false;
  return now.getTime() - date.getTime() > STALE_AFTER_HOURS * 3_600_000;
}
