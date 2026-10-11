import { useState } from 'react';
import { Lock } from 'lucide-react';
import { type GrantOut, type GroupDetail } from '@/api/admin-groups';
import { useGrants, useRevokeGrant } from '@/api/hooks/use-admin-grants';
import { Button, ErrorNotice, SkeletonRegion, SkeletonRows } from '@/ui';
import { plural } from '../format';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { grantRevokeLines } from '../review-lines';
import { GrantEditor } from './grant-editor';
import { GrantList } from './grant-list';
import { ReviewSlot } from './review-slot';

interface GroupGrantsProps {
  group: GroupDetail;
  /** Names of the subgroups that inherit these grants. */
  subgroups: readonly string[];
  canEdit: boolean;
}

function reachOf(group: GroupDetail, subgroups: readonly string[]): string {
  const members = plural(group.member_count, 'member');
  return subgroups.length ? `reaches ${members} + ${subgroups.join(', ')}` : `reaches ${members}`;
}

/** A group's data grants. Only admin:groups reads or changes them. */
export function GroupGrants({ group, subgroups, canEdit }: GroupGrantsProps) {
  const grants = useGrants(canEdit ? { subjectType: 'group', subjectId: group.id } : null);
  const revoke = useRevokeGrant();
  const write = useReviewedWrite();
  const [editing, setEditing] = useState(false);
  const subject = `group:${group.name}`;
  const members = plural(group.member_count, 'member');
  const onRevoke = (g: GrantOut) =>
    write.open({
      slot: 'grant',
      title: 'Revoke grant',
      auditAction: 'grant.revoke',
      lines: grantRevokeLines(
        subject,
        g,
        g.effect === 'deny' ? `lifts a restriction for ${members}` : `removes it for ${members}`,
      ),
      applyLabel: 'Revoke grant',
      appliedLabel: 'Revoked',
      run: () => revoke.mutateAsync(g.id),
    });
  const inherited = subgroups.length ? `this group and ${subgroups.join(', ')}` : 'members';
  return (
    <section aria-label="Grants">
      <h3 className="mb-2.5 mt-3 flex flex-wrap items-baseline gap-2 font-serif text-section text-ink">
        Grants
        <span className="font-sans text-caption tabular-nums text-muted-foreground">
          {group.grant_count} · inherited by {inherited}
        </span>
      </h3>
      {!canEdit && (
        <p className="mb-2 flex items-center gap-1.5 text-caption text-muted-foreground">
          <Lock aria-hidden className="h-3 w-3" />
          Managing grants needs <span className="font-mono">admin:groups</span>.
        </p>
      )}
      {canEdit && !editing && (
        <Button variant="pill" className="mb-2.5" onClick={() => setEditing(true)}>
          ＋ Add grant
        </Button>
      )}
      <ReviewSlot write={write} slot="grant" />
      {grants.isLoading && (
        <SkeletonRegion label="grants" className="rounded-lg bg-card">
          <SkeletonRows count={2} />
        </SkeletonRegion>
      )}
      {grants.isError && (
        <ErrorNotice
          title="Couldn't load grants"
          onRetry={() => void grants.refetch()}
          retrying={grants.isFetching}
        />
      )}
      <GrantList grants={grants.data ?? []} label={`Grants of ${group.name}`} onRevoke={onRevoke} />
      {editing && (
        <GrantEditor
          subject={{ type: 'group', id: group.id, label: subject }}
          reach={reachOf(group, subgroups)}
          denyNotice={
            subgroups.length
              ? `Everyone in ${group.name} and its subgroups (${subgroups.join(', ')})`
              : `Everyone in ${group.name}`
          }
          restrictCount={group.member_count}
          onClose={() => setEditing(false)}
        />
      )}
    </section>
  );
}
