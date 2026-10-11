// One translation from an HTTP failure to what the UI says. The backend's
// sentence is the message (spec: errors are stated as business facts); the
// browser never invents its own reason for a denial.
import { type QueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { queryKeys } from './query-keys';

export type MutationErrorKind =
  | 'conflict'
  | 'forbidden'
  | 'unauthenticated'
  | 'not_found'
  | 'invalid'
  | 'rate_limited'
  | 'unavailable'
  | 'network'
  | 'unknown';

export interface MutationErrorInfo {
  kind: MutationErrorKind;
  status: number | null;
  message: string;
  /** Present only for a 409 from a write that opted in (`retryOn409`): render
   * the action toast with a Retry action. */
  retry: { actionLabel: string } | null;
}

export interface MutationErrorOptions {
  /** Offer Retry on a 409. Only for writes whose 409 means "access changed while
   * this request was running" (the stale-actor check in AccessAdmin's write
   * lock): retrying against refreshed access can succeed. Other 409s ("already
   * decided", "already asked", "can't change your own role") are final. */
  retryOn409?: boolean;
}

const KIND_BY_STATUS: Record<number, MutationErrorKind> = {
  400: 'invalid',
  401: 'unauthenticated',
  403: 'forbidden',
  404: 'not_found',
  409: 'conflict',
  422: 'invalid',
  429: 'rate_limited',
  503: 'unavailable',
};

const FALLBACK: Record<MutationErrorKind, string> = {
  conflict: 'Access changed while this request was running; retry.',
  forbidden: "You don't have access to do that.",
  unauthenticated: 'Your session ended. Sign in again.',
  not_found: 'That no longer exists.',
  invalid: 'That change is not valid.',
  rate_limited: 'Too many attempts. Wait a moment and try again.',
  unavailable: 'The access check is unavailable right now.',
  network: "Couldn't reach Atlas. Check your connection and try again.",
  unknown: 'Something went wrong.',
};

/** The backend's message from `{detail: str}`, `{detail: {message}}` or a
 * FastAPI validation list `{detail: [{msg}]}`; null when there is none. */
export function backendDetail(data: unknown): string | null {
  if (typeof data !== 'object' || data === null) return null;
  const detail = (data as { detail?: unknown }).detail;
  if (typeof detail === 'string') return detail || null;
  if (Array.isArray(detail)) {
    const first: unknown = detail[0];
    const msg =
      typeof first === 'object' && first !== null ? (first as { msg?: unknown }).msg : null;
    return typeof msg === 'string' ? msg : null;
  }
  if (typeof detail === 'object' && detail !== null) {
    const message = (detail as { message?: unknown }).message;
    return typeof message === 'string' ? message : null;
  }
  return null;
}

export function describeMutationError(
  error: unknown,
  { retryOn409 = false }: MutationErrorOptions = {},
): MutationErrorInfo {
  if (!isAxiosError(error)) return info('unknown', null, null);
  const response = error.response;
  if (!response) return info('network', null, null);
  const kind = KIND_BY_STATUS[response.status] ?? 'unknown';
  // An unexpected status keeps the generic sentence: a 500 body is not a business fact.
  const detail = kind === 'unknown' ? null : backendDetail(response.data);
  const described = info(kind, response.status, detail);
  if (kind === 'conflict' && retryOn409) described.retry = { actionLabel: 'Retry' };
  return described;
}

function info(
  kind: MutationErrorKind,
  status: number | null,
  detail: string | null,
): MutationErrorInfo {
  return { kind, status, message: detail ?? FALLBACK[kind], retry: null };
}

/** `onError` for every access write. Any 409 refetches `/me/access` (whatever
 * conflicted, the caller's view may be stale); Retry is offered only on opt-in. */
export function handleMutationError(
  qc: QueryClient,
  error: unknown,
  options: MutationErrorOptions = {},
): MutationErrorInfo {
  const described = describeMutationError(error, options);
  if (described.kind === 'conflict') void qc.invalidateQueries({ queryKey: queryKeys.myAccess });
  return described;
}
