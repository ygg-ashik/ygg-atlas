// Review lines for approving an access request: the exact change the backend
// stages for each kind (AccessRequests._stage_access), so what the decider
// approves is what the audit log records.
import { type RoleInfo } from '@/api/access';
import { type AccessRequest } from '@/api/access-requests';
import { type DiffLine } from '@/ui';
import { kv } from './review-lines';

const ctx = (text: string): DiffLine => ({ kind: 'context', text });
const add = (text: string): DiffLine => ({ kind: 'add', text });

/** The audit actions an approval records, per kind. */
export const APPROVE_AUDIT: Record<AccessRequest['kind'], string> = {
  group: 'request.approve + member.put',
  role: 'request.approve + user.role',
  resource: 'request.approve + grant.create',
};

/** The grant reason the backend writes for an approved resource request. */
const MAX_REASON = 500;
export const grantReason = (request: AccessRequest) =>
  `Access request ${request.id}: ${request.note}`.slice(0, MAX_REASON);

/** The capabilities `to` adds over `from` (empty when the catalog is not loaded). */
function gained(roles: readonly RoleInfo[], from: string, to: string): string[] {
  const before = new Set(roles.find((r) => r.name === from)?.capabilities ?? []);
  return (roles.find((r) => r.name === to)?.capabilities ?? []).filter((c) => !before.has(c));
}

/** `role a → b` as the card shows it; just the target once the request is decided. */
export function requestTargetText(request: AccessRequest): string {
  const from = request.requester?.role;
  if (request.kind === 'role' && request.status === 'pending' && from) {
    return `${from} → ${request.target_label}`;
  }
  return request.target_label;
}

export interface ApproveLineOptions {
  /** Resource kind only: YYYY-MM-DD, or '' for no expiry. */
  expiry: string;
  roles: readonly RoleInfo[];
}

/** The diff an approval applies, per kind. */
export function approveLines(
  request: AccessRequest,
  { expiry, roles }: ApproveLineOptions,
): DiffLine[] {
  const email = request.requester?.email ?? 'the requester';
  const head = ctx(`request ${request.id.slice(0, 8)}  ${email}`);
  if (request.kind === 'group') {
    return [head, add(`member ${email} in ${request.target_label}`)];
  }
  if (request.kind === 'role') {
    const from = request.requester?.role ?? '—';
    const gains = gained(roles, from, request.target);
    return [
      head,
      add(`role ${from} → ${request.target}`),
      ...(gains.length ? [ctx(kv('gains', gains.join(', ')))] : []),
    ];
  }
  const until = expiry ? ` until ${expiry}` : ', no expiry';
  return [
    head,
    add(`grant allow ${request.target} for ${email}${until}`),
    ctx(kv('reason', grantReason(request))),
  ];
}
