// Review-card diffs. Each builder mirrors the `rbac_changes` row the write
// records (action, then the before → after fields), so what the admin approves
// is what the audit log shows afterwards.
import { type RoleInfo } from '@/api/access';
import { type GrantOut, type RowScope } from '@/api/admin-groups';
import { type DiffLine } from '@/ui';

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

const scopeText = (scope: RowScope) =>
  Object.entries(scope)
    .map(([dim, values]) => `${dim}=${values.join(',')}`)
    .join('; ');

function grantFields(grant: GrantShape, mark: (text: string) => DiffLine): DiffLine[] {
  return [
    mark(kv('effect', grant.effect)),
    mark(kv(grant.target_kind === 'resource' ? 'target' : grant.target_kind, grant.target)),
    mark(kv('expires', grant.expires_at ? expiryLabel(grant.expires_at) : NONE)),
    ...(grant.reason ? [mark(kv('reason', grant.reason))] : []),
    ...(grant.row_scope ? [mark(kv('scope', scopeText(grant.row_scope)))] : []),
  ];
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
}

/** The phase-4 credential event a revoke-all records (`credential_events`, not `rbac_changes`). */
export const TOKEN_REVOKE_ALL = 'token.revoke_all';

/** Phase-4 revoke-all (a credential event, not an rbac change). */
export function revokeAllLines(email: string, tokens: readonly TokenLine[]): DiffLine[] {
  return [
    ctx(`${TOKEN_REVOKE_ALL}  ${email}`),
    ...tokens.map((t) => rm(kv('token', `${t.prefix}…  ${t.name}`))),
    ctx('connected apps keep working until revoked separately'),
  ];
}

/** Phase-3 per-key attribute write. */
export function attributeLines(
  email: string,
  key: string,
  before: string | null,
  after: string | null,
): DiffLine[] {
  return [
    ctx(`${after === null ? 'attribute.delete' : 'attribute.put'}  ${email}`),
    ...(before !== null ? [rm(kv(key, before))] : []),
    ...(after !== null ? [add(kv(key, after))] : []),
  ];
}

/** Phase-4 single token revoke (a credential event). */
export function tokenRevokeLines(token: TokenLine): DiffLine[] {
  return [
    ctx('token.revoke'),
    rm(kv('token', `${token.prefix}…  ${token.name}`)),
    ctx('anything using it gets 401 on the next call'),
  ];
}

/** Phase-4 OAuth client revoke: every connected sign-in through it ends. */
export function clientRevokeLines(
  client: { client_id: string; client_name: string },
  activeFamilies: number,
): DiffLine[] {
  const signIns = `${activeFamilies} connected sign-in${activeFamilies === 1 ? '' : 's'}`;
  return [
    ctx(`client.revoke  ${client.client_id}`),
    rm(kv('client', client.client_name)),
    ctx(`${signIns} stop working immediately`),
  ];
}
