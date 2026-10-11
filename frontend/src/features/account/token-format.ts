// Display formatting for credentials on the account pages. All times are UTC.
import { formatDateTime } from '@/lib/utils';

/** `2026-10-09T09:47:00Z` → `2026-10-09`. */
export const isoDate = (iso: string) => iso.slice(0, 10);

/** Last use of a token or app; never used → `never`. */
export const lastUsed = (iso: string | null) => (iso ? formatDateTime(iso) : 'never');
