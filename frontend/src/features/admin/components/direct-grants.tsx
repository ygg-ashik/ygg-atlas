import { useState } from 'react';
import { Diamond } from 'lucide-react';
import { type GrantOut } from '@/api/admin-groups';
import { type UserDetail } from '@/api/admin-users';
import { useRevokeGrant } from '@/api/hooks/use-admin-grants';
import { Button, DataTable, EmptyState, Tag, type DataColumn } from '@/ui';
import { isoDate, shortEmail } from '../format';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { grantRevokeLines } from '../review-lines';
import { GrantEditor } from './grant-editor';
import { EffectPill } from './effect-pill';
import { ReviewSlot } from './review-slot';

/** The backend's refusal for a self-grant (`create_grant`). */
const SELF_GRANT = "You can't grant access to yourself. Ask another admin.";

function columns(onRevoke: (g: GrantOut) => void): DataColumn<GrantOut>[] {
  return [
    { key: 'effect', header: 'Effect', cell: (g) => <EffectPill effect={g.effect} /> },
    {
      key: 'pattern',
      header: 'Pattern',
      cell: (g) => <span className="font-mono text-ink">{g.target}</span>,
    },
    { key: 'origin', header: 'Origin', cell: () => <Tag mono>user</Tag> },
    {
      key: 'expires',
      header: 'Expires',
      cell: (g) =>
        g.expires_at ? isoDate(g.expires_at) : <span className="text-muted-foreground">never</span>,
    },
    { key: 'reason', header: 'Reason', cell: (g) => g.reason },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'end',
      cell: (g) => (
        <Button
          variant="pill"
          size="sm"
          aria-label={`Revoke ${g.effect} ${g.target}`}
          onClick={() => onRevoke(g)}
        >
          Revoke
        </Button>
      ),
    },
  ];
}

/** Grants that apply to this user only. Each needs a reason; never to yourself. */
export function DirectGrants({ user, isSelf }: { user: UserDetail; isSelf: boolean }) {
  const [editing, setEditing] = useState(false);
  const write = useReviewedWrite();
  const revoke = useRevokeGrant();
  const subject = `user:${shortEmail(user.email)}`;
  const onRevoke = (g: GrantOut) =>
    write.open({
      slot: 'grant',
      title: 'Revoke grant',
      auditAction: 'grant.revoke',
      lines: grantRevokeLines(subject, g),
      applyLabel: 'Revoke grant',
      appliedLabel: 'Revoked',
      run: () => revoke.mutateAsync(g.id),
    });
  return (
    <div>
      <div className="mb-2.5 flex flex-wrap items-center gap-2">
        <span className="text-caption text-muted-foreground">
          Direct grants apply to this user only. Each needs a reason.
        </span>
        <Button
          variant="pill"
          className="ml-auto"
          disabled={isSelf || editing}
          title={isSelf ? SELF_GRANT : undefined}
          onClick={() => setEditing(true)}
        >
          ＋ Add grant
        </Button>
      </div>
      {isSelf && <p className="mb-2 text-caption text-body">{SELF_GRANT}</p>}
      <ReviewSlot write={write} slot="grant" />
      {user.direct_grants.length ? (
        <DataTable
          caption={`Direct grants of ${user.display_name || user.email}`}
          columns={columns(onRevoke)}
          rows={user.direct_grants}
          rowKey={(g) => g.id}
        />
      ) : (
        !editing && (
          <EmptyState icon={<Diamond className="h-5 w-5" />} title="No direct grants">
            Everything this user sees comes from their groups.
          </EmptyState>
        )
      )}
      {editing && (
        <GrantEditor
          subject={{ type: 'user', id: user.id, label: subject }}
          denyNotice={user.display_name || user.email}
          onClose={() => setEditing(false)}
        />
      )}
    </div>
  );
}
