// Review-card diffs. Each builder mirrors the `rbac_changes` row the write
// records (action, then the before → after fields), so what the admin approves
// is what the audit log shows afterwards.
import { type RoleInfo } from '@/api/access';
import { type GrantOut, type RowScope } from '@/api/admin-groups';
import { type LabelClass, type LabelClassPut } from '@/api/row-field';
import { CREDENTIAL_EVENT } from '@/api/credential-events';
import { type DiffLine } from '@/ui';
import { type ReviewSpec } from './hooks/use-reviewed-write';

const KEY_WIDTH = 10;
/** `key` padded to the audit column (at least one space before the value). */
export const kv = (key: string, value: string) => `${key.padEnd(KEY_WIDTH - 1)} ${value}`;
const ctx = (text: string): DiffLine => ({ kind: 'context', text });
const add = (text: string): DiffLine => ({ kind: 'add', text });
const rm = (text: string): DiffLine => ({ kind: 'remove', text });
const NONE = '—';

/** `2026-12-31T00:00:00Z` → `2026-12-31`; null → never. */
export const expiryLabel = (iso: string | null) => (iso ? iso.slice(0, 10) : 'never');

function capabilitiesOf(roles: readonly RoleInfo[], role: string): Set<string> {
  return new Set(roles.find((r) => r.name === role)?.capabilities ?? []);
}

/** `user.role`: before {role} → after {role}, plus the capabilities that move. */
export function roleChangeLines(
  email: string,
  from: string,
  to: string,
  roles: readonly RoleInfo[],
): DiffLine[] {
  const before = capabilitiesOf(roles, from);
  const after = capabilitiesOf(roles, to);
  const gained = [...after].filter((c) => !before.has(c));
  const lost = [...before].filter((c) => !after.has(c));
  return [
    ctx(`user.role  ${email}`),
    rm(kv('role', from)),
    add(kv('role', to)),
    // Capabilities follow from the role; they are not fields of the change row.
    ...(gained.length ? [ctx(kv('gains', gained.join(', ')))] : []),
    ...(lost.length ? [ctx(kv('loses', lost.join(', ')))] : []),
  ];
}

/** `user.status`: before {status} → after {status}. */
export function statusChangeLines(email: string, from: string, to: string): DiffLine[] {
  const lines = [ctx(`user.status  ${email}`), rm(kv('status', from)), add(kv('status', to))];
  if (to === 'disabled') lines.push(ctx('their sign-in sessions end and every check denies'));
  return lines;
}

export interface GrantShape {
  effect: string;
  target_kind: string;
  target: string;
  reason: string;
  expires_at: string | null;
  row_scope?: RowScope | null;
}

/** `country=AE,SA; channel=paid`. */
export const scopeText = (scope: RowScope) =>
  Object.entries(scope)
    .map(([dim, values]) => `${dim}=${values.join(',')}`)
    .join('; ');

function grantFields(grant: GrantShape, mark: (text: string) => DiffLine): DiffLine[] {
  return [
    mark(kv('effect', grant.effect)),
    mark(kv(grant.target_kind === 'resource' ? 'target' : grant.target_kind, grant.target)),
    mark(kv('expires', grant.expires_at ? expiryLabel(grant.expires_at) : NONE)),
    ...(grant.reason ? [mark(kv('reason', grant.reason))] : []),
    ...scopeLines(grant, mark),
  ];
}

/** A resource allow always states its rows: the scope, or "all rows" when unscoped. */
function scopeLines(grant: GrantShape, mark: (text: string) => DiffLine): DiffLine[] {
  if (grant.row_scope) return [mark(kv('scope', scopeText(grant.row_scope)))];
  if (grant.target_kind === 'resource' && grant.effect === 'allow') {
    return [ctx(kv('scope', 'all rows'))];
  }
  return [];
}

/** `grant.create` on `subject` (e.g. `group:marketing`), with how far it reaches. */
export function grantCreateLines(subject: string, grant: GrantShape, reach?: string): DiffLine[] {
  return [
    ctx(`grant.create  ${subject}`),
    ...grantFields(grant, add),
    ...(reach ? [ctx(reach)] : []),
  ];
}

/** `grant.revoke`: the whole row goes. */
export function grantRevokeLines(subject: string, grant: GrantOut, reach?: string): DiffLine[] {
  return [
    ctx(`grant.revoke  ${subject}`),
    ...grantFields(grant, rm),
    ...(reach ? [ctx(reach)] : []),
  ];
}

/** `member.put`: standing before (— when new) → after. */
export function memberPutLines(
  group: string,
  email: string,
  before: string | null,
  after: string,
): DiffLine[] {
  return [
    ctx(`member.put  ${group}`),
    ctx(kv('user', email)),
    rm(kv('standing', before ?? NONE)),
    add(kv('standing', after)),
  ];
}

