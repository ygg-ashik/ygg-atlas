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

/** The backend skips the write when the access is already held (P5-D7): the
 * approval then records the decision only. Never promise a write it skips. */
export const NO_CHANGE_IF_HELD: Record<AccessRequest['kind'], string> = {
  group: 'no change if already a member (any standing): records the decision only',
  role: 'no change if already at or above this role: records the decision only',
  resource: 'no change if the same live allow exists: records the decision only',
};

/** Catalog order is rank order (viewer < analyst < builder < admin); -1 unknown. */
const rankOf = (roles: readonly RoleInfo[], role: string) =>
  roles.findIndex((r) => r.name === role);

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
    return [head, add(`member ${email} in ${request.target_label}`), ctx(NO_CHANGE_IF_HELD.group)];
  }
  if (request.kind === 'role') {
    const from = request.requester?.role ?? '—';
    const fromRank = rankOf(roles, from);
    const toRank = rankOf(roles, request.target);
    if (fromRank >= 0 && toRank >= 0 && fromRank >= toRank) {
      return [
        head,
        ctx(`role ${from} already at or above ${request.target}: records the decision only`),
      ];
    }
    const gains = gained(roles, from, request.target);
    return [
      head,
      add(`role ${from} → ${request.target}`),
      ...(gains.length ? [ctx(kv('gains', gains.join(', ')))] : []),
      ctx(NO_CHANGE_IF_HELD.role),
    ];
  }
  const until = expiry ? ` until ${expiry}` : ', no expiry';
  return [
    head,
    add(`grant allow ${request.target} for ${email}${until}`),
    ctx(kv('reason', grantReason(request))),
    ctx(NO_CHANGE_IF_HELD.resource),
  ];
}
