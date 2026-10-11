// Grant patterns and the grant editor's form rules. The pattern functions
// mirror backend app/access/patterns.py line for line (same test table), so
// the editor never offers a target the API would refuse. The browser decides
// nothing about access: the API re-validates every write.
import { isIsoDate } from '@/ui';

const SEGMENT = /^[a-z0-9_]+$/;
const MAX_SEGMENTS = 3;

/** The backend's refusal for a bad pattern, or null when it is valid. */
export function patternError(pattern: string): string | null {
  const segments = pattern.split('/');
  const malformed =
    segments.length < 1 ||
    segments.length > MAX_SEGMENTS ||
    segments.some((s) => s !== '*' && !SEGMENT.test(s));
  if (malformed) {
    return `'${pattern}' is not a resource pattern. Use paths like '*', 'deepsales/*' or 'demo/order/revenue'.`;
  }
  if (segments[segments.length - 1] !== '*' && segments.length !== MAX_SEGMENTS) {
    return `'${pattern}' names an entity or source; use '${pattern}/*' to cover it and everything under it.`;
  }
  return null;
}

/** A well-formed resource path: 2 or 3 `[a-z0-9_]+` segments. */
export function isResourcePath(path: string): boolean {
  const segments = path.split('/');
  return (segments.length === 2 || segments.length === 3) && segments.every((s) => SEGMENT.test(s));
}

const same = (pattern: string[], path: string[]) =>
  pattern.every((p, i) => i >= path.length || p === '*' || p === path[i]);

/** True if `pattern` covers `path`; both must already be well formed. */
export function matches(pattern: string, path: string): boolean {
  if (!path) return false;
  const want = pattern.split('/');
  const have = path.split('/');
  if (want[want.length - 1] === '*') {
    const prefix = want.slice(0, -1);
    return have.length >= prefix.length && same(prefix, have);
  }
  return want.length === have.length && same(want, have);
}

export type GrantEffectChoice = 'allow' | 'deny';

/** What the grant editor holds before review. `expiry` is YYYY-MM-DD or '' (never). */
export interface GrantDraft {
  subjectType: 'group' | 'user';
  targetKind: 'resource' | 'clearance';
  target: string;
  effect: GrantEffectChoice;
  expiry: string;
  reason: string;
  denyConfirmed: boolean;
}

export interface GrantDraftErrors {
  target?: string;
  expiry?: string;
  reason?: string;
  confirm?: string;
}

const FUTURE = 'The expiry must be in the future.';
const NEED_REASON = 'Direct user grants need a reason.';

function targetError(draft: GrantDraft): string | undefined {
  if (!draft.target) return 'Pick a catalog path to grant.';
  if (draft.targetKind !== 'resource') return undefined;
  return patternError(draft.target) ?? undefined;
}

function expiryError(expiry: string, today: string): string | undefined {
  if (!expiry) return undefined;
  if (!isIsoDate(expiry)) return 'Enter the expiry as YYYY-MM-DD, or choose Never.';
  return expiry > today ? undefined : FUTURE;
}

/** Field errors for a draft; empty when it may go to review. `today` is UTC YYYY-MM-DD. */
export function validateGrantDraft(draft: GrantDraft, today: string): GrantDraftErrors {
  const errors: GrantDraftErrors = {};
  const target = targetError(draft);
  if (target) errors.target = target;
  const expiry = expiryError(draft.expiry, today);
  if (expiry) errors.expiry = expiry;
  if (draft.subjectType === 'user' && !draft.reason.trim()) errors.reason = NEED_REASON;
  if (draft.effect === 'deny' && !draft.denyConfirmed) {
    errors.confirm = 'Confirm that this deny restricts everyone it reaches.';
  }
  return errors;
}

/** Today's date in UTC as YYYY-MM-DD. */
export function todayUtc(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/** `date` (YYYY-MM-DD, UTC) plus `days`. */
export function plusDays(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** The API's `expires_at` for an expiry date: midnight UTC; '' ⇒ null (never). */
export function expiryToIso(date: string): string | null {
  return date ? `${date}T00:00:00Z` : null;
}