/** `member.remove`: standing → —. */
export function memberRemoveLines(group: string, email: string, standing: string): DiffLine[] {
  return [
    ctx(`member.remove  ${group}`),
    ctx(kv('user', email)),
    rm(kv('standing', standing)),
    add(kv('standing', NONE)),
  ];
}

/** `group.delete`: the group row goes. */
export function groupDeleteLines(name: string, parent: string | null): DiffLine[] {
  return [ctx(`group.delete  ${name}`), rm(kv('name', name)), rm(kv('parent', parent ?? NONE))];
}

export interface TokenLine {
  prefix: string;
  name: string;
  /** `TokenKind`; `oauth_*` tokens belong to connected apps. */
  kind?: string;
}

const isOAuth = (t: TokenLine) => t.kind?.startsWith('oauth') ?? false;

/** The credential event a revoke-all records (`credential_events`, not `rbac_changes`). */
export const TOKEN_REVOKE_ALL = CREDENTIAL_EVENT.tokensRevokedAll;
/** The credential event a single revoke records. */
export const TOKEN_REVOKE = CREDENTIAL_EVENT.tokenRevoked;
/** The credential event an OAuth client revoke records. */
export const CLIENT_REVOKE = CREDENTIAL_EVENT.clientRevoked;

/** Revoke-all (a credential event, not an rbac change). The endpoint
 * revokes every live token of the user, whatever its kind, so `tokens` must be
 * the unfiltered list; OAuth tokens mean connected apps lose access too. */
export function revokeAllLines(email: string, tokens: readonly TokenLine[]): DiffLine[] {
  const apps = tokens.some(isOAuth);
  return [
    ctx(`${TOKEN_REVOKE_ALL}  ${email}`),
    ...tokens.map((t) => rm(kv('token', `${t.prefix}…  ${t.name}`))),
    ctx(
      apps
        ? 'connected apps lose access too: their OAuth tokens are revoked'
        : 'every live token of any kind; each gets 401 on its next call',
    ),
  ];
}

/** The `rbac_changes` actions of attribute writes (backend `AccessAdmin`). */
export const ATTRIBUTE_SET = 'attribute.set';
export const ATTRIBUTE_DELETE = 'attribute.delete';
export const LABEL_CLASS_UPDATE = 'label_class.update';

/** Per-key attribute write: `attribute.set` or `attribute.delete`. */
export function attributeLines(
  email: string,
  key: string,
  before: string | null,
  after: string | null,
): DiffLine[] {
  return [
    ctx(`${after === null ? ATTRIBUTE_DELETE : ATTRIBUTE_SET}  ${email}`),
    ...(before !== null ? [rm(kv(key, before))] : []),
    ...(after !== null ? [add(kv(key, after))] : []),
  ];
}

/** Single token revoke (a credential event). */
export function tokenRevokeLines(token: TokenLine): DiffLine[] {
  return [
    ctx(TOKEN_REVOKE),
    rm(kv('token', `${token.prefix}…  ${token.name}`)),
    ctx('anything using it gets 401 on the next call'),
  ];
}

/** The review of revoking one token (Admin › Tokens and the ⌘K quick action). */
export function tokenRevokeReview(
  token: TokenLine,
  slot: string,
  run: () => Promise<unknown>,
): ReviewSpec {
  return {
    slot,
    title: 'Revoke token',
    auditAction: TOKEN_REVOKE,
    lines: tokenRevokeLines(token),
    applyLabel: 'Revoke token',
    appliedLabel: 'Revoked',
    retryOn409: false,
    run,
  };
}

/** OAuth client revoke: every connected sign-in through it ends. */
export function clientRevokeLines(
  client: { client_id: string; client_name: string },
  activeFamilies: number,
): DiffLine[] {
  const signIns = `${activeFamilies} connected sign-in${activeFamilies === 1 ? '' : 's'}`;
  return [
    ctx(`${CLIENT_REVOKE}  ${client.client_id}`),
    rm(kv('client', client.client_name)),
    ctx(`${signIns} stop working immediately`),
  ];
}

/** `label_class.update`: the row's `mode` and `bucket_size` before → after.
 * An omitted `bucket_size` keeps the stored one, as the backend does. */
export function labelClassLines(current: LabelClass, next: LabelClassPut): DiffLine[] {
  const size = next.bucket_size ?? current.bucket_size;
  const lines = [ctx(`${LABEL_CLASS_UPDATE}  ${current.label_class}`)];
  if (next.mode !== current.mode) {
    lines.push(rm(kv('mode', current.mode)), add(kv('mode', next.mode)));
  }
  if (size !== current.bucket_size) {
    lines.push(rm(kv('bucket', String(current.bucket_size))), add(kv('bucket', String(size))));
  }
  lines.push(ctx('applies to every caller without the matching clearance'));
  return lines;
}
