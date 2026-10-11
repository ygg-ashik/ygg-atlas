// Columns of the users table (one row per `UserOut`).
import { type User } from '@/api/admin-users';
import { Avatar, RolePill, StatusPill, Tag, type DataColumn } from '@/ui';
import { seenAt } from '../format';

const kindOf = (u: User) => (u.kind === 'service' ? 'service' : 'human');

export function userColumns(meId: string | null): DataColumn<User>[] {
  return [
    {
      key: 'email',
      header: 'Email',
      cell: (u) => (
        <span className="flex items-center gap-2.5">
          <Avatar name={u.display_name || u.email} kind={kindOf(u)} />
          <span className="text-ink">{u.email}</span>
        </span>
      ),
    },
    {
      key: 'name',
      header: 'Name',
      cell: (u) => (
        <span className="inline-flex items-center gap-2">
          {u.display_name}
          {u.id === meId && <Tag>you</Tag>}
        </span>
      ),
    },
    { key: 'role', header: 'Role', cell: (u) => <RolePill role={u.role} /> },
    {
      key: 'status',
      header: 'Status',
      cell: (u) => (
        <StatusPill tone={u.status === 'active' ? 'positive' : 'muted'}>{u.status}</StatusPill>
      ),
    },
    {
      key: 'kind',
      header: 'Kind',
      hideBelowWide: true,
      cell: (u) =>
        u.kind === 'service' ? (
          <Tag>service</Tag>
        ) : (
          <span className="text-caption text-muted-foreground">human</span>
        ),
    },
    { key: 'seen', header: 'Last seen', cell: (u) => seenAt(u.last_seen_at) },
  ];
}
