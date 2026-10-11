// A readable name for an `rbac_changes` row's object ("nour.alamin@ → marketing"),
// built from the row's own before/after snapshots plus names the viewer has
// already loaded. Display only: the raw id stays in the expanded diff.
import { type Change } from '@/api/audit';
import { shortEmail } from './format';

/** Names the screen already knows; any miss falls back to a short id. */
export interface NameBook {
  group: (id: string) => string | undefined;
  user: (id: string) => string | undefined;
}

export const NO_NAMES: NameBook = { group: () => undefined, user: () => undefined };

interface NamedGroup {
  id: string;
  name: string;
}
interface NamedUser {
  user_id: string;
  email: string;
}

/** A book over loaded groups and users (users show as `local.part@`). */
export function nameBook({
  groups = [],
  users = [],
}: {
  groups?: readonly NamedGroup[];
  users?: readonly NamedUser[];
}): NameBook {
  const groupNames = new Map(groups.map((g) => [g.id, g.name]));
  const userNames = new Map(users.map((u) => [u.user_id, shortEmail(u.email)]));
  return { group: (id) => groupNames.get(id), user: (id) => userNames.get(id) };
}

/** `6f1c2a90-1111-…` → `6f1c2a90…`; ids of 12 characters or fewer stay whole. */
export function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}

const text = (value: unknown): string | undefined =>
  typeof value === 'string' && value ? value : undefined;

function groupName(id: string | undefined, names: NameBook): string {
  if (!id) return 'group';
  return names.group(id) ?? `group ${shortId(id)}`;
}

function userName(id: string | undefined, names: NameBook): string {
  if (!id) return 'user';
  return names.user(id) ?? `user ${shortId(id)}`;
}

function subjectName(snap: Record<string, unknown>, names: NameBook): string {
  const kind = text(snap.subject_type);
  const id = text(snap.subject_id);
  if (kind === 'group' && id) return `group:${names.group(id) ?? shortId(id)}`;
  if (kind === 'user' && id) return `user:${names.user(id) ?? shortId(id)}`;
  return 'grant';
}

type Snapshot = Record<string, unknown>;
type Labeler = (change: Change, snap: Snapshot, names: NameBook) => string;

const LABELERS: Record<string, Labeler> = {
  group_member: (change, snap, names) => {
    const [groupKey, userKey] = change.object_id.split(':');
    const user = userName(text(snap.user_id) ?? userKey, names);
    const group = groupName(text(snap.group_id) ?? groupKey, names);
    return `${user} ${change.action === 'member.remove' ? '←' : '→'} ${group}`;
  },
  group: (change, snap, names) => text(snap.name) ?? groupName(change.object_id, names),
  grant: (change, snap, names) => {
    const target = text(snap.target);
    const subject = subjectName(snap, names);
    if (!target) return `${subject} ${shortId(change.object_id)}`;
    return `${subject} · ${snap.effect === 'deny' ? 'deny ' : ''}${target}`;
  },
  user: (change, snap, names) => {
    const email = text(snap.email);
    return email ? shortEmail(email) : userName(change.object_id, names);
  },
  access_request: (change, snap, names) => {
    const requester = text(snap.user_id);
    const ref = `r-${change.object_id.slice(0, 4)}`;
    return requester ? `${ref} · ${userName(requester, names)}` : ref;
  },
};

/** The Object column text for one change. */
export function changeLabel(change: Change, names: NameBook = NO_NAMES): string {
  const labeler = LABELERS[change.object_type];
  if (!labeler) return `${change.object_type} ${shortId(change.object_id)}`;
  return labeler(change, change.after ?? change.before ?? {}, names);
}
