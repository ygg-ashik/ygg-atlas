// Display formatting for admin screens. All times are UTC end to end.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** `2026-10-09T09:47:00Z` → `2026-10-09`. */
export const isoDate = (iso: string) => iso.slice(0, 10);

/** `2026-10-09T09:47:00Z` → `09 Oct 09:47` (UTC); null → `never`. */
export function seenAt(iso: string | null): string {
  if (!iso) return 'never';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'never';
  const day = String(d.getUTCDate()).padStart(2, '0');
  const time = d.toISOString().slice(11, 16);
  return `${day} ${MONTHS[d.getUTCMonth()]} ${time}`;
}

/** `sara.mansour@yougotagift.com` → `sara.mansour@` (compact, for diff lines). */
export const shortEmail = (email: string) => `${email.split('@')[0]}@`;

/** "1 member" / "4 members". */
export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;
